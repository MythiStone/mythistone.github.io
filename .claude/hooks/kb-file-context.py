#!/usr/bin/env python3
"""PostToolUse hook: surface the gotchas for a file the first time it is edited in a session.

Replaces blanket "remember to test-render / update skills" nudges on every edit. It speaks only
when it has something specific: the gotcha ids whose `files:` globs match the edited path (once
per file per session), and the domain's verification step plus the knowledge-update check (once
per domain per session). Reads only gotcha frontmatter, never the full code map, so it stays fast.
Fails open (exit 0, no output) on any error so it can never wedge tool use.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / ".claude" / "kb"))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            return
        file_path = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_input") or {}).get("notebook_path") or ""
        if not file_path:
            return
        import kb  # noqa: E402  (imported late so a broken kb.py cannot break unrelated edits)

        try:
            rel = str(Path(file_path).resolve().relative_to(ROOT.resolve())).replace("\\", "/")
        except ValueError:
            return
        if rel.startswith(".claude/kb/map/"):
            return

        state_path = Path(tempfile.gettempdir()) / f"mythi-kb-hook-{payload.get('session_id', 'nosession')}.json"
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            state = {"files": [], "domains": []}

        notes = []
        if rel not in state["files"]:
            state["files"].append(rel)
            gotchas = []
            for ref in sorted((ROOT / ".claude" / "skills").glob("*/ref/*.md")) + sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md")):
                meta, _ = kb._frontmatter(ref.read_text(encoding="utf-8", errors="ignore"))
                globs = meta.get("files") or []
                if isinstance(globs, str):
                    globs = [globs]
                if any(kb._match(rel, g) for g in globs):
                    gotchas.append(f"{meta.get('name', ref.stem)} ({str(ref.relative_to(ROOT)).replace(os.sep, '/')})")
            if gotchas:
                notes.append(f"Gotchas for {rel}: " + "; ".join(gotchas) + ". Read any you have not read this session before changing behavior there.")

        dom = kb.domain_of(rel)
        if dom and dom not in state["domains"]:
            state["domains"].append(dom)
            notes.append(
                f"Domain {dom}: before finishing, verify with: {kb.DOMAINS[dom]['verify']}. "
                "If the change alters behavior a gotcha describes, update that gotcha (ask the user first, "
                "per the knowledgebase-authoring skill) and run `python .claude/kb/kb.py lint`."
            )

        state_path.write_text(json.dumps(state))
        if notes:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": " ".join(notes)}}))
    except Exception:
        return


if __name__ == "__main__":
    main()
    sys.exit(0)
