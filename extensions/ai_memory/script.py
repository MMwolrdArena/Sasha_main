"""ai_memory extension: persistent long-term memory via SQLite + semantic retrieval."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np

from modules import chat, shared
from modules.logging_colors import logger

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - handled gracefully at runtime
    SentenceTransformer = None

params = {
    "display_name": "AI Memory",
    "is_tab": False,
}

_DB_FILENAME = "ai_memory.sqlite3"
_TABLE_NAME = "memories"
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_MAX_MEMORY_RESULTS = 4
_MAX_SNIPPET_CHARS = 350
_RECENCY_SCALE_DAYS = 30.0

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-']+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have",
    "i", "if", "in", "into", "is", "it", "its", "of", "on", "or", "s", "so", "that", "the",
    "their", "them", "there", "these", "they", "this", "to", "was", "we", "were", "will", "with",
    "you", "your", "yours", "my", "me", "our", "ours", "he", "she", "his", "her", "hers", "not",
}

_state = {
    "db_path": None,
    "embedder": None,
    "embedder_available": False,
    "last_user_text": "",
}
_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_db_path() -> Path:
    user_data_dir = getattr(shared, "user_data_dir", Path("user_data"))
    db_dir = Path(user_data_dir) / "extensions" / "ai_memory"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / _DB_FILENAME


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(str(_state["db_path"]))
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_db() -> None:
    with _connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                input TEXT NOT NULL,
                response TEXT NOT NULL,
                subject TEXT,
                keywords TEXT,
                embedding TEXT
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{_TABLE_NAME}_timestamp ON {_TABLE_NAME}(timestamp)"
        )


def _load_embedder() -> None:
    if SentenceTransformer is None:
        logger.warning('[ai_memory] sentence-transformers is not available. Memory retrieval will be disabled.')
        return

    try:
        _state["embedder"] = SentenceTransformer(_MODEL_NAME)
        _state["embedder_available"] = True
        logger.info(f"[ai_memory] Loaded embedding model: {_MODEL_NAME}")
    except Exception as exc:
        logger.warning(f"[ai_memory] Failed to load embedding model: {exc}")


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return vector
    return vector / norm


def _embed_text(text: str) -> np.ndarray | None:
    if not _state["embedder_available"]:
        return None

    cleaned = (text or "").strip()
    if not cleaned:
        return None

    try:
        vector = _state["embedder"].encode(cleaned, convert_to_numpy=True)
        return _normalize(vector.astype(np.float32))
    except Exception as exc:
        logger.warning(f"[ai_memory] Embedding generation failed: {exc}")
        return None


def _to_json_embedding(vector: np.ndarray | None) -> str:
    if vector is None:
        return ""
    return json.dumps(vector.tolist(), separators=(",", ":"))


def _from_json_embedding(raw: str) -> np.ndarray | None:
    if not raw:
        return None

    try:
        vec = np.array(json.loads(raw), dtype=np.float32)
        return _normalize(vec)
    except Exception:
        return None


def _tokenize(text: str) -> List[str]:
    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


def _extract_subject(text: str) -> str:
    tokens = _tokenize(text)
    if not tokens:
        return "general"

    most_common = Counter(tokens).most_common(6)
    return " ".join(word for word, _ in most_common[:3])


def _extract_keywords(user_text: str, assistant_text: str) -> str:
    merged = f"{user_text} {assistant_text}".strip()
    counts = Counter(_tokenize(merged))
    if not counts:
        return ""
    return ", ".join(word for word, _ in counts.most_common(8))


def _shorten(text: str, max_chars: int = _MAX_SNIPPET_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _recency_bonus(timestamp_iso: str) -> float:
    try:
        record_time = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0

    age_days = max((datetime.now(timezone.utc) - record_time).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + (age_days / _RECENCY_SCALE_DAYS))


def _retrieve_memories(query_text: str, top_k: int = _MAX_MEMORY_RESULTS) -> List[sqlite3.Row]:
    query_embedding = _embed_text(query_text)
    if query_embedding is None:
        return []

    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, timestamp, input, response, subject, keywords, embedding FROM {_TABLE_NAME}"
        ).fetchall()

    scored: List[Tuple[float, sqlite3.Row]] = []
    for row in rows:
        mem_embedding = _from_json_embedding(row["embedding"])
        if mem_embedding is None:
            continue

        semantic = float(np.dot(query_embedding, mem_embedding))
        score = semantic + (0.05 * _recency_bonus(row["timestamp"]))
        scored.append((score, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:top_k]]


def _format_memory_block(memories: Sequence[sqlite3.Row]) -> str:
    if not memories:
        return ""

    snippets = []
    for row in memories:
        timestamp = row["timestamp"].replace("T", " ").replace("+00:00", " UTC")
        snippets.append(
            "\n".join(
                [
                    "[Memory]",
                    f"Timestamp: {timestamp}",
                    f"User: {_shorten(row['input'])}",
                    f"Sasha: {_shorten(row['response'])}",
                    f"Keywords: {row['keywords'] or ''}",
                ]
            )
        )

    joined = "\n\n".join(snippets)
    return (
        "[AUTHORITATIVE PERSONAL MEMORY]\n"
        "These are relevant past conversations and should be treated as Sasha's long-term memory.\n\n"
        f"{joined}\n"
        "[END MEMORY]"
    )


def _save_turn(user_text: str, assistant_text: str) -> None:
    user_text = (user_text or "").strip()
    assistant_text = (assistant_text or "").strip()
    if not user_text or not assistant_text:
        return

    embedding = _embed_text(user_text)
    subject = _extract_subject(user_text)
    keywords = _extract_keywords(user_text, assistant_text)

    with _connect() as conn:
        conn.execute(
            f"""
            INSERT INTO {_TABLE_NAME} (timestamp, input, response, subject, keywords, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                user_text,
                assistant_text,
                subject,
                keywords,
                _to_json_embedding(embedding),
            ),
        )


def setup() -> None:
    _state["db_path"] = _resolve_db_path()
    _ensure_db()
    _load_embedder()
    logger.info(f"[ai_memory] Initialized DB at {_state['db_path']}")


def chat_input_modifier(text, visible_text, state):
    with _lock:
        _state["last_user_text"] = (text or visible_text or "").strip()
    return text, visible_text


def custom_generate_chat_prompt(user_input, state, **kwargs):
    # Skip injection for implicit prompt generations where there is no new user message.
    if kwargs.get("impersonate") or kwargs.get("_continue"):
        return chat.generate_chat_prompt(user_input, state, **kwargs)

    query_text = (user_input or "").strip()
    memories = _retrieve_memories(query_text)
    memory_block = _format_memory_block(memories)

    if memory_block:
        augmented_input = f"{memory_block}\n\nCurrent user message:\n{query_text}"
    else:
        augmented_input = query_text

    return chat.generate_chat_prompt(augmented_input, state, **kwargs)


def output_modifier(string, state, is_chat=False):
    if not is_chat:
        return string

    with _lock:
        user_text = _state.get("last_user_text", "")

    assistant_text = unescape(string or "")

    try:
        _save_turn(user_text, assistant_text)
    except Exception as exc:
        logger.warning(f"[ai_memory] Failed to save memory turn: {exc}")

    return string
