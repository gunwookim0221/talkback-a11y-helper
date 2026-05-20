export type RunStatus = {
  state: 'idle' | 'running' | 'stopped' | 'finished' | 'error';
  run_id: string | null;
  mode: string | null;
  started_at: string | null;
  finished_at: string | null;
  returncode: number | null;
  error: string | null;
  scenario_ids: string[];
  scenario_selection_applied: boolean;
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
  startRun: (mode: 'smoke' | 'full', scenarioIds: string[]) =>
    request<RunStatus>('/api/run/start', {
      method: 'POST',
      body: JSON.stringify({ mode, scenario_ids: scenarioIds }),
    }),
  stopRun: () => request<RunStatus>('/api/run/stop', { method: 'POST' }),
  runStatus: () => request<RunStatus>('/api/run/status'),
  runLog: () => request<{ text: string }>('/api/run/log'),
  outputs: () => request<{ outputs: OutputFile[] }>('/api/outputs'),
};
