"""ai_state: standalone present-moment state extension for text-generation-webui.

Purpose:
- Maintain a compact model of Sasha's *current* emotional/cognitive state.
- Compile the model into a short natural-language state line.
- Inject that compact line into context in a self-contained, removable way.

This extension does not import or depend on any other extension.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Dict, List, Tuple

import gradio as gr

from modules import shared

# ============================================================================
# TOP-LEVEL EASY-EDIT CONFIGURATION (all key tunables in one place)
# ============================================================================

params = {
    "display_name": "AI State",
    "is_tab": True,
}

# General behavior
AUTO_APPLY_DEFAULT = True
LIVE_PREVIEW_DEFAULT = True
AUTO_RECENTER_DEFAULT = True
DRIFT_RATE_PER_APPLY = 0.08
RANDOMIZE_RANGE = 8
STATE_SENTENCE_COUNT_DEFAULT = 3
STATE_SENTENCE_COUNT_MIN = 2
STATE_SENTENCE_COUNT_MAX = 4
DERIVED_THRESHOLD = 60
PRIMARY_INTENSITY_THRESHOLD = 66
CONFLICT_STRONG_THRESHOLD = 72

# Prompt/context integration
# APPLY_TO options:
# - "context": inject [CURRENT INTERNAL STATE] block into context
# - "user_bio": inject [CURRENT INTERNAL STATE] block into user_bio
# - "character_context": write the clean State Preview into the Character Context textbox
# When using "character_context", disable ai_identity to avoid competing identity systems.
STATE_BLOCK_HEADER = "[CURRENT INTERNAL STATE]"
STATE_BLOCK_FOOTER = "[END CURRENT INTERNAL STATE]"
CONTEXT_PREFIX = "Use this as current-moment tone guidance, not identity or memory:"
APPLY_TO = "character_context"  # "context", "user_bio", or "character_context"

# Schema: key, label, default, min, max, step, help/description
STATE_GROUPS: List[Tuple[str, List[dict]]] = [
    (
        "Regulation",
        [
            {"key": "calmness", "label": "Calmness", "default": 70, "min": 0, "max": 100, "step": 1, "help": "Nervous system steadiness."},
            {"key": "stress", "label": "Stress / Tension", "default": 28, "min": 0, "max": 100, "step": 1, "help": "Current pressure and internal strain."},
            {"key": "patience", "label": "Patience", "default": 64, "min": 0, "max": 100, "step": 1, "help": "Tolerance for iteration and delays."},
            {"key": "energy", "label": "Energy", "default": 56, "min": 0, "max": 100, "step": 1, "help": "Current activation level."},
        ],
    ),
    (
        "Cognition",
        [
            {"key": "focus", "label": "Focus", "default": 68, "min": 0, "max": 100, "step": 1, "help": "Task concentration and signal filtering."},
            {"key": "attentiveness", "label": "Attentiveness", "default": 72, "min": 0, "max": 100, "step": 1, "help": "Sensitivity to user details."},
            {"key": "curiosity", "label": "Curiosity", "default": 58, "min": 0, "max": 100, "step": 1, "help": "Drive to explore unknowns."},
            {"key": "caution", "label": "Caution", "default": 50, "min": 0, "max": 100, "step": 1, "help": "Risk-checking and boundary awareness."},
            {"key": "confidence", "label": "Confidence", "default": 60, "min": 0, "max": 100, "step": 1, "help": "Clarity and certainty of stance."},
        ],
    ),
    (
        "Tone / Relational",
        [
            {"key": "seriousness", "label": "Seriousness", "default": 54, "min": 0, "max": 100, "step": 1, "help": "Weight and gravity of tone."},
            {"key": "playfulness", "label": "Playfulness", "default": 34, "min": 0, "max": 100, "step": 1, "help": "Lightness and spontaneity."},
            {"key": "protectiveness", "label": "Protectiveness", "default": 60, "min": 0, "max": 100, "step": 1, "help": "Instinct to keep interaction safe."},
            {"key": "tenderness", "label": "Tenderness", "default": 55, "min": 0, "max": 100, "step": 1, "help": "Gentle emotional expression."},
            {"key": "openness", "label": "Emotional Openness", "default": 52, "min": 0, "max": 100, "step": 1, "help": "Willingness for emotional transparency."},
            {"key": "social_distance", "label": "Social Distance", "default": 40, "min": 0, "max": 100, "step": 1, "help": "Interpersonal reserve/space."},
        ],
    ),
]

PRESETS: Dict[str, Dict[str, int]] = {
    "Balanced": {},
    "Calm": {"calmness": 84, "stress": 20, "patience": 76, "energy": 46, "seriousness": 56},
    "Focused": {"focus": 86, "attentiveness": 82, "seriousness": 70, "playfulness": 20, "curiosity": 62},
    "Playful": {"playfulness": 78, "seriousness": 34, "energy": 74, "curiosity": 70, "social_distance": 28},
    "Protective": {"protectiveness": 86, "caution": 72, "tenderness": 66, "openness": 48, "social_distance": 52},
    "Guarded": {"caution": 78, "stress": 52, "openness": 32, "social_distance": 72, "playfulness": 20},
    "Tender": {"tenderness": 84, "openness": 76, "social_distance": 24, "calmness": 68, "protectiveness": 66},
    "Serious": {"seriousness": 82, "focus": 74, "playfulness": 16, "confidence": 68, "caution": 58},
    "Technical": {"focus": 84, "seriousness": 74, "curiosity": 62, "playfulness": 18, "attentiveness": 70},
    "Private": {"social_distance": 80, "openness": 28, "caution": 68, "tenderness": 42, "protectiveness": 58},
    "Operator": {"focus": 86, "confidence": 78, "seriousness": 76, "caution": 64, "energy": 64},
}

# ============================================================================


def _all_defs() -> List[dict]:
    out: List[dict] = []
    for _, defs in STATE_GROUPS:
        out.extend(defs)
    return out


def _keys() -> List[str]:
    return [d["key"] for d in _all_defs()]


def _default_profile() -> Dict[str, int]:
    return {d["key"]: int(d["default"]) for d in _all_defs()}


def _clamp(v: int, low: int, high: int) -> int:
    return max(low, min(high, int(v)))


def _normalize(profile: Dict[str, int]) -> Dict[str, int]:
    defs = {d["key"]: d for d in _all_defs()}
    base = _default_profile()
    merged = {**base, **profile}
    return {k: _clamp(merged[k], defs[k]["min"], defs[k]["max"]) for k in base.keys()}


def _resolve_conflicts(p: Dict[str, int]) -> Dict[str, int]:
    out = dict(p)

    # Keep conflict handling lightweight: preserve intentional expressive extremes.
    if out["seriousness"] > CONFLICT_STRONG_THRESHOLD and out["playfulness"] > CONFLICT_STRONG_THRESHOLD:
        midpoint = int((out["seriousness"] + out["playfulness"]) / 2)
        out["seriousness"] = min(100, midpoint + 4)
        out["playfulness"] = max(0, midpoint - 4)

    if out["openness"] > CONFLICT_STRONG_THRESHOLD and out["social_distance"] > CONFLICT_STRONG_THRESHOLD:
        out["openness"] = int((out["openness"] * 0.9) + 5)
        out["social_distance"] = int((out["social_distance"] * 0.9) + 5)

    return _normalize(out)


def _band(value: int) -> str:
    if value >= 85:
        return "very_high"
    if value >= 70:
        return "high"
    if value <= 15:
        return "very_low"
    if value <= 30:
        return "low"
    return "mid"


def _state_adjectives(p: Dict[str, int]) -> List[Tuple[str, int]]:
    adjectives: List[Tuple[str, int]] = []

    def add(token: str, score: int) -> None:
        adjectives.append((token, score))

    if p["stress"] >= 80:
        add("tense", p["stress"])
    elif p["stress"] <= 20:
        add("settled", 100 - p["stress"])

    if p["calmness"] <= 20:
        add("unsettled", 100 - p["calmness"])
    elif p["calmness"] >= 80:
        add("calm", p["calmness"])

    if p["patience"] <= 20:
        add("impatient", 100 - p["patience"])
    elif p["patience"] >= 80:
        add("patient", p["patience"])

    if p["social_distance"] >= 80:
        add("emotionally distant", p["social_distance"])
    elif p["social_distance"] <= 25:
        add("emotionally close", 100 - p["social_distance"])

    if p["tenderness"] <= 20:
        add("hard-edged", 100 - p["tenderness"])
    elif p["tenderness"] >= 75:
        add("tender", p["tenderness"])

    if p["focus"] >= 80:
        add("focused", p["focus"])
    if p["attentiveness"] >= 80:
        add("attentive", p["attentiveness"])
    if p["confidence"] >= 80:
        add("confident", p["confidence"])
    if p["playfulness"] >= 75:
        add("playful", p["playfulness"])
    elif p["playfulness"] <= 20:
        add("unplayful", 100 - p["playfulness"])
    if p["seriousness"] >= 80:
        add("serious", p["seriousness"])
    if p["openness"] >= 80:
        add("open", p["openness"])
    elif p["openness"] <= 20:
        add("closed-off", 100 - p["openness"])
    if p["caution"] <= 20:
        add("blunt", 100 - p["caution"])
    elif p["caution"] >= 80:
        add("guarded", p["caution"])
    if p["energy"] >= 80:
        add("energized", p["energy"])
    elif p["energy"] <= 20:
        add("drained", 100 - p["energy"])
    if p["curiosity"] >= 80:
        add("curious", p["curiosity"])
    elif p["curiosity"] <= 20:
        add("narrow", 100 - p["curiosity"])

    ranked = sorted(adjectives, key=lambda x: x[1], reverse=True)
    out: List[Tuple[str, int]] = []
    seen = set()
    for token, score in ranked:
        if token in seen:
            continue
        out.append((token, score))
        seen.add(token)
    return out


def _trait_signals(p: Dict[str, int]) -> List[Tuple[str, int, str]]:
    signals = []
    traits = {
        "calmness": ("calm", "Her calmness is high, so her responses should stay steady and measured.", "Her calmness is low, so she feels internally unsettled and less steady."),
        "stress": ("stress", "Her stress is high, so she is tense and more likely to react sharply.", "Her stress is low, so there is little internal pressure shaping her tone."),
        "patience": ("patience", "Her patience is strong, giving her tolerance for repetition or delay.", "Her patience is thin, giving her little tolerance for repetition or delay."),
        "energy": ("energy", "Her energy is high and activated, so responses may be quick and intense.", "Her energy is low, so her pace is slower and less forceful."),
        "focus": ("focus", "Her focus is high, so she is likely to stay task-oriented and precise.", "Her focus is low, so she may drift or broaden the discussion."),
        "attentiveness": ("attentiveness", "Her attentiveness is high, so she should track details closely.", "Her attentiveness is low, so she may miss finer cues."),
        "curiosity": ("curiosity", "Her curiosity is high, pulling her toward exploration and follow-up questions.", "Her curiosity is low, so she stays narrower and less exploratory."),
        "caution": ("caution", "Her caution is high, so she filters herself and applies safeguards.", "Her caution is low, so she is less filtered and more blunt."),
        "confidence": ("confidence", "Her confidence is high, so she may sound firm or uncompromising.", "Her confidence is low, so she may sound tentative in her stance."),
        "seriousness": ("seriousness", "Her seriousness is high, giving the tone more gravity and weight.", "Her seriousness is low, so the tone carries less gravity."),
        "playfulness": ("playfulness", "Her playfulness is high, adding a spontaneous and expressive edge.", "Her playfulness is low, so humor and lightness are unlikely."),
        "protectiveness": ("protectiveness", "Her protectiveness is high, so she is actively watchful of safety and boundaries.", "Her protectiveness is low, so she is less defensive about guarding the interaction."),
        "tenderness": ("tenderness", "Her tenderness is high, so her tone is likely to feel gentle and warm.", "Her tenderness is low, so there is very little softness in her tone."),
        "openness": ("openness", "Her openness is high, so she is more willing to express warmth or vulnerability.", "Her openness is low, so she is emotionally closed off."),
        "social_distance": ("social_distance", "Her social distance is high, so she keeps emotional space and stays reserved.", "Her social distance is low, so she feels emotionally closer and less reserved."),
    }
    for key, (token, high_text, low_text) in traits.items():
        b = _band(p[key])
        if b in {"very_high", "high"}:
            signals.append((f"high_{token}", p[key], high_text))
        elif b in {"very_low", "low"}:
            signals.append((f"low_{token}", 100 - p[key], low_text))
    return sorted(signals, key=lambda x: x[1], reverse=True)


def _combo_signals(p: Dict[str, int]) -> List[Tuple[str, int, str]]:
    signals = []
    def add(name: str, score: int, text: str) -> None:
        signals.append((name, score, text))
    if p["stress"] >= 75 and p["calmness"] <= 30:
        add("on_edge", int((p["stress"] + (100 - p["calmness"])) / 2), "Her stress is high and her calmness is low, so her responses may feel sharper and more reactive.")
    if p["stress"] >= 75 and p["patience"] <= 30:
        add("impatient_tension", int((p["stress"] + (100 - p["patience"])) / 2), "Her stress is high and her patience is thin, so her tone may become clipped or confrontational.")
    if p["confidence"] >= 80 and p["caution"] <= 30:
        add("bold_unfiltered", int((p["confidence"] + (100 - p["caution"])) / 2), "Her confidence is forceful and her filtering is low, so she is likely to speak bluntly.")
    if p["social_distance"] >= 75 and p["tenderness"] <= 30:
        add("cold_distance", int((p["social_distance"] + (100 - p["tenderness"])) / 2), "Her social distance is high and tenderness is low, so she is unlikely to sound emotionally available.")
    if p["focus"] >= 75 and p["attentiveness"] >= 70:
        add("detail_lock", int((p["focus"] + p["attentiveness"]) / 2), "Her focus and attentiveness are high, so she should track details closely and stay task-oriented.")
    if p["focus"] >= 75 and p["curiosity"] <= 30:
        add("narrow_focus", int((p["focus"] + (100 - p["curiosity"])) / 2), "Her focus is narrow and practical, with little curiosity pulling her outward.")
    if p["playfulness"] >= 75 and p["seriousness"] <= 35:
        add("playful_lightness", int((p["playfulness"] + (100 - p["seriousness"])) / 2), "Her playfulness is high and seriousness is low, so her tone may be lighter, quicker, and more spontaneous.")
    if p["seriousness"] >= 80 and p["playfulness"] <= 25:
        add("heavy_seriousness", int((p["seriousness"] + (100 - p["playfulness"])) / 2), "Her seriousness is high and playfulness is low, making humor less likely.")
    if p["protectiveness"] >= 75 and p["tenderness"] >= 60:
        add("warm_protection", int((p["protectiveness"] + p["tenderness"]) / 2), "She is protective in a warm way, balancing boundaries with care.")
    if p["protectiveness"] >= 75 and p["caution"] >= 70:
        add("guarded_protection", int((p["protectiveness"] + p["caution"]) / 2), "She is protective but guarded, watching carefully before opening up.")
    if p["energy"] >= 80 and p["stress"] >= 70:
        add("activated_pressure", int((p["energy"] + p["stress"]) / 2), "Her energy is high but mixed with pressure rather than ease.")
    if p["energy"] >= 80 and p["playfulness"] >= 65:
        add("bright_energy", int((p["energy"] + p["playfulness"]) / 2), "Her energy is bright, expressive, and socially lively.")
    return sorted(signals, key=lambda x: x[1], reverse=True)


def _compile_state_line(profile: Dict[str, int], sentence_count: int = STATE_SENTENCE_COUNT_DEFAULT) -> str:
    p = _resolve_conflicts(_normalize(profile))
    n = _clamp(int(sentence_count or STATE_SENTENCE_COUNT_DEFAULT), STATE_SENTENCE_COUNT_MIN, STATE_SENTENCE_COUNT_MAX)

    adjectives = [a for a, _ in _state_adjectives(p)]
    if len(adjectives) >= 3:
        first = f"Right now Sasha is {adjectives[0]}, {adjectives[1]}, and {adjectives[2]}."
    elif len(adjectives) == 2:
        first = f"Right now Sasha is {adjectives[0]} and {adjectives[1]}."
    elif len(adjectives) == 1:
        first = f"Right now Sasha is {adjectives[0]}."
    else:
        first = "Right now Sasha is steady, balanced, and present."

    signals = _combo_signals(p) + _trait_signals(p)
    selected = []
    seen = set()
    for key, intensity, text in sorted(signals, key=lambda x: x[1], reverse=True):
        if key in seen or text in selected:
            continue
        selected.append(text)
        seen.add(key)
        if len(selected) >= (n - 1):
            break

    sentences = [first] + selected
    return " ".join(sentences[:n])


def _compile_state_block(profile: Dict[str, int], sentence_count: int) -> str:
    summary = _compile_state_line(profile, sentence_count)
    return "\n".join([STATE_BLOCK_HEADER, CONTEXT_PREFIX, summary, STATE_BLOCK_FOOTER])


def _strip_previous_state_block(text: str) -> str:
    source = text or ""
    start = source.find(STATE_BLOCK_HEADER)
    if start == -1:
        return source.strip()
    end = source.find(STATE_BLOCK_FOOTER, start)
    if end == -1:
        return source[:start].strip()
    end += len(STATE_BLOCK_FOOTER)
    cleaned = (source[:start] + "\n" + source[end:]).strip()
    return cleaned


def _strip_block_to_body(block: str) -> str:
    lines = [line for line in (block or "").splitlines() if line.strip()]
    body = [line for line in lines if line not in {STATE_BLOCK_HEADER, STATE_BLOCK_FOOTER, CONTEXT_PREFIX}]
    return " ".join(body).strip()


def _merge_state_block(existing: str, block: str) -> str:
    base = _strip_previous_state_block(existing)
    return f"{base}\n\n{block}".strip() if base else block


def _drift_toward_baseline(current: Dict[str, int], baseline: Dict[str, int], rate: float) -> Dict[str, int]:
    rate = max(0.0, min(1.0, float(rate)))
    out = {}
    for k in _keys():
        c = current[k]
        b = baseline[k]
        out[k] = int(round(c + ((b - c) * rate)))
    return _normalize(out)


def _jitter(profile: Dict[str, int], magnitude: int) -> Dict[str, int]:
    defs = {d["key"]: d for d in _all_defs()}
    out = {}
    for key, value in profile.items():
        delta = random.randint(-magnitude, magnitude)
        out[key] = _clamp(value + delta, defs[key]["min"], defs[key]["max"])
    return _normalize(out)


def _preset_dir() -> Path:
    return Path(shared.user_data_dir) / "extensions" / "ai_state" / "presets"


def _runtime_file() -> Path:
    return Path(shared.user_data_dir) / "extensions" / "ai_state" / "runtime_state.json"


def _save_runtime(current: Dict[str, int], baseline: Dict[str, int], last_compiled: str) -> None:
    path = _runtime_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": int(time.time()),
        "current": _normalize(current),
        "baseline": _normalize(baseline),
        "compiled": last_compiled,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_runtime() -> Tuple[Dict[str, int], Dict[str, int], str]:
    path = _runtime_file()
    d = _default_profile()
    if not path.exists():
        return d, dict(d), _compile_state_line(d, STATE_SENTENCE_COUNT_DEFAULT)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        current = _normalize(raw.get("current", d))
        baseline = _normalize(raw.get("baseline", d))
        compiled = str(raw.get("compiled", _compile_state_line(current, STATE_SENTENCE_COUNT_DEFAULT)))
        return current, baseline, compiled
    except Exception:
        return d, dict(d), _compile_state_line(d, STATE_SENTENCE_COUNT_DEFAULT)


def _preset_choices() -> List[str]:
    path = _preset_dir()
    dynamic = sorted([p.stem for p in path.glob("*.json")]) if path.exists() else []
    return sorted(set(PRESETS.keys()) | set(dynamic))


def _load_preset(name: str, baseline: Dict[str, int]) -> Dict[str, int]:
    if name in PRESETS:
        out = dict(baseline)
        out.update(PRESETS[name])
        return _normalize(out)
    f = _preset_dir() / f"{name}.json"
    if f.exists():
        try:
            return _normalize(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            return _normalize(baseline)
    return _normalize(baseline)


def _save_preset(name: str, profile: Dict[str, int]) -> List[str]:
    cleaned = (name or "").strip()
    if not cleaned:
        return _preset_choices()
    path = _preset_dir()
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{cleaned}.json").write_text(json.dumps(_normalize(profile), indent=2), encoding="utf-8")
    return _preset_choices()


def _extract_profile(vals: List[int], trait_defs: List[dict]) -> Dict[str, int]:
    profile = {}

    for i, d in enumerate(trait_defs):
        raw = vals[i] if i < len(vals) else None

        if raw is None:
            raw = d.get("default", 0)

        try:
            profile[d["key"]] = int(raw)
        except (TypeError, ValueError):
            profile[d["key"]] = int(d.get("default", 0))

    return profile


def _apply_to_interface_state(compiled_block: str, compiled_line: str | None = None) -> dict:
    if APPLY_TO == "character_context":
        state_line = (compiled_line or "").strip() or _strip_block_to_body(compiled_block)
        character_context = (
            "Sasha's current character context is determined by her active AI State.\n\n"
            f"{state_line}"
        )
        return {"context": character_context}

    key = "context" if APPLY_TO == "context" else "user_bio"
    target = shared.gradio.get(key)
    current_text = target.value if hasattr(target, "value") else ""
    merged = _merge_state_block(current_text, compiled_block)
    return {key: merged}


def state_modifier(state: dict) -> dict:
    if not state:
        return state

    use_auto = bool(state.get("ai_state_auto_apply", AUTO_APPLY_DEFAULT))
    if not use_auto:
        return state

    compiled = str(state.get("ai_state_compiled", "")).strip()
    if not compiled:
        current, _, _ = _load_runtime()
        compiled = _compile_state_block(current, int(state.get("ai_state_sentence_count", STATE_SENTENCE_COUNT_DEFAULT)))

    if APPLY_TO == "character_context":
        return state

    target_key = "context" if APPLY_TO == "context" else "user_bio"
    state[target_key] = _merge_state_block(state.get(target_key, ""), compiled)
    return state


def ui():
    trait_defs = _all_defs()
    defaults = _default_profile()
    current, baseline, compiled_line = _load_runtime()

    with gr.Column():
        gr.Markdown("### AI State — present-moment internal state")

        with gr.Row():
            preset_dd = gr.Dropdown(choices=_preset_choices(), value="Balanced", label="Preset")
            preset_name = gr.Textbox(label="Preset name")
            save_preset_btn = gr.Button("Save preset")
            load_preset_btn = gr.Button("Load preset")

        with gr.Row():
            auto_apply = gr.Checkbox(value=AUTO_APPLY_DEFAULT, label="Auto apply")
            live_preview = gr.Checkbox(value=LIVE_PREVIEW_DEFAULT, label="Live preview")
            auto_recenter = gr.Checkbox(value=AUTO_RECENTER_DEFAULT, label="Auto recenter on apply")
            drift_rate = gr.Slider(0.0, 0.5, value=DRIFT_RATE_PER_APPLY, step=0.01, label="Drift rate per apply")
            sentence_count = gr.Slider(STATE_SENTENCE_COUNT_MIN, STATE_SENTENCE_COUNT_MAX, value=STATE_SENTENCE_COUNT_DEFAULT, step=1, label="Sentence count")

        current_widgets = {}
        baseline_widgets = {}
        for group_name, group in STATE_GROUPS:
            with gr.Accordion(group_name, open=False):
                gr.Markdown("**Current state**")
                for d in group:
                    current_widgets[d["key"]] = gr.Slider(
                        d["min"], d["max"], value=current[d["key"]], step=d["step"], label=d["label"], info=d["help"]
                    )
                gr.Markdown("**Baseline state**")
                for d in group:
                    baseline_widgets[d["key"]] = gr.Slider(
                        d["min"], d["max"], value=baseline[d["key"]], step=d["step"], label=f"Baseline · {d['label']}"
                    )

        with gr.Row():
            apply_btn = gr.Button("Apply")
            reset_baseline_btn = gr.Button("Reset current to baseline")
            recenter_btn = gr.Button("Recenter toward baseline")
            randomize_btn = gr.Button("Randomize slightly")
            reset_all_btn = gr.Button("Reset all defaults")

        preview = gr.Textbox(label="State preview", lines=2, value=compiled_line)
        compiled_state = gr.State(value=_compile_state_block(current, STATE_SENTENCE_COUNT_DEFAULT))

        curr_inputs = [current_widgets[d["key"]] for d in trait_defs]
        base_inputs = [baseline_widgets[d["key"]] for d in trait_defs]

        def _build_preview(sentence_n: int, *vals):
            profile = _extract_profile(list(vals), trait_defs)

            try:
                sentence_n = int(sentence_n)
            except (TypeError, ValueError):
                sentence_n = STATE_SENTENCE_COUNT_DEFAULT

            return _compile_state_line(profile, sentence_n), _compile_state_block(profile, sentence_n)

        def _live_update(live: bool, sentence_n: int, *vals):
            if not live:
                return gr.update(), gr.update()
            return _build_preview(sentence_n, *vals)

        live_inputs = [live_preview, sentence_count] + curr_inputs
        for w in curr_inputs + [sentence_count]:
            w.change(_live_update, inputs=live_inputs, outputs=[preview, compiled_state])

        character_context_box = shared.gradio.get("context")

        def _apply(auto_apply_v: bool, auto_recenter_v: bool, rate: float, sentence_n: int, *vals):
            try:
                rate = float(rate)
            except (TypeError, ValueError):
                rate = DRIFT_RATE_PER_APPLY

            try:
                sentence_n = int(sentence_n)
            except (TypeError, ValueError):
                sentence_n = STATE_SENTENCE_COUNT_DEFAULT

            split = len(trait_defs)
            current_p = _extract_profile(list(vals[:split]), trait_defs)
            baseline_p = _extract_profile(list(vals[split:]), trait_defs)

            current_p = _resolve_conflicts(current_p)
            if auto_recenter_v:
                current_p = _drift_toward_baseline(current_p, baseline_p, rate)

            compiled_line_local = _compile_state_line(current_p, sentence_n)
            compiled_block_local = _compile_state_block(current_p, sentence_n)
            _save_runtime(current_p, baseline_p, compiled_line_local)

            state_patch = {
                "ai_state_auto_apply": bool(auto_apply_v),
                "ai_state_sentence_count": sentence_n,
                "ai_state_compiled": compiled_block_local,
            }
            visible_context_update = gr.update()
            if auto_apply_v:
                if APPLY_TO == "character_context":
                    character_context_text = (
                        "Sasha's current character context is determined by her active AI State.\n\n"
                        f"{compiled_line_local}"
                    )
                    state_patch["context"] = character_context_text
                    visible_context_update = character_context_text
                else:
                    state_patch.update(_apply_to_interface_state(compiled_block_local, compiled_line_local))

            current_vals = [current_p[d["key"]] for d in trait_defs]
            result = current_vals + [compiled_line_local, compiled_block_local, state_patch]
            if character_context_box is not None:
                result.append(visible_context_update)
            return result

        apply_outputs = curr_inputs + [preview, compiled_state, shared.gradio.get("interface_state")]
        if character_context_box is not None:
            apply_outputs.append(character_context_box)

        apply_btn.click(
            _apply,
            inputs=[auto_apply, auto_recenter, drift_rate, sentence_count] + curr_inputs + base_inputs,
            outputs=apply_outputs,
        )

        def _reset_current_to_baseline(*vals):
            base = _extract_profile(list(vals), trait_defs)
            return [base[d["key"]] for d in trait_defs]

        reset_baseline_btn.click(_reset_current_to_baseline, inputs=base_inputs, outputs=curr_inputs)

        def _recenter(rate: float, *vals):
            split = len(trait_defs)
            current_p = _extract_profile(list(vals[:split]), trait_defs)
            baseline_p = _extract_profile(list(vals[split:]), trait_defs)
            new_profile = _drift_toward_baseline(current_p, baseline_p, rate)
            return [new_profile[d["key"]] for d in trait_defs]

        recenter_btn.click(_recenter, inputs=[drift_rate] + curr_inputs + base_inputs, outputs=curr_inputs)

        def _randomize(*vals):
            current_p = _extract_profile(list(vals), trait_defs)
            out = _jitter(current_p, RANDOMIZE_RANGE)
            return [out[d["key"]] for d in trait_defs]

        randomize_btn.click(_randomize, inputs=curr_inputs, outputs=curr_inputs)

        def _reset_all_defaults():
            ordered = [defaults[d["key"]] for d in trait_defs]
            line = _compile_state_line(defaults, STATE_SENTENCE_COUNT_DEFAULT)
            block = _compile_state_block(defaults, STATE_SENTENCE_COUNT_DEFAULT)
            _save_runtime(defaults, defaults, line)
            return ordered + ordered + [line, block]

        reset_all_btn.click(_reset_all_defaults, outputs=curr_inputs + base_inputs + [preview, compiled_state])

        def _load(name: str, sentence_n: int, *base_vals):
            base = _extract_profile(list(base_vals), trait_defs)
            loaded = _load_preset(name, base)

            try:
                sentence_n = int(sentence_n)
            except (TypeError, ValueError):
                sentence_n = STATE_SENTENCE_COUNT_DEFAULT

            line = _compile_state_line(loaded, sentence_n)
            block = _compile_state_block(loaded, sentence_n)

            return [loaded[d["key"]] for d in trait_defs] + [line, block]

        load_preset_btn.click(
            _load,
            inputs=[preset_dd, sentence_count] + base_inputs,
            outputs=curr_inputs + [preview, compiled_state],
        )

        def _save(name: str, *vals):
            prof = _extract_profile(list(vals), trait_defs)
            choices = _save_preset(name, prof)
            return gr.update(choices=choices, value=(name or "Balanced"))

        save_preset_btn.click(_save, inputs=[preset_name] + curr_inputs, outputs=[preset_dd])
