# ai_state (TGWUI extension)

`ai_state` is a standalone **text-generation-webui** extension that models Sasha's **present-moment internal state** and compiles it into a compact state line for prompt shaping.

It is intentionally separate from:
- identity (who she is)
- memory (what she remembers)

This extension is only about **how she is right now**.

## Features

- Standalone extension (no dependency on `ai_memory` or `ai_identity`).
- Top-of-file config section with major tunables.
- Baseline + current state model.
- State schema with per-variable metadata (key/label/default/min/max/step/help).
- Conflict normalization for contradictory combinations.
- Derived blends (e.g., composed attention, guardedness, active engagement).
- Compact compiler output (1–2 sentence state summary).
- Optional auto-recenter drift toward baseline.
- Presets (built-in + user saved).
- UI tab with grouped sliders, preview, apply/recenter/reset/randomize controls.
- Self-contained persistence under `user_data/extensions/ai_state/`.

## Install

1. Place this folder at:
   - `extensions/ai_state/` (built-in style), or
   - `user_data/extensions/ai_state/` (user override style)
2. Start webui with the extension enabled:

```bash
python server.py --extensions ai_state
```

## How it integrates with TGWUI

- Uses standard extension hooks only.
- Does **not** modify TGWUI core files.
- Uses `state_modifier(state)` to inject a compact current-state block into `context` (or `user_bio`, configurable).
- Uses `shared.gradio.get("interface_state")` when pressing **Apply** to sync values in the current UI session.

## Runtime files

Stored under:
- `user_data/extensions/ai_state/runtime_state.json`
- `user_data/extensions/ai_state/presets/*.json`

Safe to uninstall by removing the extension folder (and optional runtime files).

## Tuning

Edit `extensions/ai_state/script.py` at the top section:
- defaults and schema (`STATE_GROUPS`)
- drift settings (`DRIFT_RATE_PER_APPLY`)
- sentence count (`STATE_SENTENCE_COUNT_*`)
- auto options (`AUTO_APPLY_DEFAULT`, `LIVE_PREVIEW_DEFAULT`, `AUTO_RECENTER_DEFAULT`)
- context integration mode (`APPLY_TO`)

## Notes

- Output is intentionally compact and low-bloat.
- The extension does not rely on any non-standard TGWUI internals.
- If other extensions are installed, `ai_state` remains independent and optional.
