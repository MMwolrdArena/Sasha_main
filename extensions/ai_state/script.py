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
STATE_SENTENCE_COUNT_DEFAULT = 1
STATE_SENTENCE_COUNT_MIN = 1
STATE_SENTENCE_COUNT_MAX = 2
DERIVED_THRESHOLD = 60
PRIMARY_INTENSITY_THRESHOLD = 66
CONFLICT_STRONG_THRESHOLD = 72

# Prompt/context integration
STATE_BLOCK_HEADER = "[CURRENT INTERNAL STATE]"
STATE_BLOCK_FOOTER = "[END CURRENT INTERNAL STATE]"
CONTEXT_PREFIX = "Use this as current-moment tone guidance, not identity or memory:"
APPLY_TO = "context"  # "context" or "user_bio"

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

    # calmness vs stress
    if out["calmness"] > CONFLICT_STRONG_THRESHOLD and out["stress"] > CONFLICT_STRONG_THRESHOLD:
        out["stress"] = int((out["stress"] + (100 - out["calmness"])) / 2)

    # seriousness vs playfulness
    if out["seriousness"] > CONFLICT_STRONG_THRESHOLD and out["playfulness"] > CONFLICT_STRONG_THRESHOLD:
        midpoint = int((out["seriousness"] + out["playfulness"]) / 2)
        out["seriousness"] = min(100, midpoint + 6)
        out["playfulness"] = max(0, midpoint - 6)

    # openness vs social distance
    if out["openness"] > CONFLICT_STRONG_THRESHOLD and out["social_distance"] > CONFLICT_STRONG_THRESHOLD:
        out["social_distance"] = int(out["social_distance"] * 0.75)

    # confidence vs caution (hesitation proxy)
    if out["confidence"] > CONFLICT_STRONG_THRESHOLD and out["caution"] > CONFLICT_STRONG_THRESHOLD:
        out["caution"] = int(out["caution"] * 0.8)

    return _normalize(out)


def _derived_blends(p: Dict[str, int]) -> List[Tuple[str, float]]:
    return [
        ("composed attention", (p["calmness"] + p["focus"]) / 2),
        ("gentle protectiveness", (p["protectiveness"] + p["tenderness"]) / 2),
        ("decisive steadiness", (p["seriousness"] + p["confidence"] + p["focus"]) / 3),
        ("light warmth", (p["playfulness"] + p["openness"] + (100 - p["social_distance"])) / 3),
        ("guardedness", (p["stress"] + p["caution"] + p["social_distance"]) / 3),
        ("active engagement", (p["energy"] + p["curiosity"] + p["attentiveness"]) / 3),
        ("relational patience", (p["patience"] + p["calmness"] + p["attentiveness"]) / 3),
    ]


def _top_descriptors(p: Dict[str, int]) -> List[str]:
    items = _derived_blends(p)
    strong = [name for name, score in sorted(items, key=lambda x: x[1], reverse=True) if score >= DERIVED_THRESHOLD]

    # fallback from raw states if needed
    if len(strong) < 2:
        ranked_raw = sorted(p.items(), key=lambda kv: kv[1], reverse=True)
        for key, value in ranked_raw:
            if value < PRIMARY_INTENSITY_THRESHOLD:
                continue
            phrase = {
                "calmness": "calm",
                "focus": "focused",
                "confidence": "confident",
                "seriousness": "serious",
                "playfulness": "playful",
                "protectiveness": "protective",
                "patience": "patient",
                "tenderness": "tender",
                "curiosity": "curious",
                "caution": "cautious",
                "openness": "open",
                "social_distance": "reserved",
                "stress": "tense",
                "energy": "energized",
                "attentiveness": "attentive",
            }.get(key)
            if phrase and phrase not in strong:
                strong.append(phrase)
            if len(strong) >= 3:
                break

    return strong[:3] if strong else ["steady", "present"]


def _compile_state_line(profile: Dict[str, int], sentence_count: int = STATE_SENTENCE_COUNT_DEFAULT) -> str:
    p = _resolve_conflicts(_normalize(profile))
    descriptors = _top_descriptors(p)

    lead = f"Right now Sasha is {descriptors[0]}"
    if len(descriptors) == 2:
        line = f"{lead} and {descriptors[1]}."
    else:
        line = f"{lead}, {descriptors[1]}, and {descriptors[2]}."

    n = _clamp(sentence_count, STATE_SENTENCE_COUNT_MIN, STATE_SENTENCE_COUNT_MAX)
    if n == 1:
        return line

    balance_signal = (p["playfulness"] - p["seriousness"])
    mood_vector = "reflective" if balance_signal < -15 else ("light" if balance_signal > 15 else "balanced")
    tail = f"Her present tone is {mood_vector}, with {int((p['attentiveness'] + p['focus']) / 2)}% attention stability."
    return f"{line} {tail}"


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
    return {trait_defs[i]["key"]: int(vals[i]) for i in range(len(trait_defs))}


def _apply_to_interface_state(compiled_block: str) -> dict:
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
            return _compile_state_line(profile, int(sentence_n)), _compile_state_block(profile, int(sentence_n))

        def _live_update(live: bool, sentence_n: int, *vals):
            if not live:
                return gr.update(), gr.update()
            return _build_preview(sentence_n, *vals)

        live_inputs = [live_preview, sentence_count] + curr_inputs
        for w in curr_inputs + [sentence_count]:
            w.change(_live_update, inputs=live_inputs, outputs=[preview, compiled_state])

        def _apply(auto_apply_v: bool, auto_recenter_v: bool, rate: float, sentence_n: int, *vals):
            split = len(trait_defs)
            current_p = _extract_profile(list(vals[:split]), trait_defs)
            baseline_p = _extract_profile(list(vals[split:]), trait_defs)

            current_p = _resolve_conflicts(current_p)
            if auto_recenter_v:
                current_p = _drift_toward_baseline(current_p, baseline_p, rate)

            compiled_line_local = _compile_state_line(current_p, int(sentence_n))
            compiled_block_local = _compile_state_block(current_p, int(sentence_n))
            _save_runtime(current_p, baseline_p, compiled_line_local)

            state_patch = {
                "ai_state_auto_apply": bool(auto_apply_v),
                "ai_state_sentence_count": int(sentence_n),
                "ai_state_compiled": compiled_block_local,
            }
            if auto_apply_v:
                state_patch.update(_apply_to_interface_state(compiled_block_local))

            current_vals = [current_p[d["key"]] for d in trait_defs]
            return current_vals + [compiled_line_local, compiled_block_local, state_patch]

        apply_btn.click(
            _apply,
            inputs=[auto_apply, auto_recenter, drift_rate, sentence_count] + curr_inputs + base_inputs,
            outputs=curr_inputs + [preview, compiled_state, shared.gradio.get("interface_state")],
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

        def _load(name: str, *base_vals):
            base = _extract_profile(list(base_vals), trait_defs)
            loaded = _load_preset(name, base)
            return [loaded[d["key"]] for d in trait_defs]

        load_preset_btn.click(_load, inputs=[preset_dd] + base_inputs, outputs=curr_inputs)

        def _save(name: str, *vals):
            prof = _extract_profile(list(vals), trait_defs)
            choices = _save_preset(name, prof)
            return gr.update(choices=choices, value=(name or "Balanced"))

        save_preset_btn.click(_save, inputs=[preset_name] + curr_inputs, outputs=[preset_dd])
