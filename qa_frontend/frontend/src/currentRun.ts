import type { BatchDeviceStatus, BatchStatus, RunStatus, RuntimeDashboard } from './api';
import { getDevicePluginName } from './utils/devicePluginMeta';
import { getLifePluginName } from './utils/lifePluginMeta';
import { getNavigationName } from './utils/navigationMeta';

export type CurrentRunState = 'idle' | 'running' | 'finished' | 'stopped' | 'failed' | 'error';

export type CurrentRunDevice = {
  readonly serial: string;
  readonly model: string;
  readonly state: string;
  readonly statusLabel: string;
  readonly progressLabel: string;
  readonly completedScenarios: number;
  readonly totalScenarios: number;
  readonly currentScenarioId: string | null;
  readonly currentScenarioLabel: string | null;
  readonly technicalError: string | null;
};

export type CurrentRunInput = {
  readonly batchStatus: BatchStatus | null;
  readonly status: RunStatus | null;
  readonly dashboard: RuntimeDashboard | null;
  readonly runLabel: string;
  readonly fullValidationScenarioIds?: readonly string[];
  readonly nowMs: number;
};

export type CurrentRunProjection = {
  readonly active: boolean;
  readonly state: CurrentRunState;
  readonly runLabel: string;
  readonly runId: string | null;
  readonly primaryProgressLabel: string | null;
  readonly completedScenarios: number;
  readonly totalScenarios: number;
  readonly finishedDevices: number;
  readonly totalDevices: number;
  readonly currentScenarioId: string | null;
  readonly currentScenarioLabel: string | null;
  readonly elapsedSeconds: number;
  readonly elapsedLabel: string;
  readonly devices: readonly CurrentRunDevice[];
  readonly actionableWarning: string | null;
  readonly technicalError: string | null;
  readonly technicalDetails: readonly string[];
};

const TERMINAL_DEVICE_STATES = new Set(['passed', 'failed', 'skipped', 'error', 'stopped']);
const HEALTHY_PREFLIGHT_STATES = new Set(['PASS', 'OK', 'READY', 'ENABLED', 'SUCCESS']);

function normalizeRunState(value: string | null | undefined): CurrentRunState {
  switch (value) {
    case 'running':
      return 'running';
    case 'finished':
      return 'finished';
    case 'stopped':
      return 'stopped';
    case 'failed':
      return 'failed';
    case 'error':
      return 'error';
    default:
      return 'idle';
  }
}

function deviceStatusLabel(state: string): string {
  switch (state) {
    case 'running':
      return 'Running';
    case 'pending':
      return 'Queued';
    case 'passed':
      return 'Completed';
    case 'failed':
    case 'error':
      return 'Failed';
    case 'stopped':
      return 'Stopped';
    case 'skipped':
      return 'Skipped';
    default:
      return state || 'Unknown';
  }
}

export function scenarioDisplayName(scenarioId: string | null, providedName: string | null): string | null {
  if (!scenarioId) return providedName?.trim() || null;
  const canonicalName = getDevicePluginName(scenarioId) ?? getLifePluginName(scenarioId) ?? getNavigationName(scenarioId);
  if (canonicalName) return canonicalName;
  const trimmedName = providedName?.trim();
  return trimmedName && trimmedName !== scenarioId ? trimmedName : scenarioId;
}

export function formatElapsedDuration(seconds: number): string {
  const normalized = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(normalized / 3600);
  const minutes = Math.floor((normalized % 3600) / 60);
  const remaining = normalized % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  if (minutes > 0) return `${minutes}m ${remaining}s`;
  return `${remaining}s`;
}

function elapsedSeconds(
  startedAt: string | null | undefined,
  finishedAt: string | null | undefined,
  nowMs: number,
  fallbackSeconds: number,
): number {
  const startedMs = startedAt ? Date.parse(startedAt) : NaN;
  if (!Number.isFinite(startedMs)) return Math.max(0, Math.floor(fallbackSeconds));
  const parsedFinishedMs = finishedAt ? Date.parse(finishedAt) : NaN;
  const endMs = Number.isFinite(parsedFinishedMs) ? parsedFinishedMs : nowMs;
  return Math.max(0, Math.floor((endMs - startedMs) / 1000));
}

function scenarioProgressLabel(completed: number, total: number): string {
  return total > 0 ? `${completed} / ${total} scenarios` : 'Progress unavailable';
}

function projectDevice(device: BatchDeviceStatus): CurrentRunDevice {
  const progress = device.progress;
  const current = device.current;
  const currentScenarioId = ['running', 'pending'].includes(device.state)
    ? current?.current_scenario_id ?? null
    : null;
  return {
    serial: device.serial,
    model: device.model || 'Android device',
    state: device.state,
    statusLabel: deviceStatusLabel(device.state),
    progressLabel: scenarioProgressLabel(progress?.completed_scenarios ?? 0, progress?.selected_scenarios ?? progress?.total_scenarios ?? 0),
    completedScenarios: progress?.completed_scenarios ?? 0,
    totalScenarios: progress?.selected_scenarios ?? progress?.total_scenarios ?? 0,
    currentScenarioId,
    currentScenarioLabel: scenarioDisplayName(currentScenarioId, current?.current_scenario_name ?? null),
    technicalError: device.error ?? null,
  };
}

function isUnhealthy(value: string | null | undefined): boolean {
  const normalized = String(value ?? '').trim().toUpperCase();
  return Boolean(normalized) && !HEALTHY_PREFLIGHT_STATES.has(normalized);
}

function actionableWarning(batchStatus: BatchStatus | null, status: RunStatus | null, state: CurrentRunState): string | null {
  if (state === 'stopped') return 'Validation was stopped before completion.';
  if (state === 'failed') return 'Validation failed before completion.';
  if (state === 'error') return 'Validation encountered an error before completion.';
  const preflight = batchStatus?.logs?.latest_preflight_status;
  if (isUnhealthy(preflight?.device_connected)) return 'Device connection was lost.';
  if (isUnhealthy(preflight?.helper)) return 'Helper connection failed.';
  if (isUnhealthy(preflight?.talkback)) return 'TalkBack is not ready.';
  if (status?.state === 'error') return 'Validation could not continue.';
  return null;
}

function batchTechnicalError(batchStatus: BatchStatus | null): string | null {
  const currentDevice = batchStatus?.devices.find((device) => device.serial === batchStatus.current_device);
  return currentDevice?.error ?? batchStatus?.devices.find((device) => device.error)?.error ?? null;
}

export function shouldUseBatch(batch: BatchStatus | null, status: RunStatus | null): boolean {
  if (!batch || !(batch.batch_id || batch.state !== 'idle' || batch.devices.length > 0)) return false;
  const batchState = normalizeRunState(batch.batch?.state ?? batch.state);
  const statusState = normalizeRunState(status?.state);
  if (batchState === 'running') return true;
  if (statusState === 'running') return false;
  if (batchState === 'idle') return false;
  if (statusState === 'idle') return true;

  const batchStartedMs = batch.batch?.started_at ? Date.parse(batch.batch.started_at) : NaN;
  const statusStartedMs = status?.started_at ? Date.parse(status.started_at) : NaN;
  if (Number.isFinite(batchStartedMs) && Number.isFinite(statusStartedMs)) return batchStartedMs >= statusStartedMs;
  return true;
}

function isFullValidationSelection(scenarioIds: readonly string[], fullValidationScenarioIds: readonly string[]): boolean {
  if (scenarioIds.length !== fullValidationScenarioIds.length || scenarioIds.length === 0) return false;
  const fullIds = new Set(fullValidationScenarioIds);
  return scenarioIds.every((scenarioId) => fullIds.has(scenarioId));
}

function projectedRunLabel(input: CurrentRunInput, batch: BatchStatus | null): string {
  const mode = batch?.mode ?? input.status?.mode;
  if (mode === 'smoke') return 'Quick Smoke';
  const fullValidationScenarioIds = input.fullValidationScenarioIds ?? [];
  const statusScenarioIds = input.status?.scenario_ids ?? [];
  if (isFullValidationSelection(statusScenarioIds, fullValidationScenarioIds)) return 'Full Validation';
  if (batch?.progress?.selected_scenarios === fullValidationScenarioIds.length && fullValidationScenarioIds.length > 0) {
    return 'Full Validation';
  }
  if (mode === 'full' && (statusScenarioIds.length > 0 || batch?.progress?.selected_scenarios !== undefined)) return 'Custom Run';
  return input.runLabel;
}

export function projectCurrentRun(input: CurrentRunInput): CurrentRunProjection {
  const batch = input.batchStatus;
  const useBatch = shouldUseBatch(batch, input.status);
  const runLabel = projectedRunLabel(input, useBatch ? batch : null);
  if (useBatch && batch) {
    const state = normalizeRunState(batch.batch?.state ?? batch.state);
    const devices = batch.devices.map(projectDevice);
    const totalDevices = batch.batch?.total_devices ?? devices.length;
    const finishedDevices = batch.batch?.finished_devices ?? devices.filter((device) => TERMINAL_DEVICE_STATES.has(device.state)).length;
    const progress = batch.progress;
    const totalScenarios = progress?.selected_scenarios ?? progress?.total_scenarios ?? 0;
    const completedScenarios = progress?.completed_scenarios ?? 0;
    const currentScenarioId = state === 'running' ? batch.current?.current_scenario_id ?? null : null;
    const currentScenarioLabel = currentScenarioId
      ? scenarioDisplayName(currentScenarioId, batch.current?.current_scenario_name ?? null)
      : state === 'running' ? 'Preparing next scenario…' : null;
    const primaryProgressLabel = totalDevices > 1
      ? `${finishedDevices} / ${totalDevices} devices completed`
      : scenarioProgressLabel(completedScenarios, totalScenarios);
    const technicalDetails = [
      `Batch ID: ${batch.batch_id ?? '-'}`,
      `State: ${batch.state}`,
      `Current device: ${batch.current_device ?? '-'}`,
      `Observed scenarios: ${progress?.observed_scenarios ?? 0}`,
      `Runtime events: ${progress?.observed_runtime_events ?? 0}`,
      `Latest log: ${batch.logs?.latest_log_line ?? '-'}`,
    ];
    const startedAt = batch.batch?.started_at;
    const finishedAt = batch.batch?.finished_at;
    const elapsed = elapsedSeconds(startedAt, finishedAt, input.nowMs, 0);
    return {
      active: state === 'running', state, runLabel, runId: batch.batch_id,
      primaryProgressLabel, completedScenarios, totalScenarios, finishedDevices, totalDevices,
      currentScenarioId, currentScenarioLabel, elapsedSeconds: elapsed, elapsedLabel: formatElapsedDuration(elapsed), devices,
      actionableWarning: actionableWarning(batch, null, state), technicalError: batchTechnicalError(batch), technicalDetails,
    };
  }

  const statusState = normalizeRunState(input.status?.state);
  const totalScenarios = Math.max(input.dashboard?.scenario_progress.length ?? 0, input.status?.scenario_ids.length ?? 0);
  const completedScenarios = input.dashboard?.completed_or_terminal_scenarios ?? input.dashboard?.completed_scenarios ?? 0;
  const currentScenarioId = statusState === 'running' ? input.dashboard?.current_scenario ?? null : null;
  const currentScenarioLabel = currentScenarioId ? scenarioDisplayName(currentScenarioId, currentScenarioId) : statusState === 'running' ? 'Preparing next scenario…' : null;
  const elapsed = elapsedSeconds(input.status?.started_at, input.status?.finished_at, input.nowMs, input.dashboard?.elapsed_seconds ?? 0);
  const technicalDetails = [
    `Run ID: ${input.status?.run_id ?? input.dashboard?.run_id ?? '-'}`,
    `State: ${input.status?.state ?? input.dashboard?.state ?? '-'}`,
    `Foreground package: ${input.status?.foreground_package ?? '-'}`,
    `Preflight: ${input.status?.preflight_state ?? '-'}`,
    `Latest scenario: ${input.dashboard?.current_scenario ?? '-'}`,
  ];
  return {
    active: statusState === 'running', state: statusState, runLabel,
    runId: input.status?.run_id ?? input.dashboard?.run_id ?? null,
    primaryProgressLabel: totalScenarios > 0 ? scenarioProgressLabel(completedScenarios, totalScenarios) : null,
    completedScenarios, totalScenarios, finishedDevices: statusState === 'finished' ? 1 : 0, totalDevices: 1,
    currentScenarioId, currentScenarioLabel, elapsedSeconds: elapsed, elapsedLabel: formatElapsedDuration(elapsed), devices: [],
    actionableWarning: actionableWarning(null, input.status, statusState), technicalError: input.status?.error ?? null, technicalDetails,
  };
}
