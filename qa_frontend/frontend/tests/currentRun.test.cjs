const test = require('node:test');
const assert = require('node:assert/strict');

const {
  formatElapsedDuration,
  projectCurrentRun,
  scenarioDisplayName,
} = require('../.test-dist/currentRun.js');

const NOW = Date.parse('2026-08-22T03:24:00Z');

function batchFixture(overrides = {}) {
  return {
    batch_id: 'batch-1',
    state: 'running',
    mode: 'full',
    current_device: 'serial-1',
    devices: [],
    batch: {
      batch_id: 'batch-1',
      state: 'running',
      started_at: '2026-08-22T02:00:00Z',
      finished_at: null,
      total_devices: 1,
      finished_devices: 0,
      passed_devices: 0,
      failed_devices: 0,
      warning_devices: 0,
    },
    current: {
      current_device_serial: 'serial-1',
      current_device_model: 'Galaxy Z Flip6',
      current_device_state: 'running',
      current_scenario_id: 'life_air_care_plugin',
      current_scenario_name: 'life_air_care_plugin',
      current_scenario_runtime_state: 'running',
      current_scenario_state: 'running',
      latest_scenario_event: 'running',
      current_step_index: 4,
      current_step_label: null,
      current_step_action: null,
      current_step_target: null,
      current_step_result: null,
      current_navigation_result: null,
      current_navigation_detail: null,
      latest_step_log: null,
      current_step_log: null,
      latest_runtime_event: null,
    },
    progress: {
      selected_scenarios: 32,
      observed_scenarios: 19,
      total_scenarios: 32,
      completed_scenarios: 18,
      executed_scenarios: 18,
      not_available_scenarios: 0,
      not_available_candidate_scenarios: 0,
      no_target_candidate_scenarios: 0,
      availability_candidate_scenarios: 0,
      passed_scenarios: 17,
      failed_scenarios: 0,
      warning_scenarios: 1,
      observed_runtime_events: 190,
      observed_steps: 42,
      total_steps: 100,
      completed_steps: 42,
      pass_count: 17,
      warn_count: 1,
      fail_count: 0,
      review_count: 0,
    },
    logs: {
      latest_log_line: null,
      latest_preflight_status: {
        device_connected: 'PASS',
        screen_awake: 'PASS',
        unlock_swipe: 'PASS',
        app_foreground: 'PASS',
        helper: 'PASS',
        talkback: 'PASS',
      },
      latest_quality_event: null,
    },
    ...overrides,
  };
}

test('idle Current Run is compact and truthful', () => {
  const projection = projectCurrentRun({
    batchStatus: null,
    status: null,
    dashboard: null,
    runLabel: 'Full Validation',
    nowMs: NOW,
  });

  assert.equal(projection.state, 'idle');
  assert.equal(projection.active, false);
  assert.equal(projection.primaryProgressLabel, null);
  assert.deepEqual(projection.devices, []);
});

test('active batch uses completed scenarios, friendly scenario name, and elapsed time', () => {
  const fixture = batchFixture();
  const projection = projectCurrentRun({
    batchStatus: {
      ...fixture,
      devices: [{
        serial: 'serial-1', model: 'Galaxy Z Flip6', state: 'running', return_code: null,
        output_dir: '', started_at: '2026-08-22T02:00:00Z', finished_at: null,
        current: fixture.current, progress: fixture.progress, logs: fixture.logs,
      }],
    },
    status: null,
    dashboard: null,
    runLabel: 'Full Validation',
    nowMs: NOW,
  });

  assert.equal(projection.state, 'running');
  assert.equal(projection.primaryProgressLabel, '18 / 32 scenarios');
  assert.equal(projection.currentScenarioLabel, 'Air Care');
  assert.equal(projection.elapsedLabel, '1h 24m');
  assert.equal(projection.devices[0].progressLabel, '18 / 32 scenarios');
  assert.equal(projection.devices[0].currentScenarioLabel, 'Air Care');
});

test('observed counters do not replace completed progress', () => {
  const projection = projectCurrentRun({
    batchStatus: batchFixture(),
    status: null,
    dashboard: null,
    runLabel: 'Full Validation',
    nowMs: NOW,
  });

  assert.equal(projection.primaryProgressLabel, '18 / 32 scenarios');
  assert.notEqual(projection.primaryProgressLabel, '19 / 32 scenarios');
});

test('unknown scenario falls back to its ID and missing current scenario is conservative', () => {
  assert.equal(scenarioDisplayName('future_scenario', null), 'future_scenario');
  assert.equal(scenarioDisplayName('future_scenario', 'Future Scenario'), 'Future Scenario');

  const batch = batchFixture({
    current: { ...batchFixture().current, current_scenario_id: null, current_scenario_name: null },
  });
  const projection = projectCurrentRun({
    batchStatus: batch,
    status: null,
    dashboard: null,
    runLabel: 'Custom Run',
    nowMs: NOW,
  });

  assert.equal(projection.currentScenarioLabel, 'Preparing next scenario…');
});

test('partial active run retains the explicit Custom Run label', () => {
  const projection = projectCurrentRun({
    batchStatus: batchFixture(),
    status: null,
    dashboard: null,
    runLabel: 'Custom Run',
    nowMs: NOW,
  });

  assert.equal(projection.runLabel, 'Custom Run');
});

test('multi-device projection preserves per-device progress and completion state', () => {
  const devices = [
    {
      serial: 'serial-1', model: 'Galaxy Z Flip6', state: 'running', return_code: null,
      output_dir: '', started_at: '2026-08-22T02:00:00Z', finished_at: null,
      current: batchFixture().current, progress: batchFixture().progress, logs: batchFixture().logs,
    },
    {
      serial: 'serial-2', model: 'Galaxy Fold', state: 'passed', return_code: 0,
      output_dir: '', started_at: '2026-08-22T02:00:00Z', finished_at: '2026-08-22T03:00:00Z',
      current: { ...batchFixture().current, current_device_serial: 'serial-2', current_device_model: 'Galaxy Fold' },
      progress: { ...batchFixture().progress, completed_scenarios: 32, selected_scenarios: 32 }, logs: batchFixture().logs,
    },
    {
      serial: 'serial-3', model: 'Galaxy S25', state: 'pending', return_code: null,
      output_dir: '', started_at: null, finished_at: null,
      current: { ...batchFixture().current, current_device_serial: 'serial-3', current_device_model: 'Galaxy S25', current_scenario_id: null },
      progress: { ...batchFixture().progress, completed_scenarios: 0, selected_scenarios: 32 }, logs: batchFixture().logs,
    },
  ];
  const projection = projectCurrentRun({
    batchStatus: {
      ...batchFixture(),
      devices,
      batch: { ...batchFixture().batch, total_devices: 3, finished_devices: 1 },
    },
    status: null,
    dashboard: null,
    runLabel: 'Full Validation',
    nowMs: NOW,
  });

  assert.equal(projection.primaryProgressLabel, '1 / 3 devices completed');
  assert.equal(projection.devices.length, 3);
  assert.equal(projection.devices[1].statusLabel, 'Completed');
  assert.equal(projection.devices[1].progressLabel, '32 / 32 scenarios');
  assert.equal(projection.devices[2].statusLabel, 'Queued');
});

test('active single run wins over a stale finished batch', () => {
  const projection = projectCurrentRun({
    batchStatus: { ...batchFixture(), state: 'finished', batch: { ...batchFixture().batch, state: 'finished', finished_at: '2026-08-22T02:30:00Z' } },
    status: {
      state: 'running', run_id: 'run-new', mode: 'full', started_at: '2026-08-22T03:00:00Z', finished_at: null,
      scenario_ids: ['future_scenario'],
    },
    dashboard: { current_scenario: 'future_scenario', scenario_progress: [{ id: 'future_scenario', status: 'running' }], elapsed_seconds: 24 },
    runLabel: 'Custom Run',
    fullValidationScenarioIds: ['future_scenario'],
    nowMs: NOW,
  });

  assert.equal(projection.state, 'running');
  assert.equal(projection.active, true);
  assert.equal(projection.currentScenarioLabel, 'future_scenario');
  assert.equal(projection.runLabel, 'Full Validation');
});

test('active single run label ignores a stale batch mode', () => {
  const projection = projectCurrentRun({
    batchStatus: { ...batchFixture(), mode: 'smoke', state: 'finished', batch: { ...batchFixture().batch, state: 'finished', finished_at: '2026-08-22T02:30:00Z' } },
    status: {
      state: 'running', run_id: 'run-new', mode: 'full', started_at: '2026-08-22T03:00:00Z', finished_at: null,
      scenario_ids: ['future_scenario'],
    },
    dashboard: { current_scenario: 'future_scenario', scenario_progress: [{ id: 'future_scenario', status: 'running' }], elapsed_seconds: 24 },
    runLabel: 'Custom Run',
    fullValidationScenarioIds: ['future_scenario'],
    nowMs: NOW,
  });

  assert.equal(projection.state, 'running');
  assert.equal(projection.runLabel, 'Full Validation');
});

test('active batch ignores a stale single-run error', () => {
  const projection = projectCurrentRun({
    batchStatus: batchFixture(),
    status: {
      state: 'error', run_id: 'run-old', mode: 'full', started_at: '2026-08-22T01:00:00Z', finished_at: '2026-08-22T01:30:00Z',
      error: 'stale single-run error', scenario_ids: ['old_scenario'],
    },
    dashboard: null,
    runLabel: 'Full Validation',
    nowMs: NOW,
  });

  assert.equal(projection.state, 'running');
  assert.equal(projection.active, true);
  assert.equal(projection.actionableWarning, null);
});

test('terminal run label follows the payload instead of mutable setup state', () => {
  const projection = projectCurrentRun({
    batchStatus: { ...batchFixture(), mode: 'smoke', state: 'finished', batch: { ...batchFixture().batch, state: 'finished', finished_at: '2026-08-22T03:24:00Z' } },
    status: null,
    dashboard: null,
    runLabel: 'Custom Run',
    fullValidationScenarioIds: ['future_scenario'],
    nowMs: NOW,
  });

  assert.equal(projection.state, 'finished');
  assert.equal(projection.runLabel, 'Quick Smoke');
});

test('actionable device failure is promoted while raw diagnostics stay separate', () => {
  const failed = {
    ...batchFixture(),
    state: 'error',
    batch: { ...batchFixture().batch, state: 'failed', finished_at: '2026-08-22T03:24:00Z', failed_devices: 1 },
    devices: [{
      serial: 'serial-1', model: 'Galaxy Z Flip6', state: 'failed', return_code: 1,
      output_dir: '', started_at: '2026-08-22T02:00:00Z', finished_at: '2026-08-22T03:24:00Z',
      error: 'raw runner exception', current: batchFixture().current, progress: batchFixture().progress, logs: batchFixture().logs,
    }],
  };
  const projection = projectCurrentRun({
    batchStatus: failed,
    status: null,
    dashboard: null,
    runLabel: 'Full Validation',
    nowMs: NOW,
  });

  assert.equal(projection.state, 'failed');
  assert.equal(projection.actionableWarning, 'Validation failed before completion.');
  assert.equal(projection.technicalError, 'raw runner exception');
});

test('availability terminals count as completed when the runtime projection provides them', () => {
  const dashboard = {
    completed_or_terminal_scenarios: 3,
    completed_scenarios: 2,
    scenario_progress: [{ id: 'home_main', status: 'passed', steps: 4 }],
    elapsed_seconds: 42,
  };
  const projection = projectCurrentRun({
    batchStatus: null,
    status: {
      state: 'finished', run_id: 'run-1', mode: 'full', started_at: '2026-08-22T03:23:18Z', finished_at: '2026-08-22T03:24:00Z',
      scenario_ids: ['home_main', 'life_air_care_plugin', 'device_camera_plugin'],
    },
    dashboard,
    runLabel: 'Full Validation',
    nowMs: NOW,
  });

  assert.equal(projection.primaryProgressLabel, '3 / 3 scenarios');
});

test('elapsed duration formatting is human-readable', () => {
  assert.equal(formatElapsedDuration(0), '0s');
  assert.equal(formatElapsedDuration(8 * 60 + 42), '8m 42s');
  assert.equal(formatElapsedDuration(2 * 60 * 60 + 3 * 60), '2h 03m');
});
