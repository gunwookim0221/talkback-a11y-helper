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
  scenarios?: Array<{
    id: string;
    status: 'passed' | 'warning' | 'failed' | 'skipped' | 'running' | 'queued' | string;
    steps?: number;
    reason?: string | null;
    stop_reason?: string | null;
    traversal_result?: string | null;
  }>;
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

export type OpenLanguageSettingsResponse = {
  ok: boolean;
  status: 'opened' | 'error' | string;
  intent?: string;
  error?: string;
};

function formatApiPayloadError(payload: unknown) {
  if (!payload || typeof payload !== 'object') {
    return '';
  }
  const data = payload as Record<string, unknown>;
  const lines = [
    data.error,
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
  adbStatus: () => request<Record<string, unknown>>('/api/adb/status'),
  helperStatus: () => request<HelperStatus>('/api/helper/status'),
  installHelper: () => request<HelperStatus>('/api/helper/install', { method: 'POST' }),
  enableHelper: () => request<HelperStatus>('/api/helper/enable', { method: 'POST' }),
  openAccessibilitySettings: () => request<HelperStatus>('/api/helper/open-accessibility-settings', { method: 'POST' }),
  enableTalkBack: () => request<TalkBackEnableResponse>('/api/talkback/enable', { method: 'POST' }),
  openLanguageSettings: () =>
    request<OpenLanguageSettingsResponse>('/api/device/open-language-settings', { method: 'POST' }),
  scenarios: () => request<{ scenarios: Scenario[] }>('/api/scenarios'),
  startRun: (
    mode: 'smoke' | 'full',
    scenarioIds: string[],
    launchMode: 'warm' | 'clean',
    languageMode: 'current' | 'ko-KR' | 'en-US',
  ) =>
    request<RunStatus>('/api/run/start', {
      method: 'POST',
      body: JSON.stringify({ mode, scenario_ids: scenarioIds, launch_mode: launchMode, language_mode: languageMode }),
    }),
  stopRun: () => request<RunStatus>('/api/run/stop', { method: 'POST' }),
  runStatus: () => request<RunStatus>('/api/run/status'),
  runDashboard: () => request<RuntimeDashboard>('/api/run/dashboard'),
  runLog: () => request<{ text: string }>('/api/run/log'),
  runSnapshot: () => request<RunSnapshot>('/api/run/snapshot'),
  recentRuns: () => request<{ runs: RecentRun[] }>('/api/runs/recent'),
  runMismatch: (runId: string) => request<{
    summary: {
      matched: number;
      true_mismatch: number;
      empty_speech: number;
      empty_visible: number;
      review: number;
      runtime_warning: number;
    };
    scenario_summary: Array<{
      scenario_id: string;
      plugin_name: string;
      matched: number;
      true_mismatch: number;
      empty_speech: number;
      empty_visible: number;
      review: number;
      runtime_warning: number;
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
      failure_reason: string;
      focus_confidence: string;
      category: string; 
    }>;
  }>(`/api/runs/recent/${encodeURIComponent(runId)}/mismatch`),
  outputs: () => request<{ outputs: OutputFile[] }>('/api/outputs'),
};
