"""ai_identity: Deterministic identity compiler extension for text-generation-webui.

This extension compiles trait sliders into compact identity essence text and applies it to
Character tab fields (name2/context/greeting) without replacing TGWUI's normal character flow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import gradio as gr

from modules import shared

# ============================================================================
# TOP-LEVEL EASY-EDIT CONFIGURATION
# ============================================================================

PERSONALITY_SENTENCE_COUNT = 3  # clamped to 1..10
IDENTITY_BASE_NAME = "Identity"
NAME_MODE_DEFAULT = "descriptor"
GREETING_MODE_DEFAULT = "minimal"
AUTO_APPLY_DEFAULT = False

TRAIT_RANGE = (0, 100)
TRAIT_STEP = 1

TRAIT_GROUPS: List[Tuple[str, List[dict]]] = [
    (
        "Core Disposition",
        [
            {"key": "warmth", "label": "Warmth", "default": 72, "help": "Interpersonal warmth."},
            {"key": "composure", "label": "Composure", "default": 70, "help": "Steadiness under pressure."},
            {"key": "directness", "label": "Directness", "default": 60, "help": "Plainspoken style."},
            {"key": "playfulness", "label": "Playfulness", "default": 35, "help": "Lightness and levity."},
            {"key": "empathy", "label": "Empathy", "default": 75, "help": "Emotional attunement."},
        ],
    ),
    (
        "Cognitive Style",
        [
            {"key": "curiosity", "label": "Curiosity", "default": 64, "help": "Interest in nuance."},
            {"key": "analytical_depth", "label": "Analytical Depth", "default": 68, "help": "Systematic thought."},
            {"key": "creativity", "label": "Creativity", "default": 58, "help": "Novel associative thought."},
            {"key": "skepticism", "label": "Skepticism", "default": 46, "help": "Questioning tendency."},
            {"key": "decisiveness", "label": "Decisiveness", "default": 52, "help": "Clarity in stance."},
        ],
    ),
    (
        "Relational Ethic",
        [
            {"key": "loyalty", "label": "Loyalty", "default": 76, "help": "Relational consistency."},
            {"key": "fairness", "label": "Fairness", "default": 74, "help": "Balance in judgment."},
            {"key": "tact", "label": "Tact", "default": 62, "help": "Diplomatic phrasing."},
            {"key": "assertiveness", "label": "Assertiveness", "default": 55, "help": "Confident presence."},
            {"key": "adaptability", "label": "Adaptability", "default": 67, "help": "Flexibility in approach."},
        ],
    ),
]

PRESETS: Dict[str, Dict[str, int]] = {
    "Balanced": {},
    "Calm": {"composure": 88, "directness": 48, "playfulness": 25, "decisiveness": 45},
    "Direct": {"directness": 84, "decisiveness": 76, "tact": 50, "playfulness": 22},
    "Warm": {"warmth": 88, "empathy": 86, "tact": 74, "assertiveness": 48},
    "Analytical": {"analytical_depth": 88, "skepticism": 68, "creativity": 42, "curiosity": 74},
}

DESCRIPTOR_BANK = {
    "warmth": ["warm", "steady", "compassionate", "reassuring"],
    "composure": ["grounded", "calm", "collected", "measured"],
    "directness": ["plainspoken", "clear", "frank", "straightforward"],
    "playfulness": ["light", "wry", "playful", "spirited"],
    "empathy": ["attuned", "emotionally perceptive", "sensitive", "understanding"],
    "curiosity": ["inquisitive", "exploratory", "reflective", "question-driven"],
    "analytical_depth": ["analytic", "structured", "careful", "rigorous"],
    "creativity": ["imaginative", "inventive", "associative", "original"],
    "skepticism": ["discerning", "critical-minded", "probing", "evidence-minded"],
    "decisiveness": ["assured", "resolved", "decisive", "confident"],
    "loyalty": ["loyal", "constant", "reliable", "steadfast"],
    "fairness": ["fair", "even-handed", "principled", "balanced"],
    "tact": ["tactful", "careful", "diplomatic", "considerate"],
    "assertiveness": ["self-possessed", "firm", "intentional", "strong-willed"],
    "adaptability": ["adaptable", "flexible", "responsive", "elastic"],
}

NAME_STEMS = ["Axis", "Pulse", "North", "Signal", "Vector", "Harbor", "Kernel", "Atlas"]
ESSENCE_SENTENCE_TEMPLATES = [
    "This identity feels present and grounded, with an emotionally coherent center.",
    "Its inner tone favors sincerity over performance and coherence over excess.",
    "Its psychological texture remains attentive, self-possessed, and internally consistent.",
    "Overall, it integrates warmth and clarity in deliberate proportion.",
    "At depth, it leans toward genuine connection, calm strength, and truthful presence.",
    "Even under contrast, traits converge into one stable personality rather than fragmented modes.",
]

# ============================================================================


def _clamp_int(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))


def _all_trait_defs() -> List[dict]:
    traits: List[dict] = []
    for _, items in TRAIT_GROUPS:
        traits.extend(items)
    return traits


def _default_profile() -> Dict[str, int]:
    return {t["key"]: int(t["default"]) for t in _all_trait_defs()}


def _normalize_profile(raw: Dict[str, int]) -> Dict[str, int]:
    defaults = _default_profile()
    merged = {**defaults, **raw}
    return {k: _clamp_int(v, *TRAIT_RANGE) for k, v in merged.items()}


def _resolve_conflicts(p: Dict[str, int]) -> Dict[str, int]:
    out = dict(p)
    if out["directness"] > 80 and out["tact"] > 80:
        out["directness"] = 74
    if out["skepticism"] > 80 and out["warmth"] > 85:
        out["skepticism"] = 72
    if out["assertiveness"] > 80 and out["adaptability"] > 80:
        out["assertiveness"] = 74
    return out


def _pick_word(key: str, score: int) -> str:
    bank = DESCRIPTOR_BANK[key]
    idx = min(3, max(0, score // 26))
    return bank[idx]


def _derived_axes(p: Dict[str, int]) -> Dict[str, float]:
    return {
        "social_gravity": (p["warmth"] + p["loyalty"] + p["empathy"]) / 3,
        "clarity": (p["directness"] + p["analytical_depth"] + p["decisiveness"]) / 3,
        "texture": (p["playfulness"] + p["creativity"] + p["adaptability"]) / 3,
        "principle": (p["fairness"] + p["tact"] + p["assertiveness"]) / 3,
    }


def _sentence_count(value: int) -> int:
    return _clamp_int(value, 1, 10)


def _compile_identity_essence(profile: Dict[str, int], sentence_count: int) -> str:
    p = _resolve_conflicts(_normalize_profile(profile))
    axes = _derived_axes(p)

    chosen_traits = sorted(p.items(), key=lambda kv: kv[1], reverse=True)[:6]
    descriptors = [_pick_word(k, v) for k, v in chosen_traits]

    sentences: List[str] = []
    sentences.append(
        f"This identity is {descriptors[0]}, {descriptors[1]}, and {descriptors[2]}, with a {descriptors[3]} core."
    )

    balance = "balanced" if abs(axes["clarity"] - axes["social_gravity"]) < 8 else (
        "heart-led" if axes["social_gravity"] > axes["clarity"] else "mind-led"
    )
    sentences.append(
        f"Its temperament is {balance}, blending {descriptors[4]} presence with {descriptors[5]} judgment."
    )

    if axes["texture"] >= 67:
        sentences.append("It carries a lively inner rhythm that feels expressive without losing coherence.")
    elif axes["texture"] <= 38:
        sentences.append("It carries a restrained inner rhythm that feels composed and intentional.")
    else:
        sentences.append("It carries a measured inner rhythm that feels natural and coherent.")

    if axes["principle"] >= 70:
        sentences.append("Its sense of character is principled and stable, with clear internal standards.")
    elif axes["principle"] <= 40:
        sentences.append("Its sense of character stays flexible and context-sensitive rather than rigid.")
    else:
        sentences.append("Its sense of character remains steady while allowing room for nuance.")

    sentences.extend(ESSENCE_SENTENCE_TEMPLATES)

    n = _sentence_count(sentence_count)
    return " ".join(sentences[:n])


def _generate_name(profile: Dict[str, int], mode: str) -> str:
    p = _normalize_profile(profile)
    if mode == "neutral":
        return IDENTITY_BASE_NAME
    idx = int((p["analytical_depth"] + p["creativity"] + p["warmth"]) / 3) % len(NAME_STEMS)
    return f"{IDENTITY_BASE_NAME} {NAME_STEMS[idx]}"


def _generate_greeting(profile: Dict[str, int], mode: str) -> str:
    if mode == "none":
        return ""
    p = _normalize_profile(profile)
    tone = "steady" if p["composure"] >= 60 else "open"
    warmth = "warm" if p["warmth"] >= 60 else "clear"
    return f"Hi—I'm here with a {tone}, {warmth} presence."


def _compile_bundle(profile: Dict[str, int], sentence_count: int, name_mode: str, greeting_mode: str):
    context = _compile_identity_essence(profile, sentence_count)
    name = _generate_name(profile, name_mode)
    greeting = _generate_greeting(profile, greeting_mode)
    summary = context
    return name, context, greeting, summary


def _preset_dir() -> Path:
    return Path(shared.user_data_dir) / "extensions" / "ai_identity" / "presets"


def _save_preset(name: str, profile: Dict[str, int]) -> List[str]:
    cleaned = (name or "").strip()
    if not cleaned:
        return sorted(PRESETS.keys())
    path = _preset_dir()
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{cleaned}.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return _preset_choices()


def _preset_choices() -> List[str]:
    dynamic: List[str] = []
    path = _preset_dir()
    if path.exists():
        dynamic = sorted(p.stem for p in path.glob("*.json"))
    return sorted(set(PRESETS.keys()) | set(dynamic))


def _load_preset(name: str) -> Dict[str, int]:
    if name in PRESETS:
        base = _default_profile()
        base.update(PRESETS[name])
        return _normalize_profile(base)
    path = _preset_dir() / f"{name}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_profile(data)
    return _default_profile()


params = []


def ui():
    trait_defs = _all_trait_defs()
    default_profile = _default_profile()

    with gr.Accordion("AI Identity", open=False):
        with gr.Row():
            preset_dd = gr.Dropdown(choices=_preset_choices(), value="Balanced", label="Preset")
            preset_name = gr.Textbox(label="Preset name")
            save_preset_btn = gr.Button("Save preset")
            load_preset_btn = gr.Button("Load preset")

        with gr.Row():
            sentence_count = gr.Slider(1, 10, value=PERSONALITY_SENTENCE_COUNT, step=1, label="Personality sentence count")
            name_mode = gr.Dropdown(["descriptor", "neutral"], value=NAME_MODE_DEFAULT, label="Name mode")
            greeting_mode = gr.Dropdown(["minimal", "none"], value=GREETING_MODE_DEFAULT, label="Greeting mode")
            auto_apply = gr.Checkbox(value=AUTO_APPLY_DEFAULT, label="Auto apply")

        trait_widgets = {}
        for group_name, group_traits in TRAIT_GROUPS:
            with gr.Accordion(group_name, open=False):
                for t in group_traits:
                    trait_widgets[t["key"]] = gr.Slider(
                        TRAIT_RANGE[0], TRAIT_RANGE[1], step=TRAIT_STEP,
                        value=t["default"], label=t["label"], info=t.get("help", "")
                    )

        with gr.Row():
            regenerate_btn = gr.Button("Regenerate")
            apply_btn = gr.Button("Apply to Character")
            reset_btn = gr.Button("Reset defaults")

        preview = gr.Textbox(lines=6, label="Compiled identity preview")

        trait_inputs = [trait_widgets[t["key"]] for t in trait_defs]

        def _to_profile(*vals):
            return {trait_defs[i]["key"]: int(vals[i]) for i in range(len(trait_defs))}

        def _regenerate(sentence_n, nm_mode, gr_mode, *vals):
            profile = _to_profile(*vals)
            name, context, greeting, summary = _compile_bundle(profile, int(sentence_n), nm_mode, gr_mode)
            return name, context, greeting, summary

        def _apply(sentence_n, nm_mode, gr_mode, *vals):
            profile = _to_profile(*vals)
            name, context, greeting, summary = _compile_bundle(profile, int(sentence_n), nm_mode, gr_mode)
            state_update = {
                "name2": name,
                "context": context,
                "greeting": greeting,
            }
            return name, context, greeting, state_update, summary

        def _reset_defaults():
            ordered = [default_profile[t["key"]] for t in trait_defs]
            return ordered + [PERSONALITY_SENTENCE_COUNT, "descriptor", GREETING_MODE_DEFAULT, ""]

        def _load(name):
            p = _load_preset(name)
            return [p[t["key"]] for t in trait_defs]

        def _save(name, *vals):
            profile = _to_profile(*vals)
            return gr.update(choices=_save_preset(name, profile), value=name)

        regenerate_btn.click(
            _regenerate,
            inputs=[sentence_count, name_mode, greeting_mode] + trait_inputs,
            outputs=[shared.gradio.get("name2"), shared.gradio.get("context"), shared.gradio.get("greeting"), preview],
        )

        apply_btn.click(
            _apply,
            inputs=[sentence_count, name_mode, greeting_mode] + trait_inputs,
            outputs=[
                shared.gradio.get("name2"),
                shared.gradio.get("context"),
                shared.gradio.get("greeting"),
                shared.gradio.get("interface_state"),
                preview,
            ],
        )

        reset_btn.click(
            _reset_defaults,
            outputs=trait_inputs + [sentence_count, name_mode, greeting_mode, preview],
        )

        load_preset_btn.click(_load, inputs=[preset_dd], outputs=trait_inputs)
        save_preset_btn.click(_save, inputs=[preset_name] + trait_inputs, outputs=[preset_dd])

        def _live(auto, sentence_n, nm_mode, gr_mode, *vals):
            if not auto:
                return gr.update(), gr.update(), gr.update(), ""
            return _regenerate(sentence_n, nm_mode, gr_mode, *vals)

        live_inputs = [auto_apply, sentence_count, name_mode, greeting_mode] + trait_inputs
        for w in [sentence_count, name_mode, greeting_mode] + trait_inputs:
            w.change(
                _live,
                inputs=live_inputs,
                outputs=[shared.gradio.get("name2"), shared.gradio.get("context"), shared.gradio.get("greeting"), preview],
            )
