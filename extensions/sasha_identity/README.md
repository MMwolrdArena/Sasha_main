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