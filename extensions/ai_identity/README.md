# ai_identity (TGWUI extension)

Deterministic identity compiler extension for **text-generation-webui** that writes compact identity essence text into the existing Character tab fields.

## Install

Place this folder at:

- `extensions/ai_identity/`

Start TGWUI with:

- `--extensions ai_identity`

## Behavior

- Reads trait sliders from the extension UI.
- Resolves trait conflicts and derives internal blend axes.
- Compiles a compact identity summary for Character **Context**.
- Writes generated values into Character fields:
  - `name2`
  - `context`
  - `greeting`

## Top-level configuration

All major tuning controls are near the top of `script.py`, including:

- `PERSONALITY_SENTENCE_COUNT` (clamped 1..10)
- name/greeting mode defaults
- trait schema (`TRAIT_GROUPS`)
- presets (`PRESETS`)
- descriptor banks used by the deterministic compiler

## Notes

- The generated context is intentionally concise and identity-focused.
- The extension uses TGWUI Character pipeline fields and does not replace normal chat flow.
