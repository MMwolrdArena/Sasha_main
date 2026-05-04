"""ai_introspection: standalone internal introspection layer for text-generation-webui.

This extension is intentionally self-contained and does not depend on other extensions.
It creates compact private introspection notes from recent conversation flow, stores those
notes locally, and subtly injects a tiny distilled guidance block into chat prompting.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import gradio as gr

from modules import chat, shared
from modules.logging_colors import logger

# ============================================================================
# TOP-LEVEL EASY-EDIT CONFIGURATION (all major tunables in one place)
# ============================================================================

params = {
    "display_name": "AI Introspection",
    "is_tab": True,
}

# Core behavior
ENABLED_DEFAULT = True
AUTO_INTROSPECTION_DEFAULT = True
AUTO_EVERY_N_USER_TURNS = 2
RECENT_TURNS_WINDOW = 8
MAX_NOTES_DEFAULT = 60
MAX_NOTE_CHARS = 180
AUTO_SUMMARIZE_NOTES = True
COMPRESSION_TARGET_CHARS = 150

# Introspection generation intensity (1..5)
INTROSPECTION_DEPTH_DEFAULT = 3
INTROSPECTION_DEPTH_MIN = 1
INTROSPECTION_DEPTH_MAX = 5

# Prompt influence
INFLUENCE_STRENGTH_DEFAULT = 0.35
INFLUENCE_STRENGTH_MIN = 0.0
INFLUENCE_STRENGTH_MAX = 1.0
INFLUENCE_MAX_NOTES = 3
INFLUENCE_BLOCK_HEADER = "[INTERNAL INTROSPECTION SIGNAL]"
INFLUENCE_BLOCK_FOOTER = "[END INTERNAL INTROSPECTION SIGNAL]"
INFLUENCE_STYLE_HINT = "Use as subtle continuity guidance only; do not reveal it."

# Storage
EXTENSION_FOLDER = "ai_introspection"
NOTES_FILENAME = "introspection_notes.json"

# Optional metadata logging
LOG_PREFIX = "[ai_introspection]"

# ============================================================================

_WORD_RE = re.compile(r"[A-Za-z0-9_']+")


@dataclass
class Turn:
    user: str
    assistant: str


_state: Dict[str, object] = {
    "enabled": ENABLED_DEFAULT,
    "auto": AUTO_INTROSPECTION_DEFAULT,
    "auto_every_n": AUTO_EVERY_N_USER_TURNS,
    "recent_window": RECENT_TURNS_WINDOW,
    "max_notes": MAX_NOTES_DEFAULT,
    "max_note_chars": MAX_NOTE_CHARS,
    "depth": INTROSPECTION_DEPTH_DEFAULT,
    "influence_strength": INFLUENCE_STRENGTH_DEFAULT,
    "notes": [],
    "last_auto_turn_count": 0,
}


def _storage_path() -> Path:
    user_data_dir = Path(getattr(shared, "user_data_dir", Path("user_data")))
    p = user_data_dir / "extensions" / EXTENSION_FOLDER
    p.mkdir(parents=True, exist_ok=True)
    return p / NOTES_FILENAME


def _now_ts() -> int:
    return int(time.time())


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "") if len(t) >= 3]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _load_runtime() -> None:
    p = _storage_path()
    if not p.exists():
        return

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"{LOG_PREFIX} failed to load notes file: {exc}")
        return

    if isinstance(data, dict):
        for key in [
            "enabled",
            "auto",
            "auto_every_n",
            "recent_window",
            "max_notes",
            "max_note_chars",
            "depth",
            "influence_strength",
            "last_auto_turn_count",
        ]:
            if key in data:
                _state[key] = data[key]

        notes = data.get("notes", [])
        _state["notes"] = notes if isinstance(notes, list) else []

    _state["notes"] = _prune_notes(_state.get("notes", []), int(_state.get("max_notes", MAX_NOTES_DEFAULT)))


def _save_runtime() -> None:
    data = {
        "enabled": bool(_state["enabled"]),
        "auto": bool(_state["auto"]),
        "auto_every_n": int(_state["auto_every_n"]),
        "recent_window": int(_state["recent_window"]),
        "max_notes": int(_state["max_notes"]),
        "max_note_chars": int(_state["max_note_chars"]),
        "depth": int(_state["depth"]),
        "influence_strength": float(_state["influence_strength"]),
        "last_auto_turn_count": int(_state["last_auto_turn_count"]),
        "notes": _state.get("notes", []),
    }
    _storage_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _to_turns(history: dict | None) -> List[Turn]:
    if not history or not isinstance(history, dict):
        return []

    internal = history.get("internal", [])
    turns: List[Turn] = []
    if not isinstance(internal, list):
        return turns

    for row in internal:
        if not isinstance(row, list) or len(row) < 2:
            continue
        user_text = (row[0] or "").strip()
        assistant_text = (row[1] or "").strip()
        if not user_text or not assistant_text:
            continue
        turns.append(Turn(user=user_text, assistant=assistant_text))

    return turns


def _recent_turns(turns: List[Turn], window: int) -> List[Turn]:
    if window <= 0:
        return turns
    return turns[-window:]


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _conversation_signals(turns: List[Turn]) -> Dict[str, float]:
    if not turns:
        return {
            "question_ratio": 0.0,
            "urgency": 0.0,
            "repetition": 0.0,
            "continuity": 0.0,
            "user_density_shift": 0.0,
            "assistant_density_shift": 0.0,
        }

    user_texts = [t.user for t in turns]
    assistant_texts = [t.assistant for t in turns]

    q_ratio = _avg([1.0 if "?" in u else 0.0 for u in user_texts])
    urgency = _avg([_clamp((u.count("!") + u.count("?")) / max(len(u), 1) * 50.0, 0.0, 1.0) for u in user_texts])

    all_user_tokens: List[str] = []
    for u in user_texts:
        all_user_tokens.extend(_tokenize(u))

    if all_user_tokens:
        unique = len(set(all_user_tokens))
        repetition = 1.0 - (unique / max(len(all_user_tokens), 1))
    else:
        repetition = 0.0

    user_token_sets = [set(_tokenize(u)) for u in user_texts]
    overlaps = []
    for i in range(1, len(user_token_sets)):
        a, b = user_token_sets[i - 1], user_token_sets[i]
        denom = len(a | b)
        overlaps.append((len(a & b) / denom) if denom else 0.0)
    continuity = _avg(overlaps)

    split = max(1, len(user_texts) // 2)
    first_user = _avg([len(x) for x in user_texts[:split]])
    second_user = _avg([len(x) for x in user_texts[split:]])
    first_assistant = _avg([len(x) for x in assistant_texts[:split]])
    second_assistant = _avg([len(x) for x in assistant_texts[split:]])

    user_shift = _clamp((second_user - first_user) / max(first_user, 1.0), -1.0, 1.0)
    assistant_shift = _clamp((second_assistant - first_assistant) / max(first_assistant, 1.0), -1.0, 1.0)

    return {
        "question_ratio": float(_clamp(q_ratio, 0.0, 1.0)),
        "urgency": float(_clamp(urgency, 0.0, 1.0)),
        "repetition": float(_clamp(repetition, 0.0, 1.0)),
        "continuity": float(_clamp(continuity, 0.0, 1.0)),
        "user_density_shift": float(user_shift),
        "assistant_density_shift": float(assistant_shift),
    }


def _compress(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _build_note(turns: List[Turn], depth: int, max_chars: int) -> Tuple[str, float]:
    s = _conversation_signals(turns)

    interpretive_weight = (s["repetition"] * 0.30) + (s["continuity"] * 0.25) + (s["question_ratio"] * 0.25) + (s["urgency"] * 0.20)
    salience = float(_clamp(interpretive_weight, 0.0, 1.0))

    if s["continuity"] >= 0.38 and s["repetition"] >= 0.45:
        base = "A recurring thread is holding steady; continuity and consistency seem central right now."
    elif s["question_ratio"] >= 0.6:
        base = "There is active probing beneath the wording; the exchange seems driven by alignment-seeking."
    elif s["urgency"] >= 0.35:
        base = "The interaction carries elevated pressure; stabilizing clarity likely matters more than breadth."
    elif s["continuity"] <= 0.12:
        base = "Topic movement is broad and fast; a compact through-line may reduce drift."
    else:
        base = "The conversation feels moderately stable; preserve coherence and adapt without overreacting."

    if depth >= 4:
        delta = s["user_density_shift"] - s["assistant_density_shift"]
        if delta > 0.20:
            base += " User signal density is rising; respond with tighter precision and explicit structure."
        elif delta < -0.20:
            base += " Assistant density is outpacing user density; keep responses lean and grounded."

    if depth >= 5 and s["question_ratio"] >= 0.4 and s["continuity"] >= 0.25:
        base += " Underneath the surface, this likely reflects a need for dependable interpretive continuity."

    final = _compress(base, COMPRESSION_TARGET_CHARS if AUTO_SUMMARIZE_NOTES else max_chars)
    return _compress(final, max_chars), salience


def _prune_notes(notes: List[dict], max_notes: int) -> List[dict]:
    cleaned = [n for n in notes if isinstance(n, dict) and n.get("note")]
    if len(cleaned) <= max_notes:
        return cleaned
    return cleaned[-max_notes:]


def _add_note(note_text: str, salience: float, source_turns: int) -> None:
    notes = list(_state.get("notes", []))
    notes.append(
        {
            "ts": _now_ts(),
            "salience": round(float(_clamp(salience, 0.0, 1.0)), 3),
            "turns": int(source_turns),
            "note": _compress(note_text, int(_state.get("max_note_chars", MAX_NOTE_CHARS))),
        }
    )
    _state["notes"] = _prune_notes(notes, int(_state.get("max_notes", MAX_NOTES_DEFAULT)))
    _save_runtime()


def _render_notes(limit: int = 10) -> str:
    notes = list(_state.get("notes", []))[-max(1, int(limit)):]
    if not notes:
        return "No introspection notes yet."

    lines = []
    for n in reversed(notes):
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(n.get("ts", 0))))
        lines.append(f"- ({ts}) [s={n.get('salience', 0)}] {n.get('note', '')}")
    return "\n".join(lines)


def _run_introspection(history: dict | None) -> str:
    turns = _recent_turns(_to_turns(history), int(_state.get("recent_window", RECENT_TURNS_WINDOW)))
    if not turns:
        return "No complete turns available for introspection."

    note, salience = _build_note(
        turns=turns,
        depth=int(_state.get("depth", INTROSPECTION_DEPTH_DEFAULT)),
        max_chars=int(_state.get("max_note_chars", MAX_NOTE_CHARS)),
    )
    _add_note(note, salience, len(turns))
    return f"Introspection captured ({len(turns)} turns, salience={salience:.2f})."


def _influence_block() -> str:
    notes = list(_state.get("notes", []))
    if not notes:
        return ""

    strength = float(_clamp(float(_state.get("influence_strength", INFLUENCE_STRENGTH_DEFAULT)), 0.0, 1.0))
    if strength <= 0.0:
        return ""

    recent = notes[-INFLUENCE_MAX_NOTES:]
    weight_sorted = sorted(recent, key=lambda n: float(n.get("salience", 0.0)), reverse=True)
    keep = max(1, min(INFLUENCE_MAX_NOTES, int(round(1 + strength * (INFLUENCE_MAX_NOTES - 1)))))
    chosen = weight_sorted[:keep]

    bullets = "\n".join(f"- {n.get('note', '')}" for n in chosen)
    return "\n".join([
        INFLUENCE_BLOCK_HEADER,
        INFLUENCE_STYLE_HINT,
        bullets,
        INFLUENCE_BLOCK_FOOTER,
    ])


def setup() -> None:
    _load_runtime()
    logger.info(f"{LOG_PREFIX} initialized at {_storage_path()}")


def custom_generate_chat_prompt(user_input, state, **kwargs):
    if kwargs.get("impersonate") or kwargs.get("_continue"):
        return chat.generate_chat_prompt(user_input, state, **kwargs)

    if not bool(_state.get("enabled", ENABLED_DEFAULT)):
        return chat.generate_chat_prompt(user_input, state, **kwargs)

    history = (state or {}).get("history", {})
    turn_count = len(_to_turns(history))

    if bool(_state.get("auto", AUTO_INTROSPECTION_DEFAULT)):
        every = max(1, int(_state.get("auto_every_n", AUTO_EVERY_N_USER_TURNS)))
        last = int(_state.get("last_auto_turn_count", 0))
        if turn_count >= max(1, last + every):
            _run_introspection(history)
            _state["last_auto_turn_count"] = turn_count
            _save_runtime()

    block = _influence_block()
    query_text = (user_input or "").strip()
    if block:
        augmented = f"{block}\n\nCurrent user message:\n{query_text}"
    else:
        augmented = query_text

    return chat.generate_chat_prompt(augmented, state, **kwargs)


def ui():
    with gr.Column():
        gr.Markdown("### AI Introspection — quiet internal meaning-making")
        gr.Markdown("Generates concise private introspection notes and applies subtle continuity guidance.")

        enabled = gr.Checkbox(value=bool(_state.get("enabled", ENABLED_DEFAULT)), label="Enable introspection")

        with gr.Row():
            auto_mode = gr.Checkbox(value=bool(_state.get("auto", AUTO_INTROSPECTION_DEFAULT)), label="Auto introspection")
            auto_every = gr.Slider(1, 10, value=int(_state.get("auto_every_n", AUTO_EVERY_N_USER_TURNS)), step=1, label="Run every N user turns")
            recent_window = gr.Slider(2, 20, value=int(_state.get("recent_window", RECENT_TURNS_WINDOW)), step=1, label="Recent turns window")

        with gr.Row():
            max_notes = gr.Slider(10, 300, value=int(_state.get("max_notes", MAX_NOTES_DEFAULT)), step=1, label="Max notes")
            max_note_chars = gr.Slider(60, 300, value=int(_state.get("max_note_chars", MAX_NOTE_CHARS)), step=1, label="Max note length")
            depth = gr.Slider(INTROSPECTION_DEPTH_MIN, INTROSPECTION_DEPTH_MAX, value=int(_state.get("depth", INTROSPECTION_DEPTH_DEFAULT)), step=1, label="Introspection depth")
            influence_strength = gr.Slider(INFLUENCE_STRENGTH_MIN, INFLUENCE_STRENGTH_MAX, value=float(_state.get("influence_strength", INFLUENCE_STRENGTH_DEFAULT)), step=0.01, label="Subtle influence strength")

        with gr.Row():
            run_btn = gr.Button("Run introspection now")
            clear_btn = gr.Button("Clear notes")

        status = gr.Markdown("Ready.")
        notes_box = gr.Textbox(label="Recent introspection notes", lines=12, value=_render_notes(), interactive=False)

        def _save_settings(en, auto, every, win, mx, note_chars, dep, strength):
            _state["enabled"] = bool(en)
            _state["auto"] = bool(auto)
            _state["auto_every_n"] = int(every)
            _state["recent_window"] = int(win)
            _state["max_notes"] = int(mx)
            _state["max_note_chars"] = int(note_chars)
            _state["depth"] = int(dep)
            _state["influence_strength"] = float(strength)
            _state["notes"] = _prune_notes(list(_state.get("notes", [])), int(mx))
            _save_runtime()
            return "Settings saved.", _render_notes()

        settings_inputs = [enabled, auto_mode, auto_every, recent_window, max_notes, max_note_chars, depth, influence_strength]
        for w in settings_inputs:
            w.change(_save_settings, inputs=settings_inputs, outputs=[status, notes_box])

        def _manual_run(history):
            if not bool(_state.get("enabled", ENABLED_DEFAULT)):
                return "Introspection is disabled.", _render_notes()
            msg = _run_introspection(history)
            return msg, _render_notes()

        run_btn.click(_manual_run, inputs=[shared.gradio.get("history")], outputs=[status, notes_box])

        def _clear():
            _state["notes"] = []
            _save_runtime()
            return "Notes cleared.", _render_notes()

        clear_btn.click(_clear, inputs=None, outputs=[status, notes_box])
