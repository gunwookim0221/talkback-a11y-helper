import { RecentRun, Scenario } from '../api';

export function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString();
}

export function formatDuration(seconds: number) {
  if (seconds <= 0) {
    return '0s';
  }
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes === 0) {
    return `${remaining}s`;
  }
  return `${minutes}m ${remaining}s`;
}

export function formatBytes(value: number) {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function healthClass(value: string | null | undefined) {
  const normalized = String(value ?? '').toLowerCase();
  if (['finished', 'passed', 'success', 'ok', 'enabled', 'cleared'].includes(normalized)) {
    return 'healthOk';
  }
  if ([
    'running',
    'queued',
    'unknown',
    'dismissed_unverified',
    'partial',
    'stopped',
    'warning',
    'disabled',
    'not_installed',
    'apk_not_found',
    'needs setup',
    'not_available',
    'not_available_candidate',
    'no_target_candidate',
  ].includes(normalized)) {
    return 'healthWarn';
  }
  if (['failed', 'error', 'blocked', 'adb_error', 'helper_error', 'uncleared'].includes(normalized)) {
    return 'healthBad';
  }
  return 'healthNeutral';
}

export function helperBadgeText(status: string | undefined) {
  switch (status) {
    case 'ok':
      return 'OK';
    case 'disabled':
      return 'Needs setup';
    case 'not_installed':
      return 'Not installed';
    case 'apk_not_found':
      return 'APK not found';
    case 'error':
      return 'Error';
    default:
      return status ?? 'unknown';
  }
}

export function scenarioRunText(run: RecentRun) {
  if (run.scenario_result_status === 'failed') {
    return `Scenario results failed (${run.failed_scenarios})`;
  }
  if ((run.availability_candidate_scenarios ?? 0) > 0) {
    const executed = run.executed_scenarios ?? run.completed_scenarios ?? 0;
    return `Executed ${executed}/${run.total_scenarios}, ${run.availability_candidate_scenarios} not available`;
  }
  if (run.scenario_result_status === 'passed') {
    return 'Scenario results passed';
  }
  if (run.scenario_result_status === 'warning') {
    return `Scenario results warning (${run.warning_scenarios ?? 0})`;
  }
  if (run.scenario_result_status === 'partial') {
    return `Partial (${run.completed_scenarios}/${run.total_scenarios})`;
  }
  return `Scenario results ${run.scenario_result_status}`;
}

export function resolveSmokeSteps(scenarioId: string) {
  if ([
    'global_nav_main',
    'home_main',
    'devices_main',
    'life_main',
    'routines_main',
    'menu_main',
    'settings_entry_example',
  ].includes(scenarioId)) {
    return 6;
  }
  if (scenarioId.startsWith('life_') || scenarioId.startsWith('device_')) {
    return 8;
  }
  return 8;
}

export function describeScenarioSteps(scenario: Scenario, mode: 'smoke' | 'full') {
  const sourceSteps = scenario.max_steps;
  if (mode === 'smoke') {
    const smokeSteps = resolveSmokeSteps(scenario.id);
    return `max_steps: ${smokeSteps}`;
  }
  return sourceSteps ? `max_steps: ${sourceSteps}` : 'max_steps: source config';
}

export function languageLabel(languageMode: string | null | undefined) {
  switch (languageMode) {
    case 'ko-KR':
      return 'Korean (ko-KR)';
    case 'en-US':
      return 'English (en-US)';
    case 'current':
      return 'Current device language';
    default:
      return languageMode ?? '-';
  }
}

export function scenarioReasonText(scenario: NonNullable<RecentRun['scenarios']>[number]) {
  return scenario.reason || scenario.stop_reason || scenario.traversal_result || '';
}
