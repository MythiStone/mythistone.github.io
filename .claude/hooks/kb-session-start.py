#!/usr/bin/env python3
"""SessionStart hook: report `kb lint` problems so a stale or duplicated gotcha is fixed instead of
followed. Silent when lint is clean. Fails open on any error.
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

        report = kb.KB().lint()
        if report != "kb lint: clean":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "Knowledgebase lint problems. Fix these before relying on the gotchas they name:\n" + report,
            }}))
    except Exception:
        return


if __name__ == "__main__":
    main()
    sys.exit(0)
