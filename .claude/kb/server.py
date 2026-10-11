#!/usr/bin/env python3
"""mythi-kb MCP server: exposes kb.py over the MCP stdio transport.

Stdlib only (newline-delimited JSON-RPC 2.0, the subset MCP tools need), so it runs anywhere
python runs without a pip install. Registered in the repo-root .mcp.json. The index is built on
the first tool call and rebuilt automatically when a source file changes.
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb as kbmod  # noqa: E402

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
_kb = None


def _get_kb():
    global _kb
    if _kb is None:
        _kb = kbmod.KB()
    else:
        _kb.refresh()
    return _kb


def _tool_list():
    tools = []
    for name, (desc, params, _) in kbmod.TOOLS.items():
        tools.append({
            "name": name,
            "description": desc,
            "inputSchema": {
                "type": "object",
                "properties": {p: {"type": "string"} for p in params},
                "required": list(params),
            },
        })
    return tools


def _handle(msg):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mythi-kb", "version": "1.0.0"},
            "instructions": (
                "Code-derived map of the MythiStone repo plus curated gotchas. Use these tools before "
                "reading databaseConnector.py, database.sql, generateSpecPages.py or spec_page.html: "
                "they return the slice you need. Call kb_file on a path before editing it."
            ),
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _tool_list()}
    if method == "tools/call":
        name = params.get("name")
        if name not in kbmod.TOOLS:
            raise LookupError(f"unknown tool {name}")
        _, keys, fn = kbmod.TOOLS[name]
        args = params.get("arguments") or {}
        try:
            text = fn(_get_kb(), *[str(args.get(k, "")) for k in keys])
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:  # report tool failures to the model instead of killing the server
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"}], "isError": True}
    raise NotImplementedError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in msg:  # notifications (initialized, cancelled) need no reply
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": _handle(msg)}
        except NotImplementedError as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"method not found: {e}"}}
        except Exception as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
