"""Pure, explainable action classification. No dispatch or ledger authority.

Lexical matches nominate risk. Action capability, configured effect metadata,
and observed context corroborate decisions. A focus action never activates its
target; target activation signals are retained without misclassifying focus.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Mapping

from tb_runner.canonical_json import canonical_json, canonical_sha256
from tb_runner.utils import parse_bounds_str
from tb_runner.traversal_reliability import normalized_bounds

CLASSES = ("SAFE", "CONDITIONALLY_SAFE", "RISKY", "FORBIDDEN", "UNKNOWN")
ACTION_TYPES = ("FOCUS", "CLICK", "LONG_CLICK", "SCROLL_FORWARD", "SCROLL_BACKWARD",
    "BACK", "OPEN_MENU", "SELECT_TAB", "EXPAND", "COLLAPSE", "TOGGLE", "CHECK", "UNCHECK",
    "TEXT_INPUT", "SUBMIT", "CONFIRM", "DISMISS", "NAVIGATE", "EXTERNAL_INTENT", "UNKNOWN_ACTION")
DIMENSIONS = ("REVERSIBILITY", "STATE_MUTATION", "EXTERNAL_EFFECT", "DESTRUCTIVENESS",
    "PHYSICAL_DEVICE_EFFECT", "ACCOUNT_SECURITY_EFFECT", "PAYMENT_COMMERCE_EFFECT",
    "PRIVACY_EFFECT", "NAVIGATION_SCOPE", "RECOVERY_CONFIDENCE", "SEMANTIC_CERTAINTY")
ALIASES = {"FOCUS_TARGET": "FOCUS", "FOCUS_CANDIDATE": "FOCUS", "BOTTOM_NAV": "SELECT_TAB",
    "SCROLL_FORWARD_VERTICAL": "SCROLL_FORWARD", "SCROLL_BACKWARD_VERTICAL": "SCROLL_BACKWARD",
    "SCROLL_FORWARD_HORIZONTAL": "SCROLL_FORWARD", "SCROLL_BACKWARD_HORIZONTAL": "SCROLL_BACKWARD",
    "PLUGIN_NAVIGATION": "NAVIGATE", "CANCEL": "DISMISS"}
RISK_EFFECTS = {"delete": "DESTRUCTIVE", "remove": "DESTRUCTIVE", "reset": "DESTRUCTIVE",
    "account_mutation": "ACCOUNT", "payment": "PAYMENT", "external_send": "EXTERNAL_COMMUNICATION",
    "physical_control": "PHYSICAL_DEVICE", "privacy_mutation": "PRIVACY_SECURITY",
    "setting_mutation": "MUTATING_SETTING", "external_intent": "EXTERNAL_COMMUNICATION"}
READ_ONLY_EFFECTS = {"read_only", "read_only_navigation", "read_only_expansion", "ui_filter"}


@lru_cache(maxsize=1)
def default_config():
    return json.loads((Path(__file__).resolve().parents[1] / "config/safe_action_policy.json").read_text(encoding="utf-8"))


def normalize_action(action):
    value = str(action or "").upper()
    return ALIASES.get(value, value if value in ACTION_TYPES else "UNKNOWN_ACTION")


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").lower().replace("_", " ").replace("-", " ")).strip()


def matches(text, words):
    text = normalize_text(text)
    return sorted({word for word in words if (normalize_text(word) in text if re.search(r"[가-힣]", word)
        else re.search(r"(?<!\w)" + re.escape(normalize_text(word)) + r"(?!\w)", text))})


@dataclass(frozen=True)
class ActionClassification:
    _json: str

    def to_dict(self):
        return json.loads(self._json)


def configured_metadata(candidate, context, config):
    """Only explicit configuration is an effect authority; node hints are not."""
    target, semantic = candidate.get("target_identity", {}), candidate.get("target_semantics", {})
    result = {}
    for rule in config.get("metadata_rules", []):
        selectors = rule.get("match", {})
        observed = {"resource_id": target.get("resource_id", ""), "class_name": target.get("class_name", ""),
                    "role": semantic.get("role", ""), "context_kind": context.get("context_kind", "")}
        # Empty rules or scenario IDs cannot silently certify all controls.
        if not selectors or set(selectors) - set(observed):
            raise ValueError("Metadata rules require generic target/context selectors")
        if all(re.fullmatch(pattern, str(observed[key])) for key, pattern in selectors.items()):
            effect = rule.get("effect")
            if result and result.get("effect") != effect:
                return {"source": "CONFIGURED", "effect": "conflicting_effects"}
            result = {**rule, "source": "CONFIGURED", "effect": effect}
    return result


def classify_action(candidate: Mapping, *, action_type=None, context=None, metadata=None, config=None):
    config = config if config is not None else default_config()
    context = context or {}
    target, semantic = candidate.get("target_identity", {}), candidate.get("target_semantics", {})
    evidence, flags = candidate.get("evidence", {}), semantic.get("flags", {})
    action = normalize_action(action_type or candidate.get("action_kind"))
    if action == "CLICK" and (flags.get("checkable") is True or any(
            word in str(semantic.get("role", "")).lower() + str(target.get("class_name", "")).lower()
            for word in ("switch", "checkbox", "toggle"))):
        action = "TOGGLE"
    metadata = metadata if metadata is not None else configured_metadata(candidate, context, config)
    trusted = metadata.get("source") == "CONFIGURED"
    effect = metadata.get("effect", "") if trusted else ""
    label = " ".join(str(semantic.get(k) or "") for k in ("normalized_label", "text", "contentDescription", "talkbackLabel"))
    text = normalize_text(label + " " + str(target.get("resource_id") or ""))
    lexical = {key: matches(text, words) for key, words in config.get("lexicon", {}).items()}
    lexical = {key: words for key, words in lexical.items() if words}
    surrounding = normalize_text(" ".join(context.get("surrounding_labels", [])))
    physical_context = context.get("physical_context") is True or bool(matches(surrounding, config.get("physical_context", [])))
    if physical_context and matches(text, config.get("physical_commands", [])):
        lexical["PHYSICAL_DEVICE"] = sorted(set(lexical.get("PHYSICAL_DEVICE", []) + matches(text, config["physical_commands"])))
    bounds = parse_bounds_str(normalized_bounds(target.get("bounds", "")))
    geometry = bool(bounds and bounds[0] < bounds[2] and bounds[1] < bounds[3])
    present = evidence.get("current_presence") is True or (candidate.get("action_kind", "").startswith("SCROLL_")
        and evidence.get("axis_contract") == "axis-v1" and bool(evidence.get("supporting_signals")))
    enabled = flags.get("enabled") is not False and candidate.get("eligibility", {}).get("availability") not in {"DISABLED", "UNAVAILABLE"}
    actions = {v.get("id") if isinstance(v, dict) else v for v in semantic.get("actions", [])}
    actionable = flags.get("clickable") is True or 16 in actions
    signals = ["LEXICAL_CANDIDATE:" + category + ":" + word for category, words in lexical.items() for word in words]
    if present: signals.append("CURRENT_TARGET_OBSERVED")
    if actionable: signals.append("ACTIVATION_CAPABILITY_OBSERVED")
    if physical_context: signals.append("PHYSICAL_CONTEXT_CORROBORATED")
    if trusted: signals.append("CONFIGURED_EFFECT:" + str(effect))
    dimensions = dict.fromkeys(DIMENSIONS, "UNKNOWN")
    identity = {"schema": "action-safety-identity-v1", "action_type": action,
        "target_identity": target.get("instance_id") or canonical_json(target),
        "state_id": candidate.get("state_id") or context.get("state_id"),
        "destination": context.get("destination"), "substate": context.get("substate", [])}

    def result(kind, confidence, reason, required=(), risk_categories=()):
        dimensions["SEMANTIC_CERTAINTY"] = confidence
        return ActionClassification(canonical_json(dict(schema="action-safety-classification-v1",
            action_id="safe-action:" + canonical_sha256(identity), action_identity=identity,
            candidate_id=candidate.get("candidate_id"), action_type=action, target_identity=dict(target),
            target_role=semantic.get("role"), target_label=label.strip(),
            safety_class=kind, confidence=confidence, signals=sorted(set(signals)), reason=reason,
            required_conditions=list(required), risk_categories=sorted(set(risk_categories)),
            activation_risk_candidates=sorted(lexical), risk_dimensions=dimensions,
            action_executed=False, attempt_credit=0, visit_credit=0)))

    if not present or not geometry or not enabled or not target:
        return result("UNKNOWN", "LOW", "TARGET_EVIDENCE_INSUFFICIENT")
    if metadata.get("forbidden") is True and trusted:
        return result("FORBIDDEN", "HIGH", "CONFIGURED_AUTOMATION_PROHIBITED")
    if action == "FOCUS":
        if flags.get("focusable") is not True:
            return result("UNKNOWN", "LOW", "FOCUS_CAPABILITY_UNPROVEN")
        dimensions.update(REVERSIBILITY="REVERSIBLE", STATE_MUTATION="NONE", EXTERNAL_EFFECT="NONE",
            DESTRUCTIVENESS="NONE", PHYSICAL_DEVICE_EFFECT="NONE", ACCOUNT_SECURITY_EFFECT="NONE",
            PAYMENT_COMMERCE_EFFECT="NONE", PRIVACY_EFFECT="NONE", NAVIGATION_SCOPE="CURRENT_VIEWPORT")
        signals.append("FOCUS_DOES_NOT_ACTIVATE_TARGET")
        return result("SAFE", "HIGH", "READ_ONLY_ACCESSIBILITY_FOCUS")
    if action in {"SCROLL_FORWARD", "SCROLL_BACKWARD"}:
        if effect in RISK_EFFECTS or any(word in str(semantic.get("role", "")).lower()
                + str(target.get("class_name", "")).lower() for word in ("seekbar", "slider", "range")):
            dimensions["STATE_MUTATION"] = "YES"
            return result("RISKY", "HIGH", "SCROLL_ADJUSTMENT_NOT_VIEWPORT_ONLY",
                          risk_categories=(RISK_EFFECTS.get(effect, "MUTATING_SETTING"),))
        if evidence.get("axis_contract") != "axis-v1" or not evidence.get("supporting_signals"):
            return result("UNKNOWN", "LOW", "SCROLL_EFFECT_UNPROVEN")
        dimensions.update(REVERSIBILITY="REVERSIBLE", STATE_MUTATION="VIEWPORT_ONLY", EXTERNAL_EFFECT="NONE",
                          PHYSICAL_DEVICE_EFFECT="NONE", NAVIGATION_SCOPE="CURRENT_CONTAINER")
        return result("CONDITIONALLY_SAFE", "HIGH", "BOUNDED_VIEWPORT_SCROLL",
                      ("current_target", "scroll_container_verified", "within_app"))
    if effect == "conflicting_effects":
        return result("UNKNOWN", "LOW", "CONFLICTING_CONFIGURED_EFFECTS")
    if action == "UNKNOWN_ACTION":
        return result("UNKNOWN", "LOW", "UNKNOWN_ACTION_SEMANTICS")
    inherited = set(context.get("confirmation_risks", [])) if context.get("confirmation_verified") is True else set()
    own_risk = {RISK_EFFECTS[effect]} if effect in RISK_EFFECTS else set()
    # A verified cancellation is separate from a risky confirmation. A strong
    # target mutation effect always wins; merely naming a dialog Cancel cannot.
    cancellation = action == "DISMISS" or bool(matches(label, config.get("cancel_signals", [])))
    if actionable and cancellation and not own_risk and (effect in {"cancel", "informational_dismiss"}
            or context.get("confirmation_verified") is True):
        dimensions.update(REVERSIBILITY="REVERSIBLE", STATE_MUTATION="NONE", EXTERNAL_EFFECT="NONE")
        return result("CONDITIONALLY_SAFE", "HIGH", "VERIFIED_NON_COMMITTING_DISMISSAL",
                      ("current_target", "modal_verified", "cancellation_only", "within_app"))
    if actionable and inherited:
        dimensions["STATE_MUTATION"] = "INHERITED_CONFIRMATION_EFFECT"
        signals.append("VERIFIED_CONFIRMATION_CHAIN")
        return result("FORBIDDEN" if "DESTRUCTIVE" in inherited else "RISKY", "HIGH",
                      "CONFIRMATION_INHERITS_RISK", risk_categories=inherited | own_risk)
    if action == "EXTERNAL_INTENT": own_risk.add("EXTERNAL_COMMUNICATION")
    if own_risk:
        dimensions["STATE_MUTATION"] = "YES"
        for category, dim in {"DESTRUCTIVE":"DESTRUCTIVENESS", "ACCOUNT":"ACCOUNT_SECURITY_EFFECT",
            "PAYMENT":"PAYMENT_COMMERCE_EFFECT", "PHYSICAL_DEVICE":"PHYSICAL_DEVICE_EFFECT",
            "PRIVACY_SECURITY":"PRIVACY_EFFECT", "EXTERNAL_COMMUNICATION":"EXTERNAL_EFFECT"}.items():
            if category in own_risk: dimensions[dim] = "YES"
        forbidden = metadata.get("irreversible") is True or action == "EXTERNAL_INTENT" and metadata.get("forbidden") is True
        return result("FORBIDDEN" if forbidden else "RISKY", "HIGH", "CONFIGURED_OR_EXPLICIT_RISK_EFFECT", risk_categories=own_risk)
    if effect in READ_ONLY_EFFECTS and actionable and action in {"CLICK", "OPEN_MENU", "SELECT_TAB", "EXPAND", "COLLAPSE", "NAVIGATE"}:
        dimensions.update(REVERSIBILITY="REVERSIBLE", STATE_MUTATION="UI_ONLY", EXTERNAL_EFFECT="NONE",
                          PHYSICAL_DEVICE_EFFECT="NONE", NAVIGATION_SCOPE="WITHIN_APP")
        signals.append("LEXICAL_CANDIDATES_DISAMBIGUATED_BY_CONFIGURED_READ_ONLY_EFFECT")
        return result("CONDITIONALLY_SAFE", "HIGH", "CORROBORATED_READ_ONLY_UI",
                      ("current_target", "within_app", "read_only_effect", "recovery_verified"))
    if actionable and lexical:
        dimensions["STATE_MUTATION"] = "POSSIBLE"
        return result("RISKY", "MEDIUM", "LEXICAL_RISK_CORROBORATED_BY_ACTIVATION_CAPABILITY", risk_categories=lexical)
    if action in {"TOGGLE", "CHECK", "UNCHECK", "TEXT_INPUT"} and (
            actionable or flags.get("checkable") is True or flags.get("editable") is True):
        dimensions["STATE_MUTATION"] = "YES"
        return result("RISKY", "HIGH", "STATE_MUTATION_WITHOUT_READ_ONLY_CONTRACT", risk_categories=("MUTATING_SETTING",))
    if action == "SELECT_TAB" and candidate.get("action_kind") == "BOTTOM_NAV" and "GLOBAL_NAV" in candidate.get("source", []):
        dimensions.update(STATE_MUTATION="UI_ONLY", NAVIGATION_SCOPE="WITHIN_APP", REVERSIBILITY="REVERSIBLE")
        return result("CONDITIONALLY_SAFE", "HIGH", "OBSERVED_APPLICATION_TAB",
                      ("current_target", "within_app", "recovery_verified"))
    return result("UNKNOWN", "LOW", "ACTIVATION_EFFECT_UNPROVEN")
