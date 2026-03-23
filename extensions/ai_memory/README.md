# ai_memory extension

Persistent long-term memory for chat mode using TGWUI extension hooks (no core file edits).

## What it does

- Initializes a SQLite DB at startup.
- Embeds each user message with `sentence-transformers`.
- Retrieves top relevant past turns by cosine similarity (+ light recency bonus).
- Injects memory snippets into each new chat prompt through `custom_generate_chat_prompt`.
- Saves each completed user/assistant turn via `output_modifier`.

## Install

1. Enable the extension:

   ```bash
   python server.py --extensions ai_memory
   ```

2. Install extension dependencies:

   ```bash
   pip install -r extensions/ai_memory/requirements.txt
   ```

## Notes

- Database path: `user_data/extensions/ai_memory/ai_memory.sqlite3`.
- If the embedding model is unavailable, the extension keeps running and still saves turns; semantic retrieval is skipped until embeddings can be generated.
