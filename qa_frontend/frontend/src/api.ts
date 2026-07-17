export type IdentityFeatureFlags = {
  evidence_ledger: boolean;
  identity_shadow_v2: boolean;
  traversal_identity_v2: boolean;
  runtime_profiler: boolean;
};

export type TraversalIdentityV2Diagnostics = {
  available: boolean;
  schema: 'traversal-identity-v2-diagnostics-v1' | string;
  reason?: string;
  missing_counters?: string[];
  false_progress_suppressed?: number;
  representative_only_progress_ignored?: number;
  recovered_candidate_attempts?: number;
  recovered_visits?: number;
  premature_stop_prevented?: number;
  fallback_to_legacy_count?: number;
  indeterminate_count?: number;
};

export type RunStatus = {
  state: 'idle' | 'running' | 'stopped' | 'finished' | 'error';
  run_id: string | null;
  mode: string | null;
  started_at: string | null;
  finished_at: string | null;
  returncode: number | null;
  error: string | null;
  log_path?: string | null;
  scenario_ids: string[];
  scenario_selection_applied: boolean;
  runtime_config_path: string | null;
  max_steps_policy: string | null;
  scenario_steps: Array<{
    scenario: string;
    selected: boolean;
    original_max_steps: number | null;
    effective_max_steps: number | null;
    policy: string;
  }>;
  launch_mode: 'warm' | 'clean';
  language_mode: 'current' | 'ko-KR' | 'en-US';
  device_locale: string | null;
  target_locale?: string | null;
  manual_language_change_required?: boolean;
  language_error?: string | null;
  language_settings_intent?: string | null;
  language_status: Record<string, unknown> | null;
  preflight_state: string | null;
  preflight_reason: string | null;
  talkback_state: string | null;
  helper_state: string | null;
  foreground_package: string | null;
  popup_preflight_state: string | null;
  popup_detected: boolean;
  popup_package: string | null;
  popup_dismissed: boolean;
  popup_result: string | null;
  accessibility_settings_opened: boolean;
  preflight: Record<string, unknown> | null;
  feature_flags?: IdentityFeatureFlags | null;
  traversal_identity_v2_diagnostics?: TraversalIdentityV2Diagnostics | null;
};
export type DeviceInfo = {
  serial: string;
  model: string;
  state: string;
  helper_ready: boolean | null;
  talkback_enabled: boolean | null;
  foreground_package: string | null;
};

export type AdbStatus = Record<string, unknown> & {
  status?: string;
  devices: Array<{
    serial: string;
    state: string;
  }>;
};

export type BatchDeviceRequest = {
  serial: string;
  model: string;
};

export type IdentityShadowReport = {
  available: boolean;
  schema: 'identity-shadow-report-v1' | string;
  availability: string;
  legacy_available?: boolean;
  v2_available?: boolean;
  summary: {
    transactions: number;
    changed: number;
    incomplete: number;
    strong_physical: number;
    insufficient: number;
    v2_verdicts: Record<string, number>;
    target_relations?: Record<string, number>;
    v2_verdict_percentages?: Record<string, number>;
    confidence_counts?: Record<string, number>;
    confidence_percentages?: Record<string, number>;
    relation_counts?: Record<string, number>;
    relation_percentages?: Record<string, number>;
  };
  transactions: Array<{ transaction_id: string; step_index?: number | null; action_type?: string | null; legacy_verdict?: string | null; v2_verdict?: string | null; verdict_changed: boolean; target_relation?: string | null; temporal_relation?: string | null; confidence?: string | null; evidence_complete: boolean }>;
  traversal_identity_v2_diagnostics?: TraversalIdentityV2Diagnostics;
};

export type BatchStartRequest = {
  devices: BatchDeviceRequest[];
  mode: string;
};

export type BatchDeviceStatus = {
  serial: string;
  model: string;
  state: 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | string;
  output_dir: string;
  return_code: number | null;
  started_at: string | null;
  finished_at: string | null;
  error?: string;
  runner_log_path?: string | null;
  current?: BatchCurrentStatus;
  progress?: BatchProgressStatus;
  logs?: BatchLogStatus;
  feature_flags?: IdentityFeatureFlags | null;
};

export type BatchSummaryStatus = {
  batch_id: string | null;
  state: 'idle' | 'running' | 'finished' | 'failed' | 'stopped' | string;
  started_at: string | null;
  finished_at: string | null;
  total_devices: number;
  finished_devices: number;
  passed_devices: number;
  failed_devices: number;
  warning_devices: number;
};

export type BatchCurrentStatus = {
  current_device_serial: string | null;
  current_device_model: string | null;
  current_device_state?: string | null;
  current_scenario_id: string | null;
  current_scenario_name: string | null;
  current_scenario_runtime_state?: string | null;
  current_scenario_state?: string | null;
  latest_scenario_event?: string | null;
  current_step_index: number | null;
  current_step_label: string | null;
  current_step_action: string | null;
  current_step_target: string | null;
  current_step_result: string | null;
  current_navigation_result?: string | null;
  current_navigation_detail?: string | null;
  latest_step_log?: string | null;
  current_step_log?: string | null;
  latest_runtime_event?: string | null;
};

export type BatchProgressStatus = {
  selected_scenarios?: number;
  observed_scenarios?: number;
  tail_observed_scenarios?: number;
  total_scenarios: number;
  completed_scenarios: number;
  executed_scenarios?: number;
  not_available_scenarios?: number;
  not_available_candidate_scenarios?: number;
  no_target_candidate_scenarios?: number;
  availability_candidate_scenarios?: number;
  passed_scenarios: number;
  failed_scenarios: number;
  warning_scenarios: number;
  observed_runtime_events?: number;
  observed_steps?: number;
  total_steps: number;
  completed_steps: number;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  review_count: number;
};

export type BatchLogStatus = {
  latest_log_line: string | null;
  latest_preflight_status: {
    device_connected: string | null;
    screen_awake: string | null;
    unlock_swipe: string | null;
    app_foreground: string | null;
    helper: string | null;
    talkback: string | null;
    last?: string | null;
  };
  latest_quality_event: string | null;
};

export type BatchStatus = {
  batch_id: string | null;
  state: 'idle' | 'running' | 'finished' | 'error' | string;
  mode: string | null;
  current_device: string | null;
  devices: BatchDeviceStatus[];
  batch?: BatchSummaryStatus;
  current?: BatchCurrentStatus;
  progress?: BatchProgressStatus;
  logs?: BatchLogStatus;
};

export type Scenario = {
  id: string;
  enabled: boolean;
  max_steps: number | null;
};

export type OutputFile = {
  filename: string;
  size: number;
  modified: number;
};

export type ComparatorBaseline = { baseline_id: string; revision: number | null; state: string; approved_at: string | null; app_package: string | null; version: string | null; locale: string | null; source_candidate_id?: string | null; source_run_id?: string | null; source_batch_id?: string | null };
export type ComparatorCandidate = { candidate_id: string; run: string; source: string; app_package: string | null; version: string | null; locale: string | null; source_status?: string; source_status_label?: string; eligibility?: boolean | null; run_kind?: string | null; dirty?: boolean | null; approved_baseline_id?: string | null; blocking_reasons?: string[] };
export type ComparisonHistoryEntry = { comparison_id: string; baseline_id: string; candidate_id: string; compared_at: string; verdict: unknown; result?: Record<string, unknown> };

export type RecentRun = {
  run_id: string;
  mode: 'smoke' | 'full';
  language_mode?: string;
  device_locale?: string | null;
  status: string;
  process_status: string;
  scenario_result_status: string;
  passed_scenarios?: number;
  warning_scenarios?: number;
  completed_scenarios: number;
  executed_scenarios?: number;
  not_available_scenarios?: number;
  not_available_candidate_scenarios?: number;
  no_target_candidate_scenarios?: number;
  availability_candidate_scenarios?: number;
  failed_scenarios: number;
  total_scenarios: number;
  event_warning_count: number;
  started_at: string;
  duration_seconds: number;
  log_exists: boolean;
  log_filename: string | null;
  xlsx_exists: boolean;
  xlsx_filename: string | null;
  summary_exists?: boolean;
  summary_source?: string;
  feature_flags?: IdentityFeatureFlags | null;
  traversal_identity_v2_diagnostics?: TraversalIdentityV2Diagnostics | null;
  scenarios?: Array<{
    id: string;
    status: 'passed' | 'warning' | 'failed' | 'skipped' | 'running' | 'queued' | string;
    steps?: number;
    reason?: string | null;
    stop_reason?: string | null;
    traversal_result?: string | null;
    availability_status?: string | null;
    availability_confidence?: string | null;
    availability_reason?: string | null;
    availability_target?: string | null;
  }>;
};

export type QualityIssue = {
  scenario_id: string;
  step: string;
  context_type?: string;
  visible_label?: string;
  merged_announcement?: string;
  mismatch_type: string;
  final_result: string;
  shadow_verdict?: string;
  shadow_verdict_reason?: string;
  shadow_verdict_source?: string;
  scenario_shadow_verdict?: string;
  review_note?: string;
  focus_confidence?: string;
  crop_path?: string | null;
};

export type FocusableCoverageIssue = {
  scenario_id: string;
  focusable_label: string;
  focusable_view_id?: string;
  focusable_taxonomy: 'REQUIRED' | 'REVIEW' | 'OPTIONAL' | 'IGNORE' | string;
  focusable_coverage_status: 'COVERED' | 'MISSED' | 'UNKNOWN' | string;
  focusable_coverage_reason?: string;
  focusable_taxonomy_reason?: string;
};

export type FocusableCoverage = {
  summary?: {
    focusable_required_expected_count?: number;
    focusable_required_covered_count?: number;
    focusable_required_missed_count?: number;
    focusable_review_expected_count?: number;
    focusable_review_unknown_count?: number;
    focusable_optional_expected_count?: number;
    focusable_coverage_rate?: number | null;
  };
  scenarios?: Array<{
    scenario_id: string;
    focusable_required_missed?: number;
    focusable_review_unknown?: number;
    focusable_coverage_rate?: number | null;
  }>;
  issues?: FocusableCoverageIssue[];
};

export type CoverageProbeSummary = {
  available: boolean;
  source: 'aggregate' | 'scenario' | 'none' | string;
  results_artifact?: string | null;
  validation_artifact?: string | null;
  probe_enabled?: boolean;
  candidate_count?: number;
  attempted_count?: number;
  success_count?: number;
  failed_count?: number;
  match_count?: number;
  promotable_count: number;
  not_promotable_count?: number;
  promoted_row_count: number;
  dedup_skipped_count?: number;
  screen_skipped_count?: number | null;
  scenario_filtered_count?: number | null;
  total_candidate_count?: number;
  total_attempted_count?: number;
  total_success_count?: number;
  total_failed_count?: number;
  promotion_dedup_skipped_count?: number;
  total_screen_skipped_count?: number | null;
  total_scenario_filtered_count?: number | null;
};

export type ShadowValidationSummary = {
  available: boolean;
  status: 'completed' | 'incomplete' | 'failed' | string;
  inventory_count: number;
  identified_count: number;
  identify_unknown_count: number;
  match_count: number;
  unknown_count: number;
  ambiguous_count: number;
  mismatch_count: number;
  failed_count: number;
  promotion_eligible_count: number;
  legacy_preserved: boolean;
  runtime_seconds: number | null;
  result_groups: Record<'MATCH' | 'UNKNOWN' | 'AMBIGUOUS' | 'MISMATCH' | 'FAILED', string[]>;
  promotion_readiness?: {
    overall_status: 'READY' | 'HOLD' | 'BLOCKED' | 'INSUFFICIENT_DATA' | 'UNKNOWN_ONLY' | string;
    legacy_preserved: boolean;
    controlled_routing_enabled: false;
    status_counts: Record<'READY' | 'HOLD' | 'BLOCKED' | 'INSUFFICIENT_DATA' | 'UNKNOWN_ONLY', number>;
    families: Array<{
      plugin_family: string;
      status: 'READY' | 'HOLD' | 'BLOCKED' | 'INSUFFICIENT_DATA' | 'UNKNOWN_ONLY' | string;
      reason: string;
      observation_count: number;
      counts: Record<'MATCH' | 'UNKNOWN' | 'AMBIGUOUS' | 'MISMATCH' | 'FAILED', number>;
      promotion_eligible_count: number;
      minimum_confidence: number;
      average_confidence: number;
      ready_candidate: boolean;
    }>;
  } | null;
  error?: string;
  error_stage?: string;
  artifacts: {
    report: string | null;
    compare: string | null;
    readiness_report: string | null;
    readiness_json: string | null;
    folder_available: boolean;
  };
};

export type RecentBatchDevice = {
  serial: string;
  model: string;
  state: string;
  output_dir?: string | null;
  return_code: number | null;
  log_path?: string | null;
  runner_log_path?: string | null;
  xlsx_path?: string | null;
  quality?: {
    fail: number;
    issue: number;
    review: number;
    clean: number;
  } | null;
  shadow_quality?: {
    pass: number;
    review: number;
    warn: number;
    fail: number;
  } | null;
  shadow_scenarios?: Array<{
    scenario_id: string;
    scenario_shadow_verdict?: string;
    shadow_pass_count?: number;
    shadow_review_count?: number;
    shadow_warn_count?: number;
    shadow_fail_count?: number;
    focusable_required_missed?: number;
    focusable_review_unknown?: number;
    focusable_coverage_rate?: number | null;
  }>;
  quality_issues?: QualityIssue[];
  focusable_coverage?: FocusableCoverage | null;
  focusable_issues?: FocusableCoverageIssue[];
  coverage_probe_summary?: CoverageProbeSummary | null;
  coverage_probe?: CoverageProbeSummary | null;
  shadow_validation?: ShadowValidationSummary | null;
  feature_flags?: IdentityFeatureFlags | null;
  traversal_identity_v2_diagnostics?: TraversalIdentityV2Diagnostics | null;
  process_status?: string;
  scenario_result_status?: string;
  passed_scenarios?: number;
  warning_scenarios?: number;
  completed_scenarios?: number;
  executed_scenarios?: number;
  not_available_scenarios?: number;
  not_available_candidate_scenarios?: number;
  no_target_candidate_scenarios?: number;
  availability_candidate_scenarios?: number;
  failed_scenarios?: number;
  total_scenarios?: number;
  scenarios?: Array<{
    id: string;
    status: 'passed' | 'warning' | 'failed' | 'skipped' | 'running' | 'queued' | string;
    steps?: number;
    reason?: string | null;
    stop_reason?: string | null;
    traversal_result?: string | null;
    availability_status?: string | null;
    availability_confidence?: string | null;
    availability_reason?: string | null;
    availability_target?: string | null;
  }>;
};

export type RecentBatch = {
  batch_id: string;
  state: string;
  mode: string;
  created_at: string;
  duration_seconds?: number | null;
  device_count: number;
  passed_count: number;
  failed_count: number;
  summary_path: string;
  feature_flags?: IdentityFeatureFlags | null;
  devices?: RecentBatchDevice[];
};

export type CrashItem = {
  crash_event_id: string;
  crash_type: string;
  scenario: string | null;
  timestamp: string | null;
  recovery_result: 'CRASH_CAPTURED' | 'CRASH_RECOVERED' | 'CRASH_REPEATED' | 'unknown' | string;
  repro_guide_exists: boolean;
  screenshot_exists: boolean;
  helper_dump_exists: boolean;
  window_dump_exists: boolean;
};

export type CrashSummary = {
  crash_count: number;
  crashes: CrashItem[];
};

export type CrashDetail = CrashItem & {
  repro_guide: string | null;
  artifacts: {
    screenshot: boolean;
    helper_dump: boolean;
    window_dump: boolean;
  };
};

export type RuntimeEvent = {
  line: number;
  type: string;
  scenario: string | null;
  message: string;
};

export type ScenarioProgress = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'skipped' | string;
  steps: number;
  availability_status?: string | null;
  availability_confidence?: string | null;
  availability_reason?: string | null;
  availability_target?: string | null;
};

export type RuntimeDashboard = {
  run_id: string | null;
  mode: string | null;
  launch_mode: string | null;
  language_mode: string | null;
  device_locale: string | null;
  state: string | null;
  started_at: string | null;
  elapsed_seconds: number;
  current_scenario: string | null;
  completed_scenarios: number;
  executed_scenarios?: number;
  not_available_scenarios?: number;
  not_available_candidate_scenarios?: number;
  no_target_candidate_scenarios?: number;
  availability_candidate_scenarios?: number;
  passed_scenarios?: number;
  warning_scenarios?: number;
  remaining_scenarios: number;
  failed_scenarios: number;
  scenario_progress: ScenarioProgress[];
  current_step: number | null;
  total_step_count: number;
  overlay_count: number;
  save_excel_count: number;
  popup_result: string | null;
  preflight_state: string | null;
  helper_status: string | null;
  adb_status: string | null;
  last_focus_label: string | null;
  last_focus_package: string | null;
  stop_reason: string | null;
  traversal_result: string | null;
  event_feed: RuntimeEvent[];
  log_size: number;
  parse_error: string | null;
};

export type HelperStatus = {
  helper_name: string;
  status: 'ok' | 'not_installed' | 'disabled' | 'apk_not_found' | 'error' | string;
  apk_found: boolean;
  apk_path: string | null;
  apk_searched: string[];
  installed: boolean;
  accessibility_enabled: boolean;
  package_name: string;
  service_name: string;
  build_command: string;
  ok?: boolean;
  error?: string;
  enabled_accessibility_services?: string;
  helper_service_appended?: boolean;
  accessibility_settings_opened?: boolean;
};

export type TalkBackEnableResponse = {
  ok: boolean;
  status: 'enabled' | 'error' | string;
  service_name?: string;
  selected_package?: string;
  candidates?: string[];
  enabled_accessibility_services?: string;
  accessibility_enabled?: string;
  helper_service_preserved?: boolean;
  talkback_service_appended?: boolean;
  error?: string;
};

export type TalkBackFixResponse = {
  ok: boolean;
  status: 'fixed' | 'still_not_ready' | 'helper_not_ready' | 'popup_contamination' | 'adb_unavailable' | 'talkback_enable_failed' | string;
  talkback_status?: string;
  talkback_reason?: string;
  settings_opened?: boolean;
  message?: string;
  error?: string;
  steps?: Array<Record<string, unknown>>;
};

export type OpenLanguageSettingsResponse = {
  ok: boolean;
  status: 'opened' | 'error' | string;
  intent?: string;
  error?: string;
};

export type CorpusReadinessDistribution = {
  READY: number;
  HOLD: number;
  BLOCKED: number;
  INSUFFICIENT_DATA: number;
  UNKNOWN_ONLY: number;
};

export type CorpusFamilySummary = {
  family: string;
  total_runs: number;
  total_observations: number;
  match_count: number;
  unknown_count: number;
  ambiguous_count: number;
  mismatch_count: number;
  failed_count: number;
  unique_device_label_count: number;
  unique_device_model_count: number;
  unique_device_serial_count: number;
  unique_locale_count: number;
  unique_app_version_count: number;
  last_seen_at: string;
  readiness: string;
  readiness_distribution: CorpusReadinessDistribution;
  candidate_for_v11_pilot: boolean;
};

export type CorpusDashboard = {
  available: boolean;
  corpus_dir: string;
  entry_count: number;
  last_updated: string;
  overall_readiness: string;
  overall_readiness_distribution: CorpusReadinessDistribution;
  family_readiness_counts: CorpusReadinessDistribution;
  totals: Record<'MATCH' | 'UNKNOWN' | 'AMBIGUOUS' | 'MISMATCH' | 'FAILED', number>;
  family_count: number;
  families: CorpusFamilySummary[];
  candidate_for_v11_pilot: string[];
  candidate_count: number;
  blocking_families: string[];
  unknown_only_families: string[];
  diversity_metrics: {
    unique_labels: number;
    unique_device_models: number;
    max_unique_devices_per_family: number;
    unique_locales: number;
    unique_app_versions: number;
  };
  controlled_routing_enabled: false;
};

export type PluginDiscoveryCard = {
  id: string;
  label: string;
  stable_label: string;
  type: 'life' | 'device' | string;
  confidence: 'high' | 'medium' | 'low' | string;
  source: 'helper' | 'xml' | 'helper+xml' | string;
  bounds: string;
  resource_id: string;
  known: boolean;
  existing_scenario_id: string;
};

export type PluginDiscoveryResponse = {
  ok: boolean;
  schema_version: 'plugin-discovery-v1' | string;
  cards: PluginDiscoveryCard[];
  diagnostics: {
    warnings: string[];
  };
};

export type PluginProbeResponse = {
  ok: boolean;
  schema_version: 'plugin-probe-v1' | string;
  probe_status: string;
  entry: {
    attempted: boolean;
    method: string;
    open_confirmed: boolean;
    reason: string;
  };
  summary: {
    plugin_open_verified_candidate: boolean;
    suggested_entry_method: string;
    suggested_scenario_type: string;
  };
  seed: {
    verify_tokens: string[];
    negative_verify_tokens: string[];
    headers: string[];
    local_tabs: string[];
    representative_cards: string[];
    overlay_hints: string[];
    context_verify_text_candidates: string[];
    entry_candidate: {
      action: string;
      target_seed: string;
    };
  };
  artifacts: {
    helper_nodes_captured: boolean;
    xml_captured: boolean;
    focus_steps: number;
  };
  diagnostics: {
    warnings: string[];
    failure_reason: string;
  };
};

export type PluginDraftResponse = {
  ok: boolean;
  schema_version: 'plugin-draft-v1' | string;
  draft_status: string;
  draft: {
    scenario: Record<string, unknown>;
    runtime_config: Record<string, unknown>;
    metadata: {
      source_card: PluginDiscoveryCard;
      probe_status: string;
      plugin_open_verified_candidate: boolean;
      headers: string[];
      local_tabs: string[];
      representative_cards: string[];
      overlay_hints: string[];
      context_verify_text_candidates: string[];
      manual_review_required: boolean;
    };
  };
  diagnostics: {
    warnings: string[];
    notes: string[];
    failure_reason: string;
  };
};

export type PluginDraftReviewResponse = {
  ok: boolean;
  schema_version: 'plugin-draft-review-v1' | string;
  review_status: string;
  checks: {
    scenario_id_exists: boolean;
    runtime_config_exists: boolean;
    manual_review_required: boolean;
    can_apply: boolean;
  };
  preview: {
    scenario_config_insertion_hint: string;
    runtime_config_patch: Record<string, unknown>;
    diff_preview: string;
  };
  diagnostics: {
    warnings: string[];
    errors: string[];
  };
};

export type PluginDraftApplyResponse = {
  ok: boolean;
  schema_version: 'plugin-draft-apply-v1' | string;
  apply_status: string;
  changed_files: string[];
  backup: {
    created: boolean;
    paths: string[];
  };
  applied: {
    scenario_id: string;
    runtime_config_key: string;
  };
  diagnostics: {
    warnings: string[];
    errors: string[];
  };
};

export type PluginDraftSmokeResponse = {
  ok: boolean;
  schema_version: 'plugin-draft-smoke-v1' | string;
  smoke_status: string;
  run_id: string;
  scenario_id: string;
  max_steps: number;
  summary: {
    pre_navigation_success: boolean;
    plugin_open_verified: boolean;
    steps_collected: number;
    failure_reason: string;
    result_status: string;
  };
  artifacts: {
    log_path: string;
    xlsx_path: string;
  };
  diagnostics: {
    warnings: string[];
  };
};

export type PluginDraftSmokeStatusResponse = Omit<PluginDraftSmokeResponse, 'schema_version' | 'diagnostics'> & {
  schema_version: 'plugin-draft-smoke-status-v1' | string;
  run_status: string;
  artifacts: PluginDraftSmokeResponse['artifacts'] & {
    summary_json_path: string;
    display_urls: {
      log: string;
      xlsx: string;
    };
  };
  diagnostics: {
    warnings: string[];
    errors: string[];
  };
};

export type PluginOnboardingSession = {
  schema_version: 'plugin-onboarding-session-v1' | string;
  session_id: string;
  plugin: {
    label: string;
    stable_label: string;
    type: string;
    scenario_id: string;
  };
  status: string;
  steps: Record<string, { status: string; payload: Record<string, unknown>; updated_at?: string }>;
  feedback: {
    warnings: string[];
    errors: string[];
    suggestions: string[];
  };
  created_at: string;
  updated_at: string;
};

export type PluginOnboardingSessionCreateResponse = {
  ok: boolean;
  schema_version: 'plugin-onboarding-session-v1' | string;
  session_id: string;
};

export type PluginOnboardingSessionResponse = {
  ok: boolean;
  schema_version: 'plugin-onboarding-session-v1' | string;
  session: PluginOnboardingSession;
};

export type PluginOnboardingSessionsResponse = {
  ok: boolean;
  schema_version: 'plugin-onboarding-session-v1' | string;
  sessions: PluginOnboardingSession[];
};

export type PluginOnboardingRestoreResponse = {
  ok: boolean;
  schema_version: 'plugin-onboarding-restore-v1' | string;
  session: PluginOnboardingSession;
  restored_state: {
    selected_card: Partial<PluginDiscoveryCard>;
    probe_result: Partial<PluginProbeResponse>;
    draft_result: Partial<PluginDraftResponse>;
    review_result: Partial<PluginDraftReviewResponse>;
    apply_result: Partial<PluginDraftApplyResponse>;
    rollback_result?: Record<string, unknown>;
    smoke_start_result: Partial<PluginDraftSmokeResponse>;
    smoke_status_result: Partial<PluginDraftSmokeStatusResponse>;
  };
  recommendation: {
    next_action: string;
    severity: 'success' | 'warning' | 'danger' | 'info' | string;
    reasons: string[];
    allowed_actions: string[];
    blocked_actions: string[];
  };
};

export type PluginRollbackPreviewResponse = {
  ok: boolean;
  schema_version: 'plugin-rollback-preview-v1' | string;
  rollback_status: string;
  can_rollback: boolean;
  target_files: string[];
  backup: {
    found: boolean;
    paths: string[];
  };
  preview: {
    scenario_entry_will_be_removed: boolean;
    runtime_config_entry_will_be_removed: boolean;
    diff_preview: string;
  };
  diagnostics: {
    warnings: string[];
    errors: string[];
  };
};

export type PluginRollbackExecuteResponse = {
  ok: boolean;
  schema_version: 'plugin-rollback-execute-v1' | string;
  rollback_status: string;
  session_id: string;
  restored_files: string[];
  backup: {
    paths: string[];
  };
  pre_rollback_backup: string[];
  diagnostics: {
    warnings: string[];
    errors: string[];
  };
};

export type PluginRemoveAppliedDraftResponse = {
  ok: boolean;
  schema_version: string;
  remove_status: string;
  session_id: string;
  removed?: { scenario_id: string; runtime_config_key: string };
  changed_files?: string[];
  backup?: { created: boolean; paths: string[] };
  diagnostics: { warnings: string[]; errors: string[] };
};

export type PluginDeleteSessionResponse = {
  ok: boolean;
  schema_version: string;
  session_id: string;
  delete_status: string;
};

function formatApiPayloadError(payload: unknown) {
  if (!payload || typeof payload !== 'object') {
    return '';
  }
  const data = payload as Record<string, unknown>;
  const lines = [
    data.error,
    data.message,
    data.build_command ? `Build command: ${data.build_command}` : null,
    Array.isArray(data.apk_searched) ? `Searched: ${data.apk_searched.join(', ')}` : null,
  ].filter(Boolean);
  return lines.join('\n');
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'string' ? payload : formatApiPayloadError(payload);
    throw new Error(message || response.statusText);
  }
  if (payload && typeof payload === 'object' && (payload as Record<string, unknown>).ok === false) {
    throw new Error(formatApiPayloadError(payload) || 'Request failed');
  }
  return payload as T;
}

async function requestPayload<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  const contentType = response.headers.get('content-type') ?? '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'string' ? payload : formatApiPayloadError(payload);
    throw new Error(message || response.statusText);
  }
  return payload as T;
}

export type RunSnapshot = {
  status: RunStatus;
  dashboard: RuntimeDashboard;
  log_tail: { lines: string[]; text: string; log_path: string | null };
  run_id: string | null;
  state: string | null;
  log_path: string | null;
  outputs_changed: boolean;
};

export const api = {
  devices: () => request<DeviceInfo[]>('/api/devices'),
  adbStatus: () => request<AdbStatus>('/api/adb/status'),
  helperStatus: () => request<HelperStatus>('/api/helper/status'),
  installHelper: () => request<HelperStatus>('/api/helper/install', { method: 'POST' }),
  enableHelper: () => request<HelperStatus>('/api/helper/enable', { method: 'POST' }),
  openAccessibilitySettings: () => request<HelperStatus>('/api/helper/open-accessibility-settings', { method: 'POST' }),
  enableTalkBack: () => request<TalkBackEnableResponse>('/api/talkback/enable', { method: 'POST' }),
  fixTalkBack: () => requestPayload<TalkBackFixResponse>('/api/talkback/fix', { method: 'POST' }),
  openLanguageSettings: () =>
    request<OpenLanguageSettingsResponse>('/api/device/open-language-settings', { method: 'POST' }),
  discoverPlugins: (data: { targets: string[]; include_xml: boolean; current_view_only: boolean }) =>
    requestPayload<PluginDiscoveryResponse>('/api/plugin-discovery/discover', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  startPluginProbe: (data: { card: PluginDiscoveryCard; max_probe_steps: number; include_xml: boolean; include_helper_dump: boolean }) =>
    requestPayload<PluginProbeResponse>('/api/plugin-probe/start', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  generatePluginDraft: (data: { card: PluginDiscoveryCard; probe: PluginProbeResponse; options?: { include_disabled_runtime_config: boolean } }) =>
    requestPayload<PluginDraftResponse>('/api/plugin-draft/generate', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  reviewPluginDraft: (data: { draft: PluginDraftResponse['draft']; options?: { include_diff_preview: boolean; check_existing: boolean } }) =>
    requestPayload<PluginDraftReviewResponse>('/api/plugin-draft/review', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  applyPluginDraft: (data: { draft: PluginDraftResponse['draft']; review: PluginDraftReviewResponse; options?: { create_backup: boolean } }) =>
    requestPayload<PluginDraftApplyResponse>('/api/plugin-draft/apply', {
      method: 'POST',
      body: JSON.stringify({
        draft: data.draft,
        review: {
          schema_version: data.review.schema_version,
          checks: data.review.checks,
        },
        options: data.options,
      }),
    }),
  smokePluginDraft: (data: { scenario_id: string; max_steps: number; mode: 'smoke'; serial?: string | null; options?: { force_enabled_runtime_override: boolean; collect_summary: boolean } }) =>
    requestPayload<PluginDraftSmokeResponse>('/api/plugin-draft/smoke', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getPluginDraftSmokeStatus: (runId: string, scenarioId: string) =>
    requestPayload<PluginDraftSmokeStatusResponse>(
      `/api/plugin-draft/smoke/${encodeURIComponent(runId)}?scenario_id=${encodeURIComponent(scenarioId)}`,
    ),
  createPluginOnboardingSession: (data: { card: Pick<PluginDiscoveryCard, 'label' | 'stable_label' | 'type' | 'existing_scenario_id'> }) =>
    requestPayload<PluginOnboardingSessionCreateResponse>('/api/plugin-onboarding/session', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  savePluginOnboardingStep: (sessionId: string, data: { step: string; status: string; payload: Record<string, unknown> }) =>
    requestPayload<PluginOnboardingSessionResponse>(`/api/plugin-onboarding/session/${encodeURIComponent(sessionId)}/step`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getPluginOnboardingSession: (sessionId: string) =>
    requestPayload<PluginOnboardingSessionResponse>(`/api/plugin-onboarding/session/${encodeURIComponent(sessionId)}`),
  restorePluginOnboardingSession: (sessionId: string) =>
    requestPayload<PluginOnboardingRestoreResponse>(`/api/plugin-onboarding/session/${encodeURIComponent(sessionId)}/restore`),
  previewPluginRollback: (sessionId: string) =>
    requestPayload<PluginRollbackPreviewResponse>(`/api/plugin-onboarding/session/${encodeURIComponent(sessionId)}/rollback/preview`, {
      method: 'POST',
    }),
  executePluginRollback: (sessionId: string, data: { confirm: boolean }) =>
    requestPayload<PluginRollbackExecuteResponse>(`/api/plugin-onboarding/session/${encodeURIComponent(sessionId)}/rollback`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listPluginOnboardingSessions: () => requestPayload<PluginOnboardingSessionsResponse>('/api/plugin-onboarding/sessions'),
  removeAppliedDraft: (sessionId: string, data: { confirm: boolean }) =>
    requestPayload<PluginRemoveAppliedDraftResponse>(`/api/plugin-onboarding/session/${encodeURIComponent(sessionId)}/remove-applied-draft`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteSession: (sessionId: string) =>
    requestPayload<PluginDeleteSessionResponse>(`/api/plugin-onboarding/session/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),
  scenarios: () => request<{ scenarios: Scenario[] }>('/api/scenarios'),
  getV10CorpusSummary: () => request<CorpusDashboard>('/api/v10/corpus/summary'),
  openV10CorpusTarget: (target: 'folder' | 'index' | 'family-summary' | 'readiness-summary') =>
    request<{ ok: boolean; path: string }>(`/api/v10/corpus/open/${target}`, { method: 'POST' }),
  startRun: (
    mode: 'smoke' | 'full',
    scenarioIds: string[],
    launchMode: 'warm' | 'clean',
    languageMode: 'current' | 'ko-KR' | 'en-US',
    enableCoverageProbe?: boolean,
    shadowValidation?: boolean,
    evidenceLedger?: boolean,
    identityShadowV2?: boolean,
    traversalIdentityV2?: boolean,
    traversalProfiler?: boolean,
  ) =>
    request<RunStatus>('/api/run/start', {
      method: 'POST',
      body: JSON.stringify({ mode, scenario_ids: scenarioIds, launch_mode: launchMode, language_mode: languageMode, enable_coverage_probe: enableCoverageProbe, shadow_validation: shadowValidation, evidence_ledger: evidenceLedger, identity_shadow_v2: identityShadowV2, traversal_identity_v2: traversalIdentityV2, traversal_profiler: traversalProfiler }),
    }),
  stopRun: () => request<RunStatus>('/api/run/stop', { method: 'POST' }),
  startBatch: async (data: { mode: string; devices: { serial: string; model: string }[]; launch_mode: string; language_mode: string; scenario_ids: string[]; enable_coverage_probe?: boolean; shadow_validation?: boolean; evidence_ledger?: boolean; identity_shadow_v2?: boolean; traversal_identity_v2?: boolean; traversal_profiler?: boolean }) => {
    return request<BatchStatus>('/api/batch/start', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },
  stopBatch: () => request<BatchStatus>('/api/batch/stop', { method: 'POST' }),
  getBatchStatus: () => request<BatchStatus>('/api/batch/status'),
  runStatus: () => request<RunStatus>('/api/run/status'),
  runDashboard: () => request<RuntimeDashboard>('/api/run/dashboard'),
  runLog: () => request<{ text: string }>('/api/run/log'),
  runSnapshot: () => request<RunSnapshot>('/api/run/snapshot'),
  recentRuns: () => request<{ runs: RecentRun[] }>('/api/runs/recent'),
  comparatorBaselines: () => request<{ baselines: ComparatorBaseline[] }>('/api/comparator/baselines'),
  comparatorCandidates: () => request<{ candidates: ComparatorCandidate[] }>('/api/comparator/candidates'),
  compare: (baselineId: string, candidateId: string) => request<ComparisonHistoryEntry>('/api/comparator/compare', {
    method: 'POST', body: JSON.stringify({ baseline_id: baselineId, candidate_id: candidateId }),
  }),
  comparisonHistory: () => request<{ comparisons: ComparisonHistoryEntry[] }>('/api/comparator/history'),
  comparisonResult: (comparisonId: string) => request<ComparisonHistoryEntry>(`/api/comparator/results/${encodeURIComponent(comparisonId)}`),
  comparisonMarkdown: (comparisonId: string) => request<string>(`/api/comparator/results/${encodeURIComponent(comparisonId)}/markdown`),
  comparisonJsonDownloadUrl: (comparisonId: string) => `/api/comparator/results/${encodeURIComponent(comparisonId)}/report.json`,
  comparisonMarkdownDownloadUrl: (comparisonId: string) => `/api/comparator/results/${encodeURIComponent(comparisonId)}/report.md`,
  recentBatches: () => request<RecentBatch[]>('/api/batch/recent'),
  getBatchLogTail: (path: string) => request<{ text: string }>(`/api/batch/log-tail?path=${encodeURIComponent(path)}`),
  openShadowFolder: (runId: string, deviceId: string) =>
    request<{ ok: boolean; path: string }>(
      `/api/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}/shadow/open-folder`,
      { method: 'POST' },
    ),
  getIdentityShadow: (runId: string, deviceId: string) =>
    request<IdentityShadowReport>(`/api/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}/identity-shadow`),
  getRunDeviceCrashes: (runId: string, deviceId: string) =>
    request<CrashSummary>(`/api/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}/crashes`),
  getRunDeviceCrash: (runId: string, deviceId: string, crashEventId: string) =>
    request<CrashDetail>(
      `/api/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}/crashes/${encodeURIComponent(crashEventId)}`,
    ),
  getRunDeviceCrashScreenshotUrl: (runId: string, deviceId: string, crashEventId: string) =>
    `/api/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}/crashes/${encodeURIComponent(crashEventId)}/screenshot`,
  getRunDeviceCrashDownloadUrl: (runId: string, deviceId: string, crashEventId: string) =>
    `/api/runs/${encodeURIComponent(runId)}/devices/${encodeURIComponent(deviceId)}/crashes/${encodeURIComponent(crashEventId)}/download`,
  runMismatch: (runId: string) => request<{
    summary: {
      fail_count: number;
      issue_count: number;
      review_count: number;
      clean_count: number;
      matched: number;
      true_mismatch: number;
      empty_speech: number;
      empty_visible: number;
      review: number;
      runtime_warning: number;
      shadow_pass_count?: number;
      shadow_review_count?: number;
      shadow_warn_count?: number;
      shadow_fail_count?: number;
      focusable_required_expected_count?: number;
      focusable_required_covered_count?: number;
      focusable_required_missed_count?: number;
      focusable_review_expected_count?: number;
      focusable_review_unknown_count?: number;
      focusable_optional_expected_count?: number;
      focusable_coverage_rate?: number | null;
    };
    scenario_summary: Array<{
      scenario_id: string;
      plugin_name: string;
      fail_count: number;
      issue_count: number;
      review_count: number;
      clean_count: number;
      matched: number;
      true_mismatch: number;
      empty_speech: number;
      empty_visible: number;
      review: number;
      runtime_warning: number;
      shadow_pass_count?: number;
      shadow_review_count?: number;
      shadow_warn_count?: number;
      shadow_fail_count?: number;
      scenario_shadow_verdict?: string;
      focusable_required_missed?: number;
      focusable_review_unknown?: number;
      focusable_coverage_rate?: number | null;
      status: 'fail' | 'issue' | 'review' | 'clean';
    }>;
    signals: Array<{ 
      scenario: string; 
      plugin_name: string;
      step: string;
      visible: string; 
      spoken: string; 
      mismatch_type: string; 
      final_result: string;
      shadow_verdict?: string;
      shadow_verdict_reason?: string;
      shadow_verdict_source?: string;
      scenario_shadow_verdict?: string;
      failure_reason: string;
      focus_confidence: string;
      repeat_count?: number;
      first_step?: string;
      last_step?: string;
      steps?: string;
      is_repeated_issue_group?: boolean;
      category: string; 
      top_category: string;
    }>;
    focusable_coverage?: FocusableCoverage;
    coverage_probe_summary?: CoverageProbeSummary;
    coverage_probe?: CoverageProbeSummary | null;
  }>(`/api/runs/recent/${encodeURIComponent(runId)}/mismatch`),
  outputs: () => request<{ outputs: OutputFile[] }>('/api/outputs'),
};
