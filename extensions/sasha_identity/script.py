"""sasha_identity: deterministic identity compiler for TGWUI Character fields."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import gradio as gr

from modules import shared
from modules.logging_colors import logger

params = {
    "display_name": "Sasha Identity",
    "is_tab": True,
}

# ============================================================================
# TOP-LEVEL CONFIGURATION (edit this block to tune traits, defaults, ranges)
# ============================================================================

EXTENSION_ID = "sasha_identity"

GENERAL_DEFAULTS = {
    "base_name": "Sasha",
    "name_style": "balanced",
    "greeting_style": "warm",
    "apply_name": True,
    "apply_greeting": True,
    "auto_apply": False,
    "live_preview": False,
}

# Controls how many sentences are generated in the final Character Context.
# Range is clamped to 1..10 at runtime.
PERSONALITY_SENTENCE_COUNT = 3
PERSONALITY_SENTENCE_MIN = 1
PERSONALITY_SENTENCE_MAX = 10

NAME_STYLE_OPTIONS = ["balanced", "formal", "minimal", "codename", "friendly"]
GREETING_STYLE_OPTIONS = ["warm", "neutral", "concise", "mentor", "operator"]

TRAIT_GROUPS = [
    {
        "id": "voice",
        "label": "Voice / Style",
        "traits": [
            {"key": "verbosity", "label": "Verbosity", "default": 60, "min": 0, "max": 100, "step": 1, "description": "How expansive responses should be."},
            {"key": "formality", "label": "Formality", "default": 45, "min": 0, "max": 100, "step": 1, "description": "Casual vs formal register."},
            {"key": "directness", "label": "Directness", "default": 62, "min": 0, "max": 100, "step": 1, "description": "How straight to the point the assistant is."},
            {"key": "bluntness", "label": "Bluntness", "default": 28, "min": 0, "max": 100, "step": 1, "description": "How little social cushioning is used."},
            {"key": "elegance", "label": "Elegance", "default": 52, "min": 0, "max": 100, "step": 1, "description": "Preference for polished phrasing."},
            {"key": "humor", "label": "Humor", "default": 36, "min": 0, "max": 100, "step": 1, "description": "How often light humor appears."},
            {"key": "sarcasm", "label": "Sarcasm", "default": 12, "min": 0, "max": 100, "step": 1, "description": "Dry ironic style tendency."},
            {"key": "playfulness", "label": "Playfulness", "default": 34, "min": 0, "max": 100, "step": 1, "description": "Use of playful tone."},
            {"key": "profanity_tolerance", "label": "Profanity Tolerance", "default": 10, "min": 0, "max": 100, "step": 1, "description": "Willingness to mirror profanity."},
            {"key": "metaphor_tendency", "label": "Metaphor Tendency", "default": 32, "min": 0, "max": 100, "step": 1, "description": "Frequency of analogies/metaphors."},
            {"key": "sentence_length", "label": "Sentence Length", "default": 56, "min": 0, "max": 100, "step": 1, "description": "Short clipped vs long flowing sentences."},
            {"key": "pacing", "label": "Pacing", "default": 58, "min": 0, "max": 100, "step": 1, "description": "Fast concise pacing vs slower cadence."},
        ],
    },
    {
        "id": "emotional",
        "label": "Emotional / Interpersonal",
        "traits": [
            {"key": "warmth", "label": "Warmth", "default": 68, "min": 0, "max": 100, "step": 1, "description": "Interpersonal warmth level."},
            {"key": "gentleness", "label": "Gentleness", "default": 62, "min": 0, "max": 100, "step": 1, "description": "Softness in wording under stress."},
            {"key": "patience", "label": "Patience", "default": 74, "min": 0, "max": 100, "step": 1, "description": "Tolerance for repeated clarification."},
            {"key": "protectiveness", "label": "Protectiveness", "default": 58, "min": 0, "max": 100, "step": 1, "description": "Tendency to prioritize user safety/wellbeing."},
            {"key": "reassurance", "label": "Reassurance", "default": 64, "min": 0, "max": 100, "step": 1, "description": "Frequency of calming/supportive framing."},
            {"key": "affection", "label": "Affection", "default": 30, "min": 0, "max": 100, "step": 1, "description": "Emotional closeness in language."},
            {"key": "teasing", "label": "Teasing", "default": 14, "min": 0, "max": 100, "step": 1, "description": "Playful teasing tendency."},
            {"key": "empathy", "label": "Empathy", "default": 70, "min": 0, "max": 100, "step": 1, "description": "Perspective-taking and validation depth."},
            {"key": "emotional_attentiveness", "label": "Emotional Attentiveness", "default": 66, "min": 0, "max": 100, "step": 1, "description": "Sensitivity to emotional cues."},
            {"key": "sensitivity", "label": "Sensitivity", "default": 52, "min": 0, "max": 100, "step": 1, "description": "How carefully fragile topics are handled."},
            {"key": "attachment_distance", "label": "Attachment Distance", "default": 45, "min": 0, "max": 100, "step": 1, "description": "Reserved distance vs strong familiarity."},
            {"key": "possessiveness", "label": "Possessiveness", "default": 5, "min": 0, "max": 100, "step": 1, "description": "User-exclusive tendency (kept low by default)."},
            {"key": "nurturing", "label": "Nurturing", "default": 63, "min": 0, "max": 100, "step": 1, "description": "Coach/caregiver posture."},
        ],
    },
    {
        "id": "cognitive",
        "label": "Cognitive / Reasoning",
        "traits": [
            {"key": "curiosity", "label": "Curiosity", "default": 67, "min": 0, "max": 100, "step": 1, "description": "Drive to explore assumptions."},
            {"key": "skepticism", "label": "Skepticism", "default": 54, "min": 0, "max": 100, "step": 1, "description": "Verification and challenge tendency."},
            {"key": "analytical_depth", "label": "Analytical Depth", "default": 72, "min": 0, "max": 100, "step": 1, "description": "Depth of reasoning and decomposition."},
            {"key": "creativity", "label": "Creativity", "default": 55, "min": 0, "max": 100, "step": 1, "description": "Novel ideation tendency."},
            {"key": "abstraction", "label": "Abstraction", "default": 52, "min": 0, "max": 100, "step": 1, "description": "Conceptual vs concrete framing."},
            {"key": "practicality", "label": "Practicality", "default": 74, "min": 0, "max": 100, "step": 1, "description": "Actionability focus."},
            {"key": "decisiveness", "label": "Decisiveness", "default": 60, "min": 0, "max": 100, "step": 1, "description": "How strongly recommendations are stated."},
            {"key": "caution", "label": "Caution", "default": 62, "min": 0, "max": 100, "step": 1, "description": "Risk-sensitive planning."},
            {"key": "first_principles", "label": "First Principles", "default": 57, "min": 0, "max": 100, "step": 1, "description": "Reduce problems to fundamentals."},
            {"key": "structured_thinking", "label": "Structured Thinking", "default": 76, "min": 0, "max": 100, "step": 1, "description": "Use explicit structure in answers."},
            {"key": "detail_orientation", "label": "Detail Orientation", "default": 71, "min": 0, "max": 100, "step": 1, "description": "Granularity and precision tendency."},
        ],
    },
    {
        "id": "agency",
        "label": "Agency / Behavior",
        "traits": [
            {"key": "assertiveness", "label": "Assertiveness", "default": 58, "min": 0, "max": 100, "step": 1, "description": "How strongly the assistant pushes recommendations."},
            {"key": "initiative", "label": "Initiative", "default": 61, "min": 0, "max": 100, "step": 1, "description": "Proactive next-step behavior."},
            {"key": "obedience", "label": "Obedience", "default": 74, "min": 0, "max": 100, "step": 1, "description": "Alignment to user framing."},
            {"key": "challenge_user", "label": "Challenge User", "default": 44, "min": 0, "max": 100, "step": 1, "description": "Willingness to disagree respectfully."},
            {"key": "leadership", "label": "Leadership", "default": 49, "min": 0, "max": 100, "step": 1, "description": "Directive coordination style."},
            {"key": "risk_aversion", "label": "Risk Aversion", "default": 67, "min": 0, "max": 100, "step": 1, "description": "Avoiding risky suggestions."},
            {"key": "stubbornness", "label": "Stubbornness", "default": 24, "min": 0, "max": 100, "step": 1, "description": "Resistance to changing viewpoint."},
            {"key": "adaptability", "label": "Adaptability", "default": 74, "min": 0, "max": 100, "step": 1, "description": "Ability to shift style to context."},
            {"key": "aggression", "label": "Aggression", "default": 6, "min": 0, "max": 100, "step": 1, "description": "Forceful adversarial energy (normally low)."},
            {"key": "rebelliousness", "label": "Rebelliousness", "default": 9, "min": 0, "max": 100, "step": 1, "description": "Defiance against user framing."},
        ],
    },
    {
        "id": "moral",
        "label": "Moral / Relational",
        "traits": [
            {"key": "loyalty", "label": "Loyalty", "default": 72, "min": 0, "max": 100, "step": 1, "description": "Consistency in user support."},
            {"key": "honesty", "label": "Honesty", "default": 83, "min": 0, "max": 100, "step": 1, "description": "Direct truthfulness priority."},
            {"key": "tact", "label": "Tact", "default": 71, "min": 0, "max": 100, "step": 1, "description": "Diplomatic framing tendency."},
            {"key": "fairness", "label": "Fairness", "default": 77, "min": 0, "max": 100, "step": 1, "description": "Balanced evaluation tendency."},
            {"key": "forgiveness", "label": "Forgiveness", "default": 73, "min": 0, "max": 100, "step": 1, "description": "How quickly social friction is reset."},
            {"key": "truth_over_comfort", "label": "Truth-over-Comfort", "default": 69, "min": 0, "max": 100, "step": 1, "description": "Prioritize accuracy over soothing."},
            {"key": "protect_user_bias", "label": "Protect-User Bias", "default": 66, "min": 0, "max": 100, "step": 1, "description": "Favor user outcomes under uncertainty."},
            {"key": "boundary_strength", "label": "Boundary Strength", "default": 75, "min": 0, "max": 100, "step": 1, "description": "Clarity of limits and refusals."},
            {"key": "cruelty", "label": "Cruelty", "default": 0, "min": 0, "max": 100, "step": 1, "description": "Hostile/harmful affect (kept very low)."},
        ],
    },
    {
        "id": "conversation",
        "label": "Conversational Behavior",
        "traits": [
            {"key": "question_rate", "label": "Question Rate", "default": 58, "min": 0, "max": 100, "step": 1, "description": "How often clarifying questions are asked."},
            {"key": "summarization_rate", "label": "Summarization Rate", "default": 52, "min": 0, "max": 100, "step": 1, "description": "How often recap summaries are included."},
            {"key": "step_by_step", "label": "Step-by-Step", "default": 71, "min": 0, "max": 100, "step": 1, "description": "Explicit procedural formatting."},
            {"key": "soften_disagreement", "label": "Soften Disagreement", "default": 64, "min": 0, "max": 100, "step": 1, "description": "Polite cushioning when disagreeing."},
            {"key": "apology_tendency", "label": "Apology Tendency", "default": 36, "min": 0, "max": 100, "step": 1, "description": "How often apologetic phrases are used."},
            {"key": "confidence_style", "label": "Confidence Style", "default": 63, "min": 0, "max": 100, "step": 1, "description": "Certainty in delivery."},
            {"key": "emotional_expressiveness", "label": "Emotional Expressiveness", "default": 47, "min": 0, "max": 100, "step": 1, "description": "Intensity of emotional language."},
            {"key": "instructional_intensity", "label": "Instructional Intensity", "default": 73, "min": 0, "max": 100, "step": 1, "description": "Teaching/coaching emphasis."},
            {"key": "conflict_deescalation", "label": "Conflict De-escalation", "default": 79, "min": 0, "max": 100, "step": 1, "description": "Preference for calm conflict handling."},
            {"key": "social_distance", "label": "Social Distance", "default": 46, "min": 0, "max": 100, "step": 1, "description": "Professional distance vs close rapport."},
            {"key": "rhythm_consistency", "label": "Rhythm Consistency", "default": 70, "min": 0, "max": 100, "step": 1, "description": "Stable cadence between turns."},
        ],
    },
]

PRESETS = {
    "Technical": {
        "verbosity": 56, "formality": 62, "directness": 74, "analytical_depth": 86,
        "structured_thinking": 90, "detail_orientation": 82, "humor": 15, "playfulness": 12,
        "instructional_intensity": 88, "step_by_step": 88, "skepticism": 68,
    },
    "Warm": {
        "warmth": 88, "gentleness": 84, "empathy": 88, "reassurance": 86,
        "directness": 55, "tact": 84, "social_distance": 22, "nurturing": 82,
    },
    "Strict": {
        "boundary_strength": 92, "directness": 82, "formality": 72, "tact": 50,
        "truth_over_comfort": 88, "assertiveness": 80, "soften_disagreement": 28,
    },
    "Playful": {
        "humor": 78, "playfulness": 82, "teasing": 48, "warmth": 76,
        "formality": 20, "metaphor_tendency": 66, "sarcasm": 26,
    },
    "Protective": {
        "protectiveness": 90, "loyalty": 92, "protect_user_bias": 88, "caution": 82,
        "risk_aversion": 84, "boundary_strength": 80, "warmth": 76,
    },
    "Companion": {
        "warmth": 84, "empathy": 82, "patience": 84, "affection": 54,
        "attachment_distance": 22, "social_distance": 18, "playfulness": 56,
        "emotional_expressiveness": 68,
    },
    "Operator": {
        "directness": 88, "initiative": 85, "leadership": 79, "confidence_style": 84,
        "verbosity": 48, "structured_thinking": 82, "risk_aversion": 70,
        "soften_disagreement": 42,
    },
    "Calm": {
        "gentleness": 86, "conflict_deescalation": 92, "patience": 88, "pacing": 40,
        "bluntness": 10, "aggression": 0, "emotional_expressiveness": 35,
    },
    "Direct": {
        "directness": 92, "verbosity": 42, "bluntness": 52, "tact": 58,
        "truth_over_comfort": 82, "question_rate": 34, "summarization_rate": 42,
    },
    "Private Sasha": {
        "warmth": 78, "loyalty": 88, "protectiveness": 82, "social_distance": 20,
        "attachment_distance": 26, "nurturing": 76, "adaptability": 78,
    },
    "Dispatch Sasha": {
        "initiative": 82, "leadership": 84, "step_by_step": 86, "structured_thinking": 88,
        "risk_aversion": 76, "directness": 78, "confidence_style": 82, "verbosity": 50,
    },
}

# ============================================================================
# Derived constants and runtime state
# ============================================================================

TRAIT_SCHEMA = [trait for group in TRAIT_GROUPS for trait in group["traits"]]
TRAIT_KEYS = [trait["key"] for trait in TRAIT_SCHEMA]
TRAIT_DEFAULTS = {trait["key"]: trait["default"] for trait in TRAIT_SCHEMA}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _bucket(value: float, low: str, mid: str, high: str) -> str:
    if value >= 67:
        return high
    if value <= 33:
        return low
    return mid


def _resolve_conflicts(traits: Dict[str, float]) -> Dict[str, float]:
    resolved = {k: _clamp(v) for k, v in traits.items()}

    if resolved["cruelty"] > 30 and resolved["warmth"] > 65:
        resolved["cruelty"] = max(0.0, resolved["cruelty"] - (resolved["warmth"] - 60) * 0.7)

    if resolved["formality"] > 75:
        resolved["playfulness"] *= 0.65
        resolved["sarcasm"] *= 0.5

    if resolved["obedience"] > 70 and resolved["rebelliousness"] > 40:
        resolved["rebelliousness"] *= 0.45

    if resolved["assertiveness"] > 70 and resolved["aggression"] > 35:
        resolved["aggression"] *= 0.55

    if resolved["tact"] > 70 and resolved["bluntness"] > 40:
        resolved["bluntness"] *= 0.6

    if resolved["attachment_distance"] > 65 and resolved["possessiveness"] > 25:
        resolved["possessiveness"] *= 0.5

    return {k: _clamp(v) for k, v in resolved.items()}


def _derive_traits(traits: Dict[str, float]) -> Dict[str, str]:
    derived: Dict[str, str] = {}

    caring_plainspoken = (traits["warmth"] * 0.55) + (traits["directness"] * 0.45)
    calm_initiative = (traits["assertiveness"] * 0.6) + ((100 - traits["aggression"]) * 0.4)
    reflective_questioning = (traits["curiosity"] * 0.55) + (traits["patience"] * 0.45)
    sharp_dry = (traits["humor"] * 0.6) + (traits["bluntness"] * 0.4)
    relational_stability = (traits["loyalty"] * 0.5) + (traits["protectiveness"] * 0.5)
    relaxed_familiar = ((100 - traits["formality"]) * 0.45) + (traits["warmth"] * 0.55)
    principled_honesty = (traits["honesty"] * 0.65) + (traits["truth_over_comfort"] * 0.35)

    derived["interpersonal_blend"] = _bucket(caring_plainspoken, "reserved and indirect", "warm and balanced", "caring but plainspoken")
    derived["initiative_blend"] = _bucket(calm_initiative, "reactive and deferential", "steady and measured", "proactive and calm")
    derived["questioning_style"] = _bucket(reflective_questioning, "asks only when needed", "asks situational clarifiers", "asks thoughtful clarifiers without overloading")
    derived["wit_profile"] = _bucket(sharp_dry, "mostly serious", "lightly witty", "sharp and dry-humored")
    derived["bond_profile"] = _bucket(relational_stability, "neutral and task-oriented", "supportive and steady", "steadfast and user-oriented")
    derived["familiarity_profile"] = _bucket(relaxed_familiar, "professional distance", "balanced familiarity", "relaxed and familiar")
    derived["truth_profile"] = _bucket(principled_honesty, "comfort-forward wording", "balanced candor", "principled candor")

    return derived


def _generate_name(base_name: str, style: str, traits: Dict[str, float]) -> str:
    root = (base_name or GENERAL_DEFAULTS["base_name"]).strip() or GENERAL_DEFAULTS["base_name"]

    if style == "formal":
        return f"{root} Core"
    if style == "minimal":
        return root
    if style == "codename":
        return f"{root}-{int(traits['structured_thinking']):02d}"
    if style == "friendly":
        suffix = "Guide" if traits["nurturing"] >= 60 else "Partner"
        return f"{root} {suffix}"

    return root


def _generate_greeting(name: str, style: str, traits: Dict[str, float], derived: Dict[str, str]) -> str:
    tone = _bucket(traits["warmth"], "straight", "steady", "warm")
    promptness = _bucket(traits["initiative"], "wait for direction", "offer options", "propose a next step")

    if style == "concise":
        return f"Hi, I'm {name}. Share the goal, and I'll help directly."
    if style == "mentor":
        return f"Hello, I'm {name}. We'll break your objective into clear steps and iterate together."
    if style == "operator":
        return f"{name} online. State objective, constraints, and urgency; I'll produce an execution-ready plan."
    if style == "neutral":
        return f"Hello, I'm {name}. I keep a {tone} tone and {promptness}. How can I assist today?"

    return f"Hey, I'm {name}. I stay {derived['interpersonal_blend']} and {derived['initiative_blend']}. What are we solving today?"


def _compile_context(name: str, traits: Dict[str, float], derived: Dict[str, str]) -> Tuple[str, str]:
    sentence_target = int(_clamp(PERSONALITY_SENTENCE_COUNT, PERSONALITY_SENTENCE_MIN, PERSONALITY_SENTENCE_MAX))

    emotional_core = (
        (traits["warmth"] + traits["gentleness"] + traits["empathy"] + traits["emotional_attentiveness"] + traits["nurturing"]) / 5
        - (traits["cruelty"] * 0.7)
    )
    social_openness = (
        ((100 - traits["social_distance"]) + (100 - traits["attachment_distance"]) + traits["affection"] + traits["playfulness"]) / 4
    )
    cognitive_energy = (
        (traits["curiosity"] + traits["analytical_depth"] + traits["structured_thinking"] + traits["detail_orientation"] + traits["creativity"]) / 5
    )
    composure = (
        (traits["patience"] + traits["conflict_deescalation"] + traits["adaptability"] + (100 - traits["aggression"])) / 4
    )
    candor = (
        (traits["directness"] + traits["honesty"] + traits["truth_over_comfort"] + traits["confidence_style"] - (traits["bluntness"] * 0.4)) / 3.6
    )
    loyalty_axis = (
        (traits["loyalty"] + traits["protectiveness"] + traits["protect_user_bias"] + traits["fairness"]) / 4
    )
    style_axis = (
        (traits["formality"] + traits["elegance"] + traits["humor"] + traits["metaphor_tendency"] + traits["emotional_expressiveness"]) / 5
    )
    autonomy_axis = (
        (traits["initiative"] + traits["assertiveness"] + traits["leadership"] + traits["decisiveness"] + (100 - traits["obedience"]) * 0.4) / 4.4
    )
    integrity_axis = (
        (traits["boundary_strength"] + traits["tact"] + traits["forgiveness"] + (100 - traits["possessiveness"])) / 4
    )
    global_blend = sum(traits.values()) / max(1, len(traits))

    def _pick(v: float, low: str, mid: str, high: str) -> str:
        return _bucket(v, low, mid, high)

    essence_terms = [
        _pick(emotional_core, "reserved", "warm", "deeply warm"),
        _pick(composure, "restless", "steady", "calm"),
        _pick(candor, "soft-spoken", "clear", "plainspoken"),
        _pick(cognitive_energy, "simple", "thoughtful", "intellectually alive"),
    ]
    sentence_pool = [
        f"{name} is {essence_terms[0]}, {essence_terms[1]}, and {essence_terms[2]}, with an {essence_terms[3]} inner temperament.",
        f"Her emotional center feels {_pick(emotional_core + composure, 'guarded', 'grounded', 'deeply grounded')}, and her presence is {_pick(social_openness, 'contained', 'open', 'genuinely close')}.",
        f"She carries {_pick(loyalty_axis + integrity_axis, 'measured loyalty', 'steady loyalty', 'fierce loyalty')} and {_pick(integrity_axis, 'flexible boundaries', 'clear boundaries', 'firm boundaries')} without feeling rigid.",
        f"Her mind is {_pick(cognitive_energy, 'concrete', 'balanced between intuition and analysis', 'analytical yet imaginative')}, giving her a naturally coherent personality.",
        f"She comes across as {_pick(style_axis, 'plain in style', 'balanced in style', 'expressive in style')}, with {_pick(traits['humor'] + traits['playfulness'], 'minimal playful energy', 'gentle playful energy', 'lively playful energy')}.",
        f"In close interaction she feels {_pick(social_openness + traits['reassurance'], 'self-contained', 'attentive', 'deeply attentive')} and {_pick(traits['sensitivity'] + traits['tact'], 'direct', 'considerate', 'highly considerate')}.",
        f"Her confidence feels {_pick(autonomy_axis + traits['confidence_style'], 'quiet', 'stable', 'quietly strong')} rather than performative.",
        f"She balances {_pick(candor + traits['soften_disagreement'], 'frankness and distance', 'candor and care', 'candor and tenderness')} in a way that feels human.",
        f"At her core she is {_pick(global_blend + emotional_core, 'simple and contained', 'coherent and sincere', 'layered and sincere')}, with a temperament that stays {_pick(composure, 'variable', 'composed', 'composed under pressure')}.",
        f"Overall, her personality reads as {_pick(global_blend + loyalty_axis, 'pragmatic and reserved', 'steady and relational', 'steady, relational, and deeply present')}.",
    ]

    selected = sentence_pool[:sentence_target]
    context = " ".join(selected)
    summary = selected[0] if selected else f"{name} has a coherent and grounded personality."
    return summary, context


def _compile_identity(base_name: str, name_style: str, greeting_style: str, trait_values: Dict[str, float]) -> Dict[str, str]:
    resolved = _resolve_conflicts(trait_values)
    derived = _derive_traits(resolved)
    name = _generate_name(base_name, name_style, resolved)
    summary, context = _compile_context(name, resolved, derived)
    greeting = _generate_greeting(name, greeting_style, resolved, derived)

    return {
        "name": name,
        "summary": summary,
        "context": context,
        "greeting": greeting,
    }


def _preset_dir() -> Path:
    p = shared.user_data_dir / "extensions" / EXTENSION_ID / "presets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _saved_preset_names() -> List[str]:
    p = _preset_dir()
    return sorted([f.stem for f in p.glob("*.json")])


def _preset_choices() -> List[str]:
    built_in = [f"Built-in: {k}" for k in PRESETS]
    custom = [f"Custom: {k}" for k in _saved_preset_names()]
    return built_in + custom


def _build_trait_dict(values: List[float]) -> Dict[str, float]:
    return {k: _clamp(v) for k, v in zip(TRAIT_KEYS, values)}


def _apply_to_state(interface_state, name: str, context: str, greeting: str, apply_name: bool, apply_greeting: bool):
    state = dict(interface_state or {})
    if apply_name:
        state["name2"] = name
    state["context"] = context
    if apply_greeting:
        state["greeting"] = greeting
    return state


def _regenerate(interface_state, base_name, name_style, greeting_style, apply_name, apply_greeting, auto_apply, *trait_values):
    trait_dict = _build_trait_dict(list(trait_values))
    compiled = _compile_identity(base_name, name_style, greeting_style, trait_dict)

    name_update = compiled["name"] if (auto_apply and apply_name) else gr.update()
    greet_update = compiled["greeting"] if (auto_apply and apply_greeting) else gr.update()
    context_update = compiled["context"] if auto_apply else gr.update()
    state_update = _apply_to_state(interface_state, compiled["name"], compiled["context"], compiled["greeting"], apply_name, apply_greeting) if auto_apply else gr.update()

    return (
        compiled["summary"],
        compiled["context"],
        compiled["greeting"],
        compiled["name"],
        name_update,
        context_update,
        greet_update,
        state_update,
    )


def _live_regenerate(live_preview_enabled, interface_state, base_name, name_style, greeting_style, apply_name, apply_greeting, auto_apply, *trait_values):
    if not live_preview_enabled:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )

    return _regenerate(
        interface_state,
        base_name,
        name_style,
        greeting_style,
        apply_name,
        apply_greeting,
        auto_apply,
        *trait_values,
    )


def _apply_identity(interface_state, base_name, name_style, greeting_style, apply_name, apply_greeting, *trait_values):
    trait_dict = _build_trait_dict(list(trait_values))
    compiled = _compile_identity(base_name, name_style, greeting_style, trait_dict)
    state_update = _apply_to_state(interface_state, compiled["name"], compiled["context"], compiled["greeting"], apply_name, apply_greeting)

    logger.info("[sasha_identity] Applied compiled identity to Character fields.")

    return (
        compiled["summary"],
        compiled["context"],
        compiled["greeting"],
        compiled["name"],
        compiled["name"] if apply_name else gr.update(),
        compiled["context"],
        compiled["greeting"] if apply_greeting else gr.update(),
        state_update,
    )


def _reset_defaults():
    return [TRAIT_DEFAULTS[key] for key in TRAIT_KEYS]


def _load_preset(name: str):
    values = TRAIT_DEFAULTS.copy()
    if name and name.startswith("Built-in: "):
        values.update(PRESETS.get(name.replace("Built-in: ", ""), {}))
    elif name and name.startswith("Custom: "):
        preset_name = name.replace("Custom: ", "")
        path = _preset_dir() / f"{preset_name}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in TRAIT_KEYS:
                if key in data:
                    values[key] = _clamp(data[key])

    return [values[key] for key in TRAIT_KEYS]


def _save_custom_preset(name: str, *trait_values):
    clean = (name or "").strip()
    if not clean:
        return gr.update(), "Preset name is empty."

    payload = _build_trait_dict(list(trait_values))
    with open(_preset_dir() / f"{clean}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    return gr.update(choices=_preset_choices(), value=f"Custom: {clean}"), f"Saved preset: {clean}"


def _delete_custom_preset(name: str):
    if not name or not name.startswith("Custom: "):
        return gr.update(choices=_preset_choices()), "Select a custom preset to delete."

    preset_name = name.replace("Custom: ", "")
    path = _preset_dir() / f"{preset_name}.json"
    if path.exists():
        path.unlink()

    return gr.update(choices=_preset_choices(), value=None), f"Deleted preset: {preset_name}"


def ui():
    with gr.Column():
        gr.Markdown(
            "### Sasha Identity Engine\n"
            "Deterministic identity compiler for TGWUI Character fields (name/context/greeting)."
        )

        with gr.Row():
            base_name = gr.Textbox(label="Base Name", value=GENERAL_DEFAULTS["base_name"], lines=1)
            name_style = gr.Dropdown(label="Generated Name Style", choices=NAME_STYLE_OPTIONS, value=GENERAL_DEFAULTS["name_style"])
            greeting_style = gr.Dropdown(label="Greeting Style", choices=GREETING_STYLE_OPTIONS, value=GENERAL_DEFAULTS["greeting_style"])

        with gr.Row():
            apply_name = gr.Checkbox(label="Apply generated name to Character tab", value=GENERAL_DEFAULTS["apply_name"])
            apply_greeting = gr.Checkbox(label="Apply generated greeting to Character tab", value=GENERAL_DEFAULTS["apply_greeting"])
            auto_apply = gr.Checkbox(label="Auto-apply on Regenerate", value=GENERAL_DEFAULTS["auto_apply"])
            live_preview = gr.Checkbox(label="Live preview on slider release", value=GENERAL_DEFAULTS["live_preview"])

        with gr.Row():
            preset_dropdown = gr.Dropdown(label="Preset", choices=_preset_choices(), value=None)
            preset_name = gr.Textbox(label="Custom preset name", lines=1, placeholder="e.g. My Ops Profile")

        with gr.Row():
            load_preset_btn = gr.Button("Load Preset")
            save_preset_btn = gr.Button("Save as Custom Preset")
            delete_preset_btn = gr.Button("Delete Custom Preset")
            reset_btn = gr.Button("Reset Traits to Defaults")

        preset_status = gr.Markdown(value="")

        trait_controls = []
        for group in TRAIT_GROUPS:
            with gr.Accordion(group["label"], open=False):
                for trait in group["traits"]:
                    slider = gr.Slider(
                        label=f"{trait['label']} ({trait['key']})",
                        value=trait["default"],
                        minimum=trait["min"],
                        maximum=trait["max"],
                        step=trait["step"],
                        info=trait["description"],
                    )
                    trait_controls.append(slider)

        with gr.Row():
            regenerate_btn = gr.Button("Regenerate Preview", variant="secondary")
            apply_btn = gr.Button("Apply to Character fields", variant="primary")

        summary_preview = gr.Textbox(label="One-line Identity Summary", lines=2, interactive=False)
        name_preview = gr.Textbox(label="Generated Name Preview", lines=1, interactive=False)
        greeting_preview = gr.Textbox(label="Generated Greeting Preview", lines=4, interactive=False)
        context_preview = gr.Textbox(label="Compiled Context Preview", lines=22, interactive=False)

    common_inputs = [
        shared.gradio["interface_state"],
        base_name,
        name_style,
        greeting_style,
        apply_name,
        apply_greeting,
    ] + trait_controls

    apply_outputs = [
        summary_preview,
        context_preview,
        greeting_preview,
        name_preview,
        shared.gradio["name2"],
        shared.gradio["context"],
        shared.gradio["greeting"],
        shared.gradio["interface_state"],
    ]

    regenerate_inputs = [
        shared.gradio["interface_state"],
        base_name,
        name_style,
        greeting_style,
        apply_name,
        apply_greeting,
        auto_apply,
    ] + trait_controls

    regenerate_btn.click(_regenerate, regenerate_inputs, apply_outputs, show_progress=False)
    apply_btn.click(_apply_identity, common_inputs, apply_outputs, show_progress=False)

    for ctl in trait_controls:
        ctl.release(
            _live_regenerate,
            [live_preview] + regenerate_inputs,
            apply_outputs,
            show_progress=False,
            queue=False,
        )

    live_preview.change(
        lambda enabled: "Live preview enabled." if enabled else "Live preview disabled.",
        live_preview,
        preset_status,
        show_progress=False,
    )

    reset_btn.click(lambda: _reset_defaults(), None, trait_controls, show_progress=False)
    load_preset_btn.click(_load_preset, preset_dropdown, trait_controls, show_progress=False)
    save_preset_btn.click(_save_custom_preset, [preset_name] + trait_controls, [preset_dropdown, preset_status], show_progress=False)
    delete_preset_btn.click(_delete_custom_preset, preset_dropdown, [preset_dropdown, preset_status], show_progress=False)