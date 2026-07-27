from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunMetadata:
    run_id: str
    batch_id: str
    device_model: str
    form_factor: str
    android_version: str
    one_ui_version: str
    talkback: str
    talkback_package: str
    app: str
    app_package: str
    locale: str
    display_width: int
    display_height: int


@dataclass(frozen=True, slots=True)
class SourceRow:
    result_row: int
    scenario_id: str
    scenario_name: str
    step: str
    screen: str
    automatic_result: str
    issue_type: str
    mismatch_type: str
    mismatch_reason: str
    visible_text: str
    speech: str
    speech_status: str
    speech_diagnostic: str
    expected: str
    resource_id: str
    class_name: str
    bounds: str
    screenshot: str
    screenshot_annotation: str
    screenshot_evidence_type: str
    evidence: str
    source_run_id: str
    focus_target: str
    focus_target_source: str
    approximate_position: str
    focus_center_relative: str
    review_description: str
    review_area: str
    classification_reason: str
    traversal_state: str
    recovery_state: str
    terminal_state: str
    source_transaction_id: str
    source_signature_digest: str
    validator_decision: str = "미검토"
    validator_comment: str = ""
    reviewer: str = ""
    reviewed_at: str = ""


@dataclass(frozen=True, slots=True)
class ReviewOutput:
    path: Path
    run_id: str
    review_count: int
