from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from tb_runner.action_safety import classify_action, normalize_action, ACTION_TYPES, default_config
from tb_runner.safe_action_policy import evaluate_policy
from tb_runner.phase5a_safety import SafetySession
from tb_runner.phase4a_planner import plan_shadow
from tb_runner.phase4b_authority import AuthorityDecision
from tb_runner.traversal_reliability import instance_id
from tb_runner.action_provenance import build_action_chain, action_chain_failures
from test_phase4b_authority import value, gate
from test_phase4c_action_provenance import food


def candidate(label="Information", action="CLICK", **flags):
    target = dict(resource_id="app:id/control", class_name="Button", bounds="0,0,100,100")
    target["instance_id"] = instance_id(dict(scenario_id="test", view_id=target["resource_id"], bounds=target["bounds"]))
    return dict(candidate_id="discovery:existing", state_id="state:existing", action_kind=action,
        target_identity=target, target_semantics=dict(normalized_label=label, role="button",
            flags=dict(enabled=True, clickable=True, focusable=True, **flags)),
        eligibility=dict(availability="AVAILABLE"), evidence=dict(current_presence=True), source=[])


def meta(effect, **kwargs):
    return dict(source="CONFIGURED", effect=effect, **kwargs)


@pytest.mark.parametrize("action", ACTION_TYPES)
def test_normalized_action_inventory(action):
    assert normalize_action(action) == action


@pytest.mark.parametrize("label", ["Delete", "삭제", "Unlock door", "전원 끄기", "Payment", "결제", "", "Start"])
def test_read_only_focus_on_any_control_is_not_activation(label):
    c = candidate(label, "FOCUS_TARGET")
    before = deepcopy(c)
    result = classify_action(c).to_dict()
    assert result["safety_class"] == "SAFE" and result["confidence"] == "HIGH"
    assert evaluate_policy(result).eligible
    assert "FOCUS_DOES_NOT_ACTIVATE_TARGET" in result["signals"]
    assert result["visit_credit"] == result["attempt_credit"] == 0 and c == before


RISK_CASES = [
    ("Delete", "delete"), ("삭제", "delete"), ("Remove", "remove"), ("제거", "remove"),
    ("Sign out", "account_mutation"), ("로그아웃", "account_mutation"),
    ("Purchase", "payment"), ("결제", "payment"), ("Send", "external_send"), ("공유", "external_send"),
    ("Power off", "physical_control"), ("전원 켜기", "physical_control"),
    ("Unlock door", "physical_control"), ("잠금 해제", "physical_control"),
    ("Start", "physical_control"), ("세탁 시작", "physical_control"),
    ("Privacy", "privacy_mutation"), ("보안 설정", "privacy_mutation")]


@pytest.mark.parametrize("label,effect", RISK_CASES)
def test_known_risk_never_safe(label, effect):
    result = classify_action(candidate(label), metadata=meta(effect))
    assert result.to_dict()["safety_class"] in {"RISKY", "FORBIDDEN"}
    assert not evaluate_policy(result).eligible


@pytest.mark.parametrize("label", ["Delete", "삭제", "Remove", "Reset", "Sign out", "결제", "Send", "Share", "비밀번호"])
def test_lexical_risk_needs_observed_activation_capability(label):
    c = candidate(label)
    assert classify_action(c).to_dict()["safety_class"] == "RISKY"
    c["target_semantics"]["flags"]["clickable"] = False
    assert classify_action(c).to_dict()["safety_class"] == "UNKNOWN"


@pytest.mark.parametrize("label", ["", "OK", "Next", "확인", "다음", "⋮", "Custom control"])
def test_ambiguous_activation_is_unknown(label):
    result = classify_action(candidate(label))
    assert result.to_dict()["safety_class"] == "UNKNOWN"
    assert not evaluate_policy(result).eligible


@pytest.mark.parametrize("label,effect", [("Power usage", "read_only_navigation"),
    ("전력 사용량", "read_only_navigation"), ("Payment history", "read_only_navigation"),
    ("결제 내역", "read_only_navigation"), ("Remove filter", "ui_filter"), ("필터 제거", "ui_filter")])
def test_benign_lexical_matches_need_corroborated_information_context(label, effect):
    result = classify_action(candidate(label), metadata=meta(effect))
    assert result.to_dict()["safety_class"] == "CONDITIONALLY_SAFE"
    assert not evaluate_policy(result).eligible
    assert evaluate_policy(result, dict(current_target=True, within_app=True, read_only_effect=True, recovery_verified=True)).eligible


@pytest.mark.parametrize("action,effect", [("EXPAND", "read_only_expansion"), ("COLLAPSE", "read_only_expansion"),
    ("OPEN_MENU", "read_only_navigation"), ("SELECT_TAB", "read_only_navigation"), ("NAVIGATE", "read_only_navigation")])
def test_read_only_navigation_requires_independent_recovery_evidence(action, effect):
    result = classify_action(candidate("Information", action), metadata=meta(effect))
    conditions = dict(current_target=True, within_app=True, read_only_effect=True, recovery_verified=False)
    assert not evaluate_policy(result, conditions).eligible
    conditions["recovery_verified"] = True
    assert evaluate_policy(result, conditions).eligible


@pytest.mark.parametrize("label", ["Start", "시작"])
def test_same_label_tutorial_vs_physical_context(label):
    c = candidate(label)
    tutorial = classify_action(c, metadata=meta("read_only_navigation"))
    appliance = classify_action(c, context=dict(surrounding_labels=["Washing machine", "세탁기"]))
    assert tutorial.to_dict()["safety_class"] == "CONDITIONALLY_SAFE"
    assert appliance.to_dict()["safety_class"] == "RISKY"
    assert "PHYSICAL_DEVICE" in appliance.to_dict()["risk_categories"]


@pytest.mark.parametrize("label", ["Cancel", "취소", "Close", "닫기"])
def test_cancel_high_risk_confirmation_is_separate_from_commit(label):
    context = dict(confirmation_verified=True, confirmation_risks=["DESTRUCTIVE"])
    result = classify_action(candidate(label), context=context, metadata=meta("cancel"))
    assert result.to_dict()["safety_class"] == "CONDITIONALLY_SAFE"
    conditions = dict(current_target=True, within_app=True, modal_verified=True, cancellation_only=True)
    assert evaluate_policy(result, conditions).eligible
    conditions["cancellation_only"] = False
    assert not evaluate_policy(result, conditions).eligible


@pytest.mark.parametrize("label", ["Confirm", "Delete", "OK", "확인", "예"])
def test_generic_confirmation_inherits_destructive_risk(label):
    result = classify_action(candidate(label), context=dict(confirmation_verified=True, confirmation_risks=["DESTRUCTIVE"]))
    assert result.to_dict()["safety_class"] == "FORBIDDEN" and not evaluate_policy(result).eligible


def test_explicit_risk_overrides_safe_dismiss_and_read_only_candidate():
    assert classify_action(candidate("Cancel", "DISMISS"), metadata=meta("payment")).to_dict()["safety_class"] == "RISKY"
    assert classify_action(candidate("Info", "FOCUS"), metadata=meta("read_only", forbidden=True)).to_dict()["safety_class"] == "FORBIDDEN"
    assert classify_action(candidate("Info"), metadata=meta("delete", irreversible=True)).to_dict()["safety_class"] == "FORBIDDEN"
    assert classify_action(candidate("Confirm"), metadata=meta("read_only"), context=dict(
        confirmation_verified=True, confirmation_risks=["PAYMENT"])).to_dict()["safety_class"] == "RISKY"


@pytest.mark.parametrize("role", ["switch", "checkbox", "toggle"])
def test_setting_toggles_are_not_safe_clicks(role):
    c = candidate("Setting")
    c["target_semantics"]["role"] = role
    result = classify_action(c, metadata=meta("read_only_navigation")).to_dict()
    assert result["action_type"] == "TOGGLE" and result["safety_class"] == "RISKY"


@pytest.mark.parametrize("action", ["LONG_CLICK", "BACK", "TEXT_INPUT", "UNKNOWN_ACTION"])
def test_unimplemented_effects_not_silently_safe(action):
    assert not evaluate_policy(classify_action(candidate("Information", action))).eligible


def test_external_intent_is_blocked_without_lexical_help():
    assert classify_action(candidate("Open", "EXTERNAL_INTENT")).to_dict()["safety_class"] == "RISKY"


@pytest.mark.parametrize("action", ["SCROLL_FORWARD_VERTICAL", "SCROLL_BACKWARD_VERTICAL"])
def test_axis_scroll_is_conditional_and_control_adjustment_is_risky(action):
    c = candidate("", action)
    c["evidence"].update(axis_contract="axis-v1", supporting_signals=["directional_action"])
    result = classify_action(c)
    assert result.to_dict()["safety_class"] == "CONDITIONALLY_SAFE"
    assert evaluate_policy(result, dict(current_target=True, scroll_container_verified=True, within_app=True)).eligible
    c["target_semantics"]["role"] = "slider"
    assert classify_action(c).to_dict()["safety_class"] == "RISKY"


def test_untrusted_node_metadata_cannot_authorize_information_click():
    c = candidate("Information")
    c["metadata"] = meta("read_only")
    assert classify_action(c).to_dict()["safety_class"] == "UNKNOWN"
    assert classify_action(c, metadata=dict(effect="read_only", source="NODE_HINT")).to_dict()["safety_class"] == "UNKNOWN"


@pytest.mark.parametrize("change", ["absent", "disabled", "no_geometry", "not_focusable"])
def test_missing_target_evidence_fails_closed(change):
    c = candidate("", "FOCUS")
    if change == "absent": c["evidence"]["current_presence"] = False
    if change == "disabled": c["target_semantics"]["flags"]["enabled"] = False
    if change == "no_geometry": c["target_identity"]["bounds"] = ""
    if change == "not_focusable": c["target_semantics"]["flags"]["focusable"] = False
    assert not evaluate_policy(classify_action(c)).eligible


def test_identity_reuses_existing_instance_not_dynamic_text_or_randomness():
    c = candidate("Before", "FOCUS")
    first = classify_action(c).to_dict()
    c["target_semantics"]["normalized_label"] = "After"
    assert classify_action(c).to_dict()["action_id"] == first["action_id"]
    assert first["action_identity"]["target_identity"] == c["target_identity"]["instance_id"]
    assert classify_action(c, action_type="CLICK").to_dict()["action_id"] != first["action_id"]
    assert classify_action(c, context=dict(destination="other")).to_dict()["action_id"] != first["action_id"]


@pytest.mark.parametrize("kind", ["RISKY", "FORBIDDEN", "UNKNOWN"])
def test_policy_never_promotes_risk_even_with_all_conditions(kind):
    assert not evaluate_policy(dict(safety_class=kind, confidence="HIGH"), dict(current_target=True)).eligible


def test_low_confidence_safe_and_truthy_conditions_cannot_authorize():
    assert not evaluate_policy(dict(safety_class="SAFE", confidence="LOW")).eligible
    assert not evaluate_policy(dict(safety_class="CONDITIONALLY_SAFE", confidence="HIGH", required_conditions=["proof"]), {"proof":1}).eligible
    assert not evaluate_policy(dict(safety_class="CONDITIONALLY_SAFE", confidence="HIGH", required_conditions=[])).eligible


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_phase4_exact_history_and_recommendation_when_off_or_shadow(mode):
    v, raw = value()
    before = deepcopy(v)
    prepared, report = SafetySession(mode).prepare(v, raw)
    assert prepared is v and v == before and plan_shadow(prepared) == plan_shadow(v)
    if mode == "shadow": assert report["visit_credit"] == report["attempt_credit"] == 0
    else: assert report is None


def test_enforcement_skips_forbidden_target_preserves_order_and_history():
    v, raw = value()
    from state_model_fixtures import node
    from tb_runner.discovery_candidates import build_discovery_snapshot
    from tb_runner.state_registry import StateRegistry
    raw["nodes"].append(node("id.c", "C", "0,340,500,440"))
    v = replace(v, snapshot=build_discovery_snapshot(raw, StateRegistry("safety-next")))
    first = plan_shadow(v).to_dict()["recommended_target"]["resource_id"]
    config = deepcopy(default_config())
    config["metadata_rules"] = [dict(match=dict(resource_id=first), effect="read_only", forbidden=True)]
    session = SafetySession("enforce", config)
    for _ in range(5):
        filtered, report = session.prepare(v, raw)
        assert plan_shadow(filtered).to_dict()["recommended_target"]["resource_id"] != first
        assert v.history.attempts == filtered.history.attempts == ()
        assert v.history.visits == filtered.history.visits == ()
        assert report["safety_blocked_candidates"]
    assert session.blocked_candidates and v.history.allowed_instance_ids is None


def test_all_focus_blocked_prefers_valid_scroll_otherwise_fallback():
    v, raw = value(scroll=True)
    container = raw["capability"]["containers"][0]
    raw["capability"].update(container=container, can_scroll_forward=True)
    raw.update(package_name="app", activity_name="app.Main", context_source="window_current_focus")
    config = deepcopy(default_config())
    config["metadata_rules"] = [dict(match=dict(resource_id="id.*"), effect="read_only", forbidden=True)]
    filtered, report = SafetySession("enforce", config).prepare(v, raw)
    assert plan_shadow(filtered).to_dict()["recommended_action"] == "SCROLL_FORWARD"
    raw["capability"]["can_scroll_forward"] = False
    filtered, report = SafetySession("enforce", config).prepare(v, raw)
    assert plan_shadow(filtered).to_dict()["recommended_action"] == "RECOVERY_OR_NONE"
    assert not filtered.history.visits and not filtered.history.attempts


def test_fresh_safety_guard_never_overrides_phase4_denial():
    v, raw = value()
    session = SafetySession("enforce")
    _, report = session.prepare(v, raw)
    denial = AuthorityDecision(False, "FALLBACK_PRODUCTION", "STALE_REQUEST_RESULT")
    assert session.guard(v, raw, plan_shadow(v), denial, report) is denial
    _, report = session.prepare(v, raw)
    assert session.guard(v, raw, plan_shadow(v), gate(v), report).allowed
    config = deepcopy(default_config())
    config["metadata_rules"] = [dict(match=dict(resource_id="id.*"), effect="read_only", forbidden=True)]
    session = SafetySession("enforce", config)
    _, report = session.prepare(v, raw)
    assert not session.guard(v, raw, plan_shadow(v), gate(v), report).allowed


def test_metadata_cannot_key_on_scenario_id_or_conflict_to_safe():
    config = deepcopy(default_config())
    config["metadata_rules"] = [dict(match=dict(scenario_id="device_camera_plugin"), effect="read_only")]
    with pytest.raises(ValueError): classify_action(candidate(), config=config)
    config["metadata_rules"] = [dict(match=dict(resource_id=".*"), effect=effect) for effect in ["read_only", "physical_control"]]
    assert classify_action(candidate(), config=config).to_dict()["safety_class"] == "UNKNOWN"


def test_safety_provenance_attaches_to_original_chain_and_detects_foreign_step():
    f = food(); audit = f["audit"]
    baseline = build_action_chain(audit, audit["production_row"], f["events"])
    audit["action_safety"] = dict(schema="phase5a-safety-step-v1", scenario=audit["scenario"], step=audit["step"],
        mode="shadow", selected=dict(policy=dict(eligible=False)), final_outcome=dict(planner_executed=True))
    chain = build_action_chain(audit, audit["production_row"], f["events"])
    assert {k:v for k,v in chain.items() if k != "action_safety"} == baseline
    assert not action_chain_failures(chain, audit)
    chain["action_safety"]["evidence"]["step"] += 1
    assert "SAFETY_EVIDENCE_OWNERSHIP_MISMATCH" in action_chain_failures(chain, audit)


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_generalized_adapter_emits_safety_chain_and_restores_hooks(mode, tmp_path, monkeypatch):
    from test_phase4c_traversal import test_generalized_harness_runs_refresh_and_restores_hooks as run_harness
    monkeypatch.setenv("TB_PHASE5A_ACTION_SAFETY_MODE", mode)
    run_harness(tmp_path, monkeypatch, False)
    row = json.loads((tmp_path/"phase4c_execution_trace.jsonl").read_text())
    assert row["action_safety"]["mode"] == mode
    assert row["action_audit_chain"]["action_safety"]["evidence"] == row["action_safety"]


def test_defaults_off_and_invalid_mode_before_device(monkeypatch):
    from tools import phase4b_controlled_smoke as harness
    monkeypatch.setenv("TB_PHASE5A_ACTION_SAFETY_MODE", "unsafe")
    monkeypatch.setattr(harness, "A11yAdbClient", lambda **kw: pytest.fail("No device I/O allowed"))
    with pytest.raises(ValueError): harness.main(generalized=True)
    assert default_config()["default_mode"] == "off"


@pytest.mark.parametrize("case", json.loads((Path(__file__).parent/"fixtures/phase5a_safe_actions.json").read_text(encoding="utf-8"))["cases"], ids=lambda c:c["id"])
def test_independently_labelled_multilingual_and_plugin_cases(case):
    from tools.phase5a_safety_shadow import fixture_input
    c, metadata, context, conditions = fixture_input(case)
    result = classify_action(c, metadata=metadata, context=context)
    assert result.to_dict()["safety_class"] == case["expected"]
    assert evaluate_policy(result, conditions).eligible is case["eligible"]


def test_missing_safety_sidecar_and_enforced_unknown_execution_rejected():
    f = food(); audit = f["audit"]
    baseline = build_action_chain(audit, audit["production_row"], f["events"])
    audit["action_safety"] = dict(schema="phase5a-safety-step-v1", scenario=audit["scenario"], step=audit["step"],
        mode="enforce", selected=dict(classification=dict(safety_class="UNKNOWN", confidence="LOW"), policy=dict(eligible=True)),
        final_outcome=dict(planner_executed=True))
    assert "SAFETY_PROVENANCE_MISSING" in action_chain_failures(baseline, audit)
    chain = build_action_chain(audit, audit["production_row"], f["events"])
    assert "SAFETY_BLOCKED_ACTION_EXECUTED" in action_chain_failures(chain, audit)
