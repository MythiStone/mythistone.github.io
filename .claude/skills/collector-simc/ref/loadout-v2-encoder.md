---
name: loadout-v2-encoder
description: The talent loadout encoder in commonUtils is used only by the local seeder, and only SimulationCraft can prove its output valid. Use when synthesizing a talents= code, editing commonUtils.encode_loadout / is_choice_node, or debugging a simc talent init error on seeded data.
kind: external
files:
  - backend_scripts/commonUtils.py
  - backend_scripts/localDev/*
---

# Loadout encoder: seeder-only, validated by simc

`commonUtils.encode_loadout` is reachable only from `backend_scripts/localDev/`. Production never
synthesizes a talent code: it uses the real stored export strings. Do not fork a second encoder.

- **The browser decoder agreeing proves nothing.** It is tolerant, simc validates strictly. Run any
  encoder change through the simc image with a bare actor (`spec=`, `level=`, `talents=<code>`). No
  `Initialization error` is the gate.
- **simc ignores the 128-bit tree hash**, so an all-zero hash is valid.
- **Validate talents with a gearless actor.** Synthetic seeded gear fails init on armor class. A
  gearless melee actor then fails on its missing main-hand weapon, which is not a talent error.
- **`not a choice node but has index selection` on a seeded spec can be data skew:** the committed
  talent dump and the simc image disagree about a node. It heals when they realign. Do not "fix" it
  in `commonUtils.is_choice_node`.
- On Windows Git Bash, `docker run -v` needs `MSYS_NO_PATHCONV=1`, or the mount path is rewritten.

Related: [[collector-smoke-test]], [[tierlist-gear-modal]], [[analyzer-page]].
