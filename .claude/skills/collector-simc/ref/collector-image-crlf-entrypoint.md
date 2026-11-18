---
name: collector-image-crlf-entrypoint
description: A collector image built from a Windows working copy gets a CRLF entrypoint.sh and exits 127 at start. Use when building or smoke-testing the collector image locally on Windows.
kind: external
files:
  - entrypoint.sh
  - Dockerfile
  - backend_scripts/localDev/collector_smoke.py
---

# CRLF entrypoint on Windows builds

The git index holds `entrypoint.sh` with LF, but a Windows checkout can write CRLF, and the Docker
build copies the working file. The container then exits 127 before any Python runs, which looks
like a broken image. For a local run, normalize the line endings in a temporary image or copy. CI
builds from a Linux checkout and is not affected.
