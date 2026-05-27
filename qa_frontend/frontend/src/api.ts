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
  status: string;
  started_at: string;
  duration_seconds: number;
  log_exists: boolean;
  log_filename: string | null;
  xlsx_exists: boolean;
  xlsx_filename: string | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  adbStatus: () => request<Record<string, unknown>>('/api/adb/status'),
  helperStatus: () => request<Record<string, unknown>>('/api/helper/status'),
  installHelper: () => request<Record<string, unknown>>('/api/helper/install', { method: 'POST' }),
  scenarios: () => request<{ scenarios: Scenario[] }>('/api/scenarios'),
  startRun: (mode: 'smoke' | 'full', scenarioIds: string[], launchMode: 'warm' | 'clean') =>
    request<RunStatus>('/api/run/start', {
      method: 'POST',
      body: JSON.stringify({ mode, scenario_ids: scenarioIds, launch_mode: launchMode }),
    }),
  stopRun: () => request<RunStatus>('/api/run/stop', { method: 'POST' }),
  runStatus: () => request<RunStatus>('/api/run/status'),
  runLog: () => request<{ text: string }>('/api/run/log'),
  recentRuns: () => request<{ runs: RecentRun[] }>('/api/runs/recent'),
  outputs: () => request<{ outputs: OutputFile[] }>('/api/outputs'),
};
