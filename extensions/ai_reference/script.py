"""ai_reference: standalone local file-reference retrieval extension for text-generation-webui.

This extension indexes text from files in a controlled reference folder and injects
compact, relevant excerpts into chat prompts using direct text matching (no embeddings).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import gradio as gr

from modules import chat, shared
from modules.logging_colors import logger

try:  # Optional PDF parser
    import pypdf
except Exception:  # pragma: no cover
    pypdf = None

try:  # Optional DOCX parser
    from docx import Document
except Exception:  # pragma: no cover
    Document = None


# ============================================================================
# TOP-LEVEL EASY-EDIT CONFIGURATION
# ============================================================================

params = {
    "display_name": "AI Reference",
    "is_tab": True,
}

DEFAULT_CONFIG = {
    "enabled": True,
    "auto_index": True,
    "remove_missing_files": True,
    "reference_subdir": "reference",
    "index_filename": "index.json",
    "config_filename": "config.json",
    "max_file_size_mb": 64,
    "supported_extensions": [
        ".txt", ".md", ".pdf", ".docx", ".csv", ".json", ".html", ".htm", ".log",
        ".py", ".js", ".ts", ".cpp", ".c", ".h", ".hpp", ".java", ".rs", ".go", ".sql", ".yaml", ".yml", ".xml",
    ],
    "chunk_size_chars": 1200,
    "chunk_overlap_chars": 180,
    "max_chunks_per_file": 1200,
    "max_retrieved_chunks": 4,
    "max_injected_chars": 4200,
    "max_chunk_chars_for_injection": 900,
    "query_token_limit": 48,
    "min_token_len": 2,
    "keyword_weight": 1.0,
    "phrase_weight": 1.3,
    "path_weight": 0.35,
    "recency_weight": 0.12,
    "token_density_weight": 0.25,
    "manual_search_preview_chars": 2400,
    "injection_header": "[AI REFERENCE CONTEXT]",
    "injection_footer": "[END AI REFERENCE CONTEXT]",
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "if", "in", "into", "is",
    "it", "its", "of", "on", "or", "s", "so", "that", "the", "their", "them", "there", "these", "they", "this", "to",
    "was", "we", "were", "will", "with", "you", "your", "yours", "i", "me", "my", "our", "ours", "he", "she", "his", "her",
}

WORD_RE = re.compile(r"[A-Za-z0-9_\-]{2,}")


# ============================================================================
# INTERNAL STATE
# ============================================================================

_STATE = {
    "config": dict(DEFAULT_CONFIG),
    "base_dir": None,
    "reference_dir": None,
    "index_path": None,
    "config_path": None,
    "index": {
        "version": 1,
        "created_at": "",
        "updated_at": "",
        "files": {},
        "chunks": [],
        "inverted_index": {},
    },
    "last_retrieval": [],
    "last_retrieval_text": "",
    "last_error": "",
}
_LOCK = threading.RLock()


class _SimpleHTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: List[str] = []

    def handle_data(self, data):
        if data and data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_json_load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[ai_reference] Failed to read {path.name}: {exc}")
        return default


def _safe_json_dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _compute_fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path}:{stat.st_size}:{int(stat.st_mtime)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text: str, limit: Optional[int] = None) -> List[str]:
    min_len = int(_STATE["config"]["min_token_len"])
    tokens = [t.lower() for t in WORD_RE.findall(text or "") if len(t) >= min_len]
    tokens = [t for t in tokens if t not in STOPWORDS]
    if limit and limit > 0:
        return tokens[:limit]
    return tokens


def _resolve_dirs() -> None:
    base = Path(shared.user_data_dir) / "extensions" / "ai_reference"
    cfg = _STATE["config"]
    ref = base / str(cfg["reference_subdir"])
    index_path = base / str(cfg["index_filename"])
    config_path = base / str(cfg["config_filename"])
    base.mkdir(parents=True, exist_ok=True)
    ref.mkdir(parents=True, exist_ok=True)
    _STATE["base_dir"] = base
    _STATE["reference_dir"] = ref
    _STATE["index_path"] = index_path
    _STATE["config_path"] = config_path


def _load_config() -> None:
    base = Path(shared.user_data_dir) / "extensions" / "ai_reference"
    config_path = base / DEFAULT_CONFIG["config_filename"]
    loaded = _safe_json_load(config_path, {})
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(loaded, dict):
        cfg.update(loaded)
    _STATE["config"] = cfg


def _save_config() -> None:
    _safe_json_dump(_STATE["config_path"], _STATE["config"])


def _load_index() -> None:
    default_index = {
        "version": 1,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "files": {},
        "chunks": [],
        "inverted_index": {},
    }
    loaded = _safe_json_load(_STATE["index_path"], default_index)
    if not isinstance(loaded, dict):
        loaded = default_index
    loaded.setdefault("files", {})
    loaded.setdefault("chunks", [])
    loaded.setdefault("inverted_index", {})
    loaded.setdefault("created_at", _utc_now_iso())
    loaded["updated_at"] = loaded.get("updated_at") or _utc_now_iso()
    _STATE["index"] = loaded


def _save_index() -> None:
    _STATE["index"]["updated_at"] = _utc_now_iso()
    _safe_json_dump(_STATE["index_path"], _STATE["index"])


def _extract_text(path: Path) -> str:
    ext = path.suffix.lower()

    if ext in {".txt", ".md", ".log", ".py", ".js", ".ts", ".cpp", ".c", ".h", ".hpp", ".java", ".rs", ".go", ".sql", ".yaml", ".yml", ".xml"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if ext in {".html", ".htm"}:
        parser = _SimpleHTMLTextExtractor()
        parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
        return parser.get_text()

    if ext == ".json":
        raw = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return json.dumps(raw, ensure_ascii=False, indent=2)

    if ext == ".csv":
        rows: List[str] = []
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(" | ".join(cell.strip() for cell in row))
        return "\n".join(rows)

    if ext == ".pdf":
        if pypdf is None:
            raise RuntimeError("PDF support unavailable: install pypdf")
        reader = pypdf.PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages):
            extracted = page.extract_text() or ""
            if extracted.strip():
                pages.append(f"[Page {i + 1}]\n{extracted}")
        return "\n\n".join(pages)

    if ext == ".docx":
        if Document is None:
            raise RuntimeError("DOCX support unavailable: install python-docx")
        doc = Document(str(path))
        paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        return "\n".join(paras)

    return path.read_text(encoding="utf-8", errors="ignore")


def _chunk_text(text: str, chunk_size: int, overlap: int, max_chunks: int) -> List[str]:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []

    if chunk_size <= 0:
        chunk_size = 1200
    overlap = max(0, min(overlap, chunk_size // 2))
    step = max(1, chunk_size - overlap)

    chunks: List[str] = []
    start = 0
    while start < len(text) and len(chunks) < max_chunks:
        end = min(len(text), start + chunk_size)
        candidate = text[start:end]

        if end < len(text):
            newline_idx = candidate.rfind("\n")
            if newline_idx > chunk_size // 3:
                end = start + newline_idx
                candidate = text[start:end]

        cleaned = _normalize_space(candidate)
        if cleaned:
            chunks.append(cleaned)

        if end >= len(text):
            break
        start = start + step

    return chunks


def _list_reference_files() -> List[Path]:
    ref = _STATE["reference_dir"]
    exts = {e.lower() for e in _STATE["config"]["supported_extensions"]}
    max_bytes = int(_STATE["config"]["max_file_size_mb"]) * 1024 * 1024

    files: List[Path] = []
    for path in ref.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in exts:
            continue
        try:
            if path.stat().st_size > max_bytes:
                logger.warning(f"[ai_reference] Skipping large file over limit: {path}")
                continue
        except OSError:
            continue
        files.append(path)
    files.sort()
    return files


def _rebuild_inverted_index(chunks: Sequence[dict]) -> Dict[str, List[int]]:
    inv: Dict[str, List[int]] = {}
    for idx, chunk in enumerate(chunks):
        for tok in set(chunk.get("tokens", [])):
            inv.setdefault(tok, []).append(idx)
    return inv


def _index_files(force_full: bool = False) -> str:
    with _LOCK:
        cfg = _STATE["config"]
        index = _STATE["index"]
        files_meta: Dict[str, dict] = dict(index.get("files", {}))
        old_chunks: List[dict] = list(index.get("chunks", []))

        old_by_file: Dict[str, List[dict]] = {}
        for ch in old_chunks:
            old_by_file.setdefault(ch.get("file", ""), []).append(ch)

        found_files = _list_reference_files()
        found_rel = {str(p.relative_to(_STATE["reference_dir"])): p for p in found_files}

        if cfg["remove_missing_files"]:
            for missing in sorted(set(files_meta.keys()) - set(found_rel.keys())):
                files_meta.pop(missing, None)

        new_chunks: List[dict] = []
        indexed = 0
        skipped = 0
        errors = 0

        for rel_path, file_path in found_rel.items():
            fingerprint = _compute_fingerprint(file_path)
            prev = files_meta.get(rel_path)
            is_unchanged = (not force_full and prev and prev.get("fingerprint") == fingerprint)

            if is_unchanged:
                new_chunks.extend(old_by_file.get(rel_path, []))
                skipped += 1
                continue

            try:
                raw = _extract_text(file_path)
                chunks = _chunk_text(
                    raw,
                    int(cfg["chunk_size_chars"]),
                    int(cfg["chunk_overlap_chars"]),
                    int(cfg["max_chunks_per_file"]),
                )
                stamped = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc).isoformat()

                for i, chunk_text in enumerate(chunks):
                    tokens = _tokenize(chunk_text)
                    if not tokens:
                        continue
                    new_chunks.append(
                        {
                            "id": f"{rel_path}::{i}",
                            "file": rel_path,
                            "chunk_index": i,
                            "text": chunk_text,
                            "tokens": tokens,
                            "token_count": len(tokens),
                            "char_count": len(chunk_text),
                            "modified_at": stamped,
                        }
                    )

                files_meta[rel_path] = {
                    "fingerprint": fingerprint,
                    "size": file_path.stat().st_size,
                    "modified_at": stamped,
                    "chunk_count": len([c for c in new_chunks if c["file"] == rel_path]),
                }
                indexed += 1
            except Exception as exc:
                errors += 1
                _STATE["last_error"] = f"{rel_path}: {exc}"
                logger.warning(f"[ai_reference] Failed indexing {rel_path}: {exc}")

        inverted = _rebuild_inverted_index(new_chunks)

        index["files"] = files_meta
        index["chunks"] = new_chunks
        index["inverted_index"] = inverted
        _save_index()

        summary = (
            f"Indexed {indexed} file(s), reused {skipped} unchanged, errors {errors}. "
            f"Total files: {len(files_meta)} | Total chunks: {len(new_chunks)}"
        )
        return summary


def _recency_score(iso_value: str) -> float:
    try:
        ts = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    age_days = max((datetime.now(timezone.utc) - ts).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + age_days / 60.0)


def _score_chunk(query: str, query_tokens: Sequence[str], token_counts: Counter, chunk: dict) -> float:
    cfg = _STATE["config"]
    chunk_tokens = chunk.get("tokens", [])
    if not chunk_tokens:
        return 0.0

    chunk_counts = Counter(chunk_tokens)
    overlap_score = 0.0
    for tok in query_tokens:
        overlap_score += min(chunk_counts.get(tok, 0), token_counts.get(tok, 0))

    phrase_score = 0.0
    query_norm = _normalize_space(query).lower()
    chunk_text = chunk.get("text", "").lower()
    if query_norm and len(query_norm) >= 6 and query_norm in chunk_text:
        phrase_score += 1.0

    path_score = 0.0
    path_lower = chunk.get("file", "").lower()
    for tok in set(query_tokens):
        if tok in path_lower:
            path_score += 1.0

    density = overlap_score / max(1, chunk.get("token_count", 1))
    recency = _recency_score(chunk.get("modified_at", ""))

    return (
        float(cfg["keyword_weight"]) * overlap_score
        + float(cfg["phrase_weight"]) * phrase_score
        + float(cfg["path_weight"]) * path_score
        + float(cfg["token_density_weight"]) * density
        + float(cfg["recency_weight"]) * recency
    )


def _retrieve(query: str, top_k: Optional[int] = None) -> List[dict]:
    query = (query or "").strip()
    if not query:
        return []

    cfg = _STATE["config"]
    query_tokens = _tokenize(query, limit=int(cfg["query_token_limit"]))
    if not query_tokens:
        return []

    index = _STATE["index"]
    chunks = index.get("chunks", [])
    inv = index.get("inverted_index", {})

    candidate_ids = set()
    for tok in set(query_tokens):
        candidate_ids.update(inv.get(tok, []))

    if not candidate_ids:
        return []

    token_counts = Counter(query_tokens)
    scored: List[Tuple[float, dict]] = []
    for idx in candidate_ids:
        if idx < 0 or idx >= len(chunks):
            continue
        ch = chunks[idx]
        score = _score_chunk(query, query_tokens, token_counts, ch)
        if score > 0:
            scored.append((score, ch))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    limit = int(top_k if top_k is not None else cfg["max_retrieved_chunks"])
    return [{**chunk, "score": float(score)} for score, chunk in scored[:limit]]


def _format_injection(query: str, chunks: Sequence[dict]) -> str:
    if not chunks:
        return ""

    cfg = _STATE["config"]
    max_total = int(cfg["max_injected_chars"])
    max_each = int(cfg["max_chunk_chars_for_injection"])

    used = 0
    blocks: List[str] = []
    for i, ch in enumerate(chunks, start=1):
        text = ch.get("text", "")[:max_each]
        if not text:
            continue
        block = (
            f"[Ref {i} | file={ch.get('file')} | chunk={ch.get('chunk_index')} | score={ch.get('score', 0):.3f}]\n"
            f"{text}"
        )
        if used + len(block) > max_total and blocks:
            break
        blocks.append(block)
        used += len(block)

    if not blocks:
        return ""

    return (
        f"{cfg['injection_header']}\n"
        "Use the excerpts below as grounded reference when relevant. "
        "If references conflict, prefer the most specific excerpt.\n"
        f"Query: {query}\n\n"
        + "\n\n".join(blocks)
        + f"\n{cfg['injection_footer']}"
    )


def _update_retrieval_snapshot(query: str, chunks: Sequence[dict]) -> None:
    _STATE["last_retrieval"] = list(chunks)
    _STATE["last_retrieval_text"] = _format_injection(query, chunks)


def setup() -> None:
    with _LOCK:
        _load_config()
        _resolve_dirs()
        _save_config()
        _load_index()

        if _STATE["config"].get("auto_index", True):
            summary = _index_files(force_full=False)
            logger.info(f"[ai_reference] {summary}")

        logger.info(f"[ai_reference] Reference folder: {_STATE['reference_dir']}")


def custom_generate_chat_prompt(user_input, state, **kwargs):
    if kwargs.get("impersonate") or kwargs.get("_continue"):
        return chat.generate_chat_prompt(user_input, state, **kwargs)

    query = (user_input or "").strip()
    with _LOCK:
        if not _STATE["config"].get("enabled", True):
            return chat.generate_chat_prompt(user_input, state, **kwargs)

        if _STATE["config"].get("auto_index", True):
            _index_files(force_full=False)

        retrieved = _retrieve(query)
        _update_retrieval_snapshot(query, retrieved)
        injection = _format_injection(query, retrieved)

    augmented = f"{injection}\n\nCurrent user message:\n{query}" if injection else query
    return chat.generate_chat_prompt(augmented, state, **kwargs)


def _indexed_files_table() -> List[List[str]]:
    rows: List[List[str]] = []
    files = _STATE["index"].get("files", {})
    for file_name in sorted(files.keys()):
        meta = files[file_name]
        rows.append([
            file_name,
            str(meta.get("chunk_count", 0)),
            str(meta.get("size", 0)),
            str(meta.get("modified_at", "")),
        ])
    return rows


def _status_text(prefix: str = "") -> str:
    idx = _STATE["index"]
    files_n = len(idx.get("files", {}))
    chunks_n = len(idx.get("chunks", []))
    tail = f"files={files_n}, chunks={chunks_n}, updated={idx.get('updated_at', '')}"
    return f"{prefix} {tail}".strip()


def _apply_ui_settings(
    enabled,
    auto_index,
    remove_missing,
    max_chunks,
    max_chars,
    chunk_size,
    chunk_overlap,
    keyword_weight,
    phrase_weight,
    path_weight,
    recency_weight,
):
    with _LOCK:
        cfg = _STATE["config"]
        cfg["enabled"] = bool(enabled)
        cfg["auto_index"] = bool(auto_index)
        cfg["remove_missing_files"] = bool(remove_missing)
        cfg["max_retrieved_chunks"] = int(max_chunks)
        cfg["max_injected_chars"] = int(max_chars)
        cfg["chunk_size_chars"] = int(chunk_size)
        cfg["chunk_overlap_chars"] = int(chunk_overlap)
        cfg["keyword_weight"] = float(keyword_weight)
        cfg["phrase_weight"] = float(phrase_weight)
        cfg["path_weight"] = float(path_weight)
        cfg["recency_weight"] = float(recency_weight)
        _save_config()
        return _status_text("Saved settings."), _indexed_files_table()


def _ui_reindex():
    with _LOCK:
        msg = _index_files(force_full=True)
        return _status_text(msg), _indexed_files_table()


def _ui_clear_index():
    with _LOCK:
        _STATE["index"] = {
            "version": 1,
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "files": {},
            "chunks": [],
            "inverted_index": {},
        }
        _save_index()
        return _status_text("Cleared index."), []


def _ui_test_search(query: str, top_k: int):
    with _LOCK:
        chunks = _retrieve(query, top_k=top_k)
        _update_retrieval_snapshot(query, chunks)
        preview = _STATE["last_retrieval_text"]
        if len(preview) > int(_STATE["config"]["manual_search_preview_chars"]):
            preview = preview[: int(_STATE["config"]["manual_search_preview_chars"])] + "..."

        rows = [[
            c.get("file", ""),
            str(c.get("chunk_index", "")),
            f"{c.get('score', 0.0):.3f}",
            str(c.get("char_count", 0)),
        ] for c in chunks]
        return preview or "No matching reference chunks.", rows


def ui():
    with gr.Column():
        gr.Markdown("## AI Reference")
        status = gr.Textbox(value=_status_text("Ready."), label="Status", interactive=False)
        ref_path = gr.Textbox(value=str(_STATE["reference_dir"]), label="Reference folder", interactive=False)

        with gr.Row():
            enabled = gr.Checkbox(value=bool(_STATE["config"]["enabled"]), label="Enable retrieval")
            auto_index = gr.Checkbox(value=bool(_STATE["config"]["auto_index"]), label="Auto-index on generation")
            remove_missing = gr.Checkbox(value=bool(_STATE["config"]["remove_missing_files"]), label="Remove deleted files from index")

        with gr.Row():
            max_chunks = gr.Slider(1, 12, step=1, value=int(_STATE["config"]["max_retrieved_chunks"]), label="Max retrieved chunks")
            max_chars = gr.Slider(400, 12000, step=100, value=int(_STATE["config"]["max_injected_chars"]), label="Max injected chars")

        with gr.Row():
            chunk_size = gr.Slider(400, 6000, step=50, value=int(_STATE["config"]["chunk_size_chars"]), label="Chunk size chars")
            chunk_overlap = gr.Slider(0, 1200, step=10, value=int(_STATE["config"]["chunk_overlap_chars"]), label="Chunk overlap chars")

        with gr.Row():
            keyword_weight = gr.Slider(0.0, 3.0, step=0.05, value=float(_STATE["config"]["keyword_weight"]), label="Keyword weight")
            phrase_weight = gr.Slider(0.0, 3.0, step=0.05, value=float(_STATE["config"]["phrase_weight"]), label="Phrase weight")
            path_weight = gr.Slider(0.0, 2.0, step=0.05, value=float(_STATE["config"]["path_weight"]), label="Filename/path weight")
            recency_weight = gr.Slider(0.0, 1.0, step=0.01, value=float(_STATE["config"]["recency_weight"]), label="Recency weight")

        with gr.Row():
            save_btn = gr.Button("Save settings")
            reindex_btn = gr.Button("Reindex now")
            clear_btn = gr.Button("Clear index")

        indexed_files = gr.Dataframe(
            headers=["File", "Chunks", "Bytes", "Modified"],
            value=_indexed_files_table(),
            label="Indexed files",
            interactive=False,
            wrap=True,
        )

        gr.Markdown("### Manual search preview")
        with gr.Row():
            test_query = gr.Textbox(label="Search query", lines=2)
            test_topk = gr.Slider(1, 12, step=1, value=int(_STATE["config"]["max_retrieved_chunks"]), label="Preview top-k")
        test_btn = gr.Button("Run search test")
        preview = gr.Textbox(label="Retrieved context preview", lines=14, interactive=False)
        preview_table = gr.Dataframe(
            headers=["File", "Chunk", "Score", "Chars"],
            value=[],
            interactive=False,
            label="Retrieved chunks",
            wrap=True,
        )

        save_btn.click(
            _apply_ui_settings,
            inputs=[
                enabled,
                auto_index,
                remove_missing,
                max_chunks,
                max_chars,
                chunk_size,
                chunk_overlap,
                keyword_weight,
                phrase_weight,
                path_weight,
                recency_weight,
            ],
            outputs=[status, indexed_files],
        )

        reindex_btn.click(_ui_reindex, inputs=[], outputs=[status, indexed_files])
        clear_btn.click(_ui_clear_index, inputs=[], outputs=[status, indexed_files])
        test_btn.click(_ui_test_search, inputs=[test_query, test_topk], outputs=[preview, preview_table])

    return [status, ref_path]
