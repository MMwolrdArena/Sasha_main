# ai_introspection (TGWUI extension)

`ai_introspection` is a standalone text-generation-webui extension that adds a quiet internal introspection layer.

It does **not** depend on `ai_memory`, `ai_identity`, or `ai_state`, and can run independently.

## What it does

- Builds compact introspection notes from recent conversation flow.
- Stores notes in its own local extension storage.
- Injects only a small internal continuity signal into chat prompt construction.
- Keeps introspection private and concise (not visible chain-of-thought output).

## Install

1. Copy this folder into your TGWUI extensions directory:
   - `extensions/ai_introspection`
2. Start TGWUI and enable the extension.
3. Open the **AI Introspection** tab to configure behavior.

## Configuration (top of script)

Major tunables are grouped at the top of `script.py`, including:

- auto run interval
- recent turn window
- max note count
- max note length
- automatic/manual behavior
- introspection depth
- influence strength
- storage filename/path constants

## UI controls

- Enable/disable introspection
- Auto-introspection toggle
- Run every N user turns
- Run introspection now button
- Clear notes button
- Max notes
- Max note length
- Introspection depth slider
- Subtle influence strength slider
- Recent introspection notes display

## Data storage

Notes are stored in:

`<user_data_dir>/extensions/ai_introspection/introspection_notes.json`

No other extension files or databases are used.

## TGWUI integration details

- Uses `custom_generate_chat_prompt(...)` to:
  - optionally run auto-introspection based on turn cadence
  - inject a compact introspection signal block into prompt generation
- Uses a Gradio tab (`params['is_tab'] = True`) for control and visibility.
- Uses only extension-local JSON persistence.
