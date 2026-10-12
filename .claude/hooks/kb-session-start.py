#!/usr/bin/env python3
"""SessionStart hook: keep the generated map files fresh and surface stale knowledge.

Rewrites .claude/kb/map/*.md (for tools without MCP) when a source file is newer than the map,
and reports `kb lint` problems so a stale gotcha is fixed instead of followed. Silent when the map
is current and lint is clean. Fails open on any error.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / ".claude" / "kb"))


def main() -> None:
    try:
        import kb

        index = kb.KB()
        marker = kb.MAP_DIR / "overview.md"
        if not marker.exists() or marker.stat().st_mtime < index._stamp:
            index.write_map()
        report = index.lint()
        if report != "kb lint: clean":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "Stale knowledge detected. Fix these gotchas before relying on them:\n" + report,
            }}))
    except Exception:
        return


if __name__ == "__main__":
    main()
    sys.exit(0)
