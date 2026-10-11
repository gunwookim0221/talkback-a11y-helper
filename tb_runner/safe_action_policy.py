"""Phase 5A policy: eligibility only, never execution or visit authority."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyPolicyDecision:
    eligible: bool
    reason: str
    missing_conditions: tuple = ()

    def to_dict(self):
        return dict(eligible=self.eligible, reason=self.reason, missing_conditions=list(self.missing_conditions),
                    phase4_gate_required=True, action_executed=False, attempt_credit=0, visit_credit=0)


def evaluate_policy(classification, conditions=None):
    value = classification.to_dict() if hasattr(classification, "to_dict") else classification
    conditions = conditions or {}
    kind = value.get("safety_class")
    if kind not in {"SAFE", "CONDITIONALLY_SAFE"}:
        return SafetyPolicyDecision(False, "BLOCK_" + str(kind or "UNKNOWN"))
    if value.get("confidence") not in {"HIGH", "MEDIUM"}:
        return SafetyPolicyDecision(False, "LOW_OR_UNKNOWN_CONFIDENCE")
    missing = tuple(key for key in value.get("required_conditions", []) if conditions.get(key) is not True)
    if kind == "CONDITIONALLY_SAFE" and not value.get("required_conditions"):
        return SafetyPolicyDecision(False, "CONDITIONAL_CONTRACT_MISSING")
    if missing:
        return SafetyPolicyDecision(False, "CONDITIONS_UNPROVEN", missing)
    return SafetyPolicyDecision(True, "ELIGIBLE_FOR_PHASE4_GATE")
