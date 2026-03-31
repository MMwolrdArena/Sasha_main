# Sasha Identity (TGWUI extension)

`Sasha Identity` is a deterministic identity compiler for text-generation-webui.

It provides deep trait controls, compiles a structured identity context, and writes the generated **name/context/greeting** into the standard Character tab fields.

## Install

Place this folder at:

- `extensions/sasha_identity/` (built-in repo extension path), or
- `user_data/extensions/sasha_identity/` (user override path).

Then launch TGWUI with:

```bash
python server.py --extensions sasha_identity
```

## Behavior

- Uses TGWUI's existing Character fields (`name2`, `context`, `greeting`) as output targets.
- Uses deterministic compiler logic (rule-based, no external generation dependency).
- Includes contradiction handling and derived-trait blending.
- Supports built-in presets plus JSON custom preset save/load.

## Manual customization

All major tuning is at the top of `script.py`:

- `PERSONALITY_SENTENCE_COUNT` (clamped to 1..10 for compact context length)
- `GENERAL_DEFAULTS`
- `NAME_STYLE_OPTIONS`, `GREETING_STYLE_OPTIONS`
- `TRAIT_GROUPS` (all trait sliders, ranges, defaults, descriptions)
- `PRESETS` (built-in identity profiles)

Edit those constants to add/remove traits and tune behavior.
