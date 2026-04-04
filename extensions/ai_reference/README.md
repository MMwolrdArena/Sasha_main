# ai_reference (TGWUI extension)

`ai_reference` is a standalone, file-based reference retrieval extension for text-generation-webui.

It indexes files from its own local reference folder and injects compact, relevant excerpts into chat prompts using direct lexical retrieval (keyword/token/phrase/path scoring). It does **not** use embeddings or vector databases.

## Key properties

- Standalone extension (no dependency on `ai_memory`, `ai_identity`, `ai_state`, or `ai_introspection`)
- Self-contained storage under `user_data/extensions/ai_reference/`
- Direct file parsing + chunk indexing + lightweight scoring retrieval
- Designed for large files by chunking and top-k excerpt selection
- Prompt injection is compact and clearly delimited

## Folder layout

Runtime folder:

- `user_data/extensions/ai_reference/reference/` → put your reference files here
- `user_data/extensions/ai_reference/index.json` → saved chunk index
- `user_data/extensions/ai_reference/config.json` → persisted extension settings

Code folder:

- `extensions/ai_reference/script.py`

## Supported file types

Built-in practical support includes:

- `.txt`, `.md`, `.log`
- `.py`, `.js`, `.ts`, `.cpp`, `.c`, `.h`, `.hpp`, `.java`, `.rs`, `.go`, `.sql`
- `.json`, `.csv`, `.html`, `.htm`, `.xml`, `.yaml`, `.yml`
- `.pdf` (optional parser: `pypdf`)
- `.docx` (optional parser: `python-docx`)

Unknown text-like files can still be read as UTF-8 text where possible.

## Install

1. Ensure this folder exists:
   - `extensions/ai_reference/`
2. (Optional but recommended) install parser dependencies for PDF and DOCX:
   - `pip install -r extensions/ai_reference/requirements.txt`
3. Start webui with extension enabled:
   - `python server.py --extensions ai_reference`

## Usage

1. Open the **AI Reference** tab.
2. Note the displayed reference folder path.
3. Copy files into that `reference/` folder.
4. Click **Reindex now** (or leave auto-index enabled).
5. Chat normally; relevant chunks will be injected automatically.
6. Use **Manual search preview** to test retrieval behavior.

## How integration works in TGWUI

- `setup()` initializes folders, loads/saves config, and loads index.
- `custom_generate_chat_prompt()` runs retrieval and injects compact reference context before generating the chat prompt.
- `ui()` provides controls for indexing and retrieval tuning.

No TGWUI core files or `modules/` files are modified.

## Major tunables (top-of-script)

Edit `DEFAULT_CONFIG` near the top of `script.py` for:

- reference folder name
- supported extensions
- chunk size / overlap
- max retrieved chunks
- max injected chars
- retrieval weights (keyword/phrase/path/recency/density)
- auto-index behavior
- deleted-file cleanup behavior

