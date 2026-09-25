"""LLM-written social captions (via OpenRouter): persona prompt built from the
hooks layer, best-of-N drafts across the free models, hard filters plus an LLM
judge to pick one, and the bundle builder combining it with the static blog
copy."""

import json
import re
import time

import openai
import requests
from openai import OpenAI

from social_posts.hooks import build_facts
from social_posts.static_copy import build_static_blog, build_static_title
from social_posts.voice import PERSONAS, opening, pick_persona, recent_openings


def get_openai_client(api_key: str):
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


# The blog copy is produced from static templates (build_static_blog); the
# language model only writes the social post. That one text has to satisfy the
# tightest platform: Bluesky allows 300 characters and, unlike Twitter's t.co
# wrapping, counts the full URL, so we cap the text well below 300 once the link
# (worst case ~60 chars) and a separating space are appended.
SOCIAL_TEXT_MAX = 230

# Drafts collected per post, and the total model calls allowed to collect them
# (free models fail validation or rate-limit often, so the budget is > N).
DRAFT_COUNT = 4
MAX_DRAFT_CALLS = 12
MAX_NUMBERS_IN_POST = 3
DRAFT_TEMPERATURE = 0.9

SOCIAL_PROMPT_TEMPLATE = """You write one social media post for MythiStone (mythistone.com), a World of Warcraft Mythic+ statistics site built on millions of real M+ runs. Today's subject: {subject}. An image with the full data is attached to the post, so do not list stats: tell one story.

VOICE: {persona_name}. {persona_brief}
Examples of this voice (tone only, never reuse their names, numbers or wording):
{persona_examples}

STORY HOOKS (pre-computed and accurate, pick ONE and build the post around it):
{hooks}

SUPPORTING FACTS (use at most one of these, only if it helps the hook):
{facts}

RULES:
- Build the post around ONE hook. Use at most 2 numbers, copied exactly as written above. Never invent, round or recalculate a number.
- Sound like a person in the WoW community, not a report. A joke, a jab at the meta, or a relatable M+ moment is the point of the post, but keep it grounded in the hook.
- Do not list stats, do not write "X has spoken", do not use labels like "timed_pct" or "Runs tracked".
- Do not imply most players pick something that only a minority picks.
- Do not start like any of these recent posts: {recent}
- Plain text only: no emojis, no markdown, no em dashes, no semicolons.
- At most {max_chars} characters, ending with 2 hashtags such as #WoW #MythicPlus.
- Do not include any URL, the link is appended separately.

Respond with ONLY the post text: no quotes, no JSON, no code fences, no commentary.
"""

JUDGE_PROMPT_TEMPLATE = """You are the social media editor for a World of Warcraft Mythic+ stats site. Score each draft post from 1 to 10 on:
- hook: does it lead with one interesting idea instead of a stat list
- humor: is it actually funny or charming to a Mythic+ player
- clarity: is it easy to read in one pass
- accuracy: does it only state things supported by the FACTS (10 = fully supported, 1 = misleading)

FACTS:
{facts}

DRAFTS:
{drafts}

Respond with ONLY a JSON array, one object per draft, like:
[{{"id": 1, "hook": 7, "humor": 6, "clarity": 8, "accuracy": 9}}]
"""


_UNICODE_REPLACEMENTS = {
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",
}


def sanitize_text(text):
    """Normalize fancy punctuation and strip emojis/symbols; keep newlines."""
    for src, dst in _UNICODE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = "".join(ch for ch in text if ch == "\n" or 32 <= ord(ch) < 0x2500)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return text.strip()


def clean_social_response(raw):
    """Strip code fences and wrapping quotes from a plain-text model response."""
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", raw).strip()
    # models sometimes wrap the whole post in matching quotes
    if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
        raw = raw[1:-1].strip()
    return raw


def _digit_runs(text):
    return set(re.findall(r"\d+", text))


def _number_tokens(text):
    """Distinct numbers as a reader sees them ('+22', '28:43.821', '87%' count once)."""
    return re.findall(r"\d[\d.,:]*", re.sub(r"#\w+", "", text))


def validate_social_text(text, facts_text, avoid_openings=()):
    """Return a list of problems; empty list means the social text is usable."""
    if not isinstance(text, str) or not text.strip():
        return ["empty social text"]
    problems = []
    # Every multi-digit number in the output must literally appear in the
    # facts or hooks; this rejects invented/garbled stats. Single digits are
    # allowed (e.g. "top 5") since they are harmless and often legitimate phrasing.
    allowed = _digit_runs(facts_text)
    unknown = {n for n in _digit_runs(text) if len(n) > 1 and n not in allowed}
    if unknown:
        problems.append(f"invents numbers not in the data: {sorted(unknown)}")
    if len(text) > SOCIAL_TEXT_MAX:
        problems.append(f"too long ({len(text)} > {SOCIAL_TEXT_MAX})")
    if re.search(r"\b[a-z]+_[a-z_]+\b", text):
        problems.append("leaks a raw data key")
    if len(_number_tokens(text)) > MAX_NUMBERS_IN_POST:
        problems.append("reads like a stat list")
    if ";" in text:
        problems.append("uses a semicolon")
    start = opening(text, 4).lower()
    if any(start == opening(o, 4).lower() for o in avoid_openings):
        problems.append("repeats a recent opening")
    return problems


# OpenRouter's model catalog churns constantly: free models are enabled and
# disabled, and their version-suffixed ids bump, so we discover the currently
# available free models at runtime instead of hardcoding a list that rots.
MODELS_URL = "https://openrouter.ai/api/v1/models"

# How many of the top-ranked free models generate_social_text will try (across
# its retries) before giving up. Bounded so one run does not fan out over the
# whole free catalog.
TOP_N_MODELS = 6

# Soft, order-of-preference nudge toward strong instruct families, matched as
# lowercase substrings of the model id/name. This is a bonus, NOT an allowlist:
# a model in no family still ranks on its size/context alone, so nothing breaks
# when a family disappears from the free tier. Optional to tweak, safe to leave.
_PREFERRED_FAMILIES = (
    "deepseek",
    "qwen",
    "llama",
    "mistral",
    "gemma",
    "glm",
)

# Below this many billion parameters, instruction-following gets shaky (tiny
# models tend to invent numbers and fail validate_social_text), so they are
# penalised rather than excluded.
_MIN_GOOD_PARAMS_B = 7.0
# Past this size the benefit flattens for a <230-char caption, so we stop
# rewarding raw size to avoid always preferring the single largest model.
_PARAM_SIZE_CAP_B = 70.0

_free_models_cache = None


def _parse_param_size_b(model):
    """Best-effort parameter count in billions parsed from the id/name.

    Handles plain sizes ("70b", "8b"), decimals ("3.8b") and MoE forms where the
    total is what matters ("235b-a22b" -> 235). Returns 0.0 when no size token is
    present (many strong models omit it), so size is a bonus, never a gate.
    """
    text = f"{model.get('id', '')} {model.get('name', '')}".lower()
    sizes = [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)\s*b\b", text)]
    return max(sizes) if sizes else 0.0


def _score_model(model):
    """Rank score for a free chat model; higher is better."""
    score = 0.0

    size_b = _parse_param_size_b(model)
    if size_b:
        score += min(size_b, _PARAM_SIZE_CAP_B)
        if size_b < _MIN_GOOD_PARAMS_B:
            score -= 100.0  # keep tiny models as last resort, not first pick

    haystack = f"{model.get('id', '')} {model.get('name', '')}".lower()
    for rank, family in enumerate(_PREFERRED_FAMILIES):
        if family in haystack:
            # earlier families in the tuple get the bigger bonus
            score += 50.0 * (len(_PREFERRED_FAMILIES) - rank)
            break

    # minor tiebreak: prefer more context, scaled well below the other signals
    score += min(model.get("context_length") or 0, 200_000) / 100_000.0
    return score


def _is_usable_text_model(model):
    """True when a model can take text in, return text out, and do chat."""
    arch = model.get("architecture") or {}
    inputs = arch.get("input_modalities") or []
    outputs = arch.get("output_modalities") or []
    # Text must be an accepted input (multimodal inputs are fine, we only send
    # text), and text must be the ONLY output: this drops embedding/vision-in
    # models AND generative audio/image models (e.g. music models that happen to
    # also emit a text field alongside audio).
    if "text" not in inputs or set(outputs) != {"text"}:
        return False
    params = model.get("supported_parameters") or []
    # basic chat controls; also excludes embedding-style endpoints
    return "max_tokens" in params and "temperature" in params


def _is_free(model):
    pricing = model.get("pricing") or {}
    return pricing.get("prompt") == "0" and pricing.get("completion") == "0"


def fetch_free_models(api_key, max_retries=3):
    """Fetch the currently available free models from OpenRouter (cached).

    Returns the raw model dicts whose prompt AND completion pricing are both "0".
    Raises after retries if the catalog cannot be fetched: without a model list
    there is nothing to generate, so this fails loudly rather than guessing.
    """
    global _free_models_cache
    if _free_models_cache is not None:
        return _free_models_cache

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(
                MODELS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            resp.raise_for_status()
            models = resp.json().get("data") or []
            _free_models_cache = [m for m in models if _is_free(m)]
            return _free_models_cache
        except Exception as e:  # network/HTTP/JSON
            last_error = e
            print(f"[fetch_free_models attempt {attempt}] failed: {e}")
            time.sleep(0.5 * attempt)
    raise RuntimeError(
        f"Could not fetch OpenRouter model catalog after {max_retries} attempts: {last_error}"
    )


def rank_free_models(models):
    """Filter to usable free chat models and return their ids best-first."""
    usable = [m for m in models if _is_usable_text_model(m)]
    usable.sort(key=_score_model, reverse=True)
    return [m["id"] for m in usable]


def select_models(api_key):
    """Ordered ids of the top free chat models to try for a generation."""
    ranked = rank_free_models(fetch_free_models(api_key))
    if not ranked:
        raise RuntimeError("No usable free text models available on OpenRouter")
    return ranked[:TOP_N_MODELS]


def _format_prompt(payload, subject, persona_key, openings):
    persona = PERSONAS[persona_key]
    hooks = payload["hooks"] or ["Pick the single most surprising fact below and make it the story"]
    return SOCIAL_PROMPT_TEMPLATE.format(
        subject=subject,
        persona_name=persona["name"],
        persona_brief=persona["brief"],
        persona_examples="\n".join(f"- {e}" for e in persona["examples"]),
        hooks="\n".join(f"- {h}" for h in hooks),
        facts="\n".join(f"- {k}: {v}" for k, v in payload["facts"].items()),
        recent=" / ".join(f'"{o}"' for o in openings) or "(none)",
        max_chars=SOCIAL_TEXT_MAX,
    ).strip()


def _finish_text(raw):
    text = sanitize_text(clean_social_response(raw))
    if "#" not in text and len(text) + 18 <= SOCIAL_TEXT_MAX:
        text = f"{text} #WoW #MythicPlus"
    return text


def generate_candidates(client, payload, subject, persona_key, openings=()):
    """Collect up to DRAFT_COUNT validated drafts, rotating over the top free models.

    Each draft starts at a different model so the drafts differ in style, and
    the whole search is bounded by MAX_DRAFT_CALLS model calls."""
    facts_text = json.dumps(payload, ensure_ascii=False)
    prompt = _format_prompt(payload, subject, persona_key, openings)
    models = select_models(client.api_key)

    drafts = []
    # drafts whose only flaw is a recycled opening: used only if nothing cleaner turns up
    soft_rejects = []
    calls = 0
    rate_limited = 0
    offset = 0
    while len(drafts) < DRAFT_COUNT and calls < MAX_DRAFT_CALLS:
        model = models[offset % len(models)]
        offset += 1
        calls += 1
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=DRAFT_TEMPERATURE,
            )
            text = _finish_text(resp.choices[0].message.content or "")
        except openai.RateLimitError as e:
            rate_limited += 1
            print(f"[draft {calls}] {model} rate-limited: {e}")
            continue
        except Exception as e:
            print(f"[draft {calls}] {model} failed: {e}")
            continue
        problems = validate_social_text(text, facts_text, openings)
        if any(text == d["text"] for d in drafts):
            problems.append("duplicate draft")
        if problems:
            print(f"[draft {calls}] {model} rejected: {'; '.join(problems)}")
            if problems == ["repeats a recent opening"]:
                soft_rejects.append({"text": text, "model": model})
            continue
        drafts.append({"text": text, "model": model})

    drafts = drafts or soft_rejects[:DRAFT_COUNT]
    if not drafts:
        if rate_limited == calls:
            raise RuntimeError("All models are rate-limited upstream")
        raise RuntimeError(
            f"Failed to generate a valid social post in {calls} model calls (validation errors or rate limits)."
        )
    return drafts


def _parse_scores(raw, count):
    match = re.search(r"\[.*\]", raw or "", re.S)
    if not match:
        return None
    try:
        rows = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    scores = {}
    for row in rows:
        try:
            idx = int(row["id"]) - 1
            parts = {k: float(row[k]) for k in ("hook", "humor", "clarity", "accuracy")}
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < count:
            scores[idx] = parts
    return scores or None


def _heuristic_pick(drafts):
    """Judge fallback: fewest numbers wins (least stat-list-like), then the shorter post."""
    return min(range(len(drafts)), key=lambda i: (len(_number_tokens(drafts[i]["text"])), len(drafts[i]["text"])))


def judge_candidates(client, drafts, payload, attempts=3):
    """Index of the best draft and its total judge score (None when the heuristic decided).

    Drafts the judge scores below 6 on accuracy are never picked. Any judge
    failure falls back to _heuristic_pick, so judging never blocks a post."""
    if len(drafts) == 1:
        return 0, None
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        facts=json.dumps(payload, ensure_ascii=False, indent=1),
        drafts="\n".join(f"{i + 1}. {d['text']}" for i, d in enumerate(drafts)),
    )
    models = select_models(client.api_key)
    for model in models[:attempts]:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
        except Exception as e:
            print(f"[judge] {model} failed: {e}")
            continue
        scores = _parse_scores(resp.choices[0].message.content, len(drafts))
        if not scores:
            print(f"[judge] {model} returned unparseable scores")
            continue
        eligible = {i: sc for i, sc in scores.items() if sc["accuracy"] >= 6}
        if not eligible:
            break
        best = max(eligible, key=lambda i: sum(eligible[i].values()))
        print(f"[judge] {model} scores: {scores}")
        return best, sum(eligible[best].values())
    return _heuristic_pick(drafts), None


def build_bundle(client, data, link, post_type, subject, donesocials=None, ctx=None):
    """Build the stored text bundle: static title + static blog + one social post.

    The social post is written by a model (best of several persona drafts) and
    has the link appended; the title and blog copy are generated from fixed
    templates (no model involved)."""
    payload = build_facts(post_type, data, ctx)
    persona = pick_persona(post_type, donesocials)
    openings = recent_openings(donesocials)
    drafts = generate_candidates(client, payload, subject, persona, openings)
    best, score = judge_candidates(client, drafts, payload)
    social = drafts[best]["text"]
    return {
        "title": build_static_title(post_type, data),
        "blog": build_static_blog(post_type, data),
        "social": f"{social} {link}".strip(),
        "persona": persona,
        "judge_score": score,
    }
