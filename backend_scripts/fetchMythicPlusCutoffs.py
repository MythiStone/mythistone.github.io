import json
import os
import re
from datetime import datetime, timezone

import requests

import commonUtils

# raider.io season-cutoffs is per-region. The site's run aggregates combine all
# regions, so we anchor the top-1% bar to the LOWEST per-region cutoff (the most
# inclusive), and resolve the required "all-timed" key level from it. The
# allTimedNN score map is region-independent, so any region's payload resolves
# the level.
REGIONS = ["us", "eu", "kr", "tw"]

RAIDERIO_API_KEY = os.getenv("RAIDERIO_API_KEY")

CUTOFFS_JSON = os.path.join("data", "static", "mythicPlusCutoffs.json")

CUTOFFS_URL = "https://raider.io/api/v1/mythic-plus/season-cutoffs"

# raider.io's score colour ramp for the season (commonUtils.score_color reads it).
SCORE_TIERS_JSON = os.path.join("data", "static", "scoreTiers.json")
SCORE_TIERS_URL = "https://raider.io/api/v1/mythic-plus/score-tiers"

# allTimed keys look like "allTimed17"; capture the numeric key level.
ALL_TIMED_RE = re.compile(r"^allTimed(\d+)$")


def fetch_region_cutoffs(season_slug, region):
    resp = requests.get(
        CUTOFFS_URL,
        {"season": season_slug, "region": region, "access_key": RAIDERIO_API_KEY},
    )
    resp.raise_for_status()
    return resp.json().get("cutoffs", {})


def parse_all_timed(cutoffs):
    """{key_level:int -> score:float} from the allTimedNN entries."""
    out = {}
    for key, value in cutoffs.items():
        match = ALL_TIMED_RE.match(key)
        if not match:
            continue
        score = value.get("score")
        if score is None:
            continue
        out[int(match.group(1))] = float(score)
    return out


def resolve_threshold_level(all_timed, top1pct_score):
    """Smallest all-timed key level whose score clears the top-1% cutoff."""
    qualifying = [lvl for lvl, score in all_timed.items() if score > top1pct_score]
    if not qualifying:
        raise RuntimeError(
            f"No all-timed key level clears the top-1% score {top1pct_score}; "
            f"max all-timed score is {max(all_timed.values()) if all_timed else 'n/a'}"
        )
    return min(qualifying)


def write_score_tiers(season_slug):
    """[{score, color}] highest first: a score takes the colour of the first tier it reaches."""
    resp = requests.get(
        SCORE_TIERS_URL, {"season": season_slug, "access_key": RAIDERIO_API_KEY}
    )
    resp.raise_for_status()
    tiers = [{"score": t["score"], "color": t["rgbHex"]} for t in resp.json()]
    if not tiers:
        raise RuntimeError(f"raider.io returned no score tiers for season {season_slug}")
    tiers.sort(key=lambda t: t["score"], reverse=True)
    with open(SCORE_TIERS_JSON, "w", encoding="utf-8") as f:
        json.dump(tiers, f, indent=2)
    print(f"Wrote {SCORE_TIERS_JSON}: {len(tiers)} tiers")


def main():
    season_slug = commonUtils.load_season_info()["slug"]
    write_score_tiers(season_slug)

    region_scores = {}
    all_timed = {}
    for region in REGIONS:
        cutoffs = fetch_region_cutoffs(season_slug, region)
        score = cutoffs.get("p990", {}).get("all", {}).get("quantileMinValue")
        if score is None:
            # A region may lag at season start (no top-1% bracket yet); skip it
            # rather than fail the whole fetch.
            print(f"WARNING: no p990 cutoff for region {region}, skipping")
            continue
        region_scores[region] = float(score)
        if not all_timed:
            all_timed = parse_all_timed(cutoffs)

    if not region_scores:
        raise RuntimeError(
            f"No region returned a top-1% cutoff for season {season_slug}"
        )
    if not all_timed:
        raise RuntimeError(
            f"No allTimed score map in season-cutoffs for {season_slug}"
        )

    top1pct_score = min(region_scores.values())
    threshold_level = resolve_threshold_level(all_timed, top1pct_score)

    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "season": season_slug,
        "regionScores": region_scores,
        "top1pct_score": top1pct_score,
        "allTimed": {str(lvl): all_timed[lvl] for lvl in sorted(all_timed)},
        "threshold_level": threshold_level,
    }

    os.makedirs(os.path.dirname(CUTOFFS_JSON), exist_ok=True)
    with open(CUTOFFS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(
        f"Wrote {CUTOFFS_JSON}: top1pct={top1pct_score} "
        f"threshold=+{threshold_level} regions={list(region_scores)}"
    )


if __name__ == "__main__":
    main()
