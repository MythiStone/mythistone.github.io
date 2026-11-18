---
name: preview-fixed-port
description: The preview server's port is hard-coded in launch.json, so a preview moved to another port serves nothing. Use when a local preview opens on a port other than 8099 or shows a connection error.
kind: external
files:
  - .claude/launch.json
---

# The preview cannot move off its port

`.claude/launch.json` passes 8099 to the server in `runtimeArgs`. When 8099 is taken, the preview
tool assigns another port, but the server still tries to bind 8099 and nothing listens on the
assigned one. If a server already holds 8099, open `http://localhost:8099` directly. Otherwise free
the port before starting the preview.
