const test = require('node:test');
const assert = require('node:assert/strict');

const { normalizeUnifiedHistory } = require('../.test-dist/reviewPresentation.js');

function standalone(overrides = {}) {
  return {
    run_id: '20260822_163119',
    mode: 'full',
    scenario_ids: ['life_family_care_plugin'],
    status: 'failed',
    process_status: 'failed',
    scenario_result_status: 'failed',
    completed_scenarios: 0,
    failed_scenarios: 1,
    total_scenarios: 1,
    event_warning_count: 0,
    started_at: '2026-08-22T16:31:19+09:00',
    duration_seconds: 0,
    log_exists: true,
    log_filename: 'run.log',
    xlsx_exists: false,
    xlsx_filename: null,
    ...overrides,
  };
}

function batch(overrides = {}) {
  return {
    batch_id: 'batch_20260822_192125',
    state: 'finished',
    mode: 'full',
    scenario_ids: ['life_family_care_plugin'],
    created_at: '2026-08-22T19:21:25+09:00',
    duration_seconds: 607,
    device_count: 1,
    passed_count: 1,
    failed_count: 0,
    summary_path: 'qa_frontend_runs/batch/batch_summary.json',
    devices: [{
      serial: 'serial-1',
      model: 'Galaxy Z Flip6',
      state: 'passed',
      return_code: 0,
      quality_issues_contract: { schema_version: 'quality-issues-v1', qa_review_count: 0 },
    }],
    ...overrides,
  };
}

test('newer batch is first when compared with an older standalone run', () => {
  const items = normalizeUnifiedHistory([standalone()], [batch()]);
  assert.equal(items[0].source, 'batch');
  assert.equal(items[0].raw.batch_id, 'batch_20260822_192125');
  assert.equal(items[1].source, 'standalone');
});

test('newer standalone is first when compared with an older batch', () => {
  const items = normalizeUnifiedHistory(
    [standalone({ run_id: '20260822_200000', started_at: '2026-08-22T20:00:00+09:00' })],
    [batch({ batch_id: 'batch_20260822_192125', created_at: '2026-08-22T19:21:25+09:00' })],
  );
  assert.deepEqual(items.map((item) => item.source), ['standalone', 'batch']);
});

test('mixed history is globally sorted newest first and respects the unified limit', () => {
  const items = normalizeUnifiedHistory(
    [
      standalone({ run_id: '20260822_180000', started_at: '2026-08-22T18:00:00+09:00' }),
      standalone({ run_id: '20260822_120000', started_at: '2026-08-22T12:00:00+09:00' }),
    ],
    [
      batch({ batch_id: 'batch_20260822_190000', created_at: '2026-08-22T19:00:00+09:00' }),
      batch({ batch_id: 'batch_20260822_170000', created_at: '2026-08-22T17:00:00+09:00' }),
    ],
    3,
  );
  assert.deepEqual(items.map((item) => item.key), [
    'batch:batch_20260822_190000',
    'standalone:20260822_180000',
    'batch:batch_20260822_170000',
  ]);
});

test('malformed and missing timestamps are safe and sort after valid timestamps', () => {
  const items = normalizeUnifiedHistory([
    standalone({ run_id: 'not-a-timestamp', started_at: 'not-a-date' }),
    standalone({ run_id: 'unknown', started_at: null }),
    standalone({ run_id: '20260822_130000', started_at: '2026-08-22T13:00:00Z' }),
  ]);
  assert.deepEqual(items.map((item) => item.key), [
    'standalone:20260822_130000',
    'standalone:not-a-timestamp',
    'standalone:unknown',
  ]);
  assert.equal(items[1].timestampMs, null);
  assert.equal(items[2].timestampMs, null);
});

test('stable execution IDs provide a conservative timestamp fallback', () => {
  const items = normalizeUnifiedHistory([
    standalone({ run_id: '20260822_120000', started_at: null }),
    standalone({ run_id: '20260822_130000', started_at: '2026-08-22T13:00:00+09:00' }),
  ]);
  assert.deepEqual(items.map((item) => item.key), [
    'standalone:20260822_130000',
    'standalone:20260822_120000',
  ]);
});

test('source identity and source-specific raw review data are retained', () => {
  const run = standalone({ run_id: '20260822_160000' });
  const batchRun = batch();
  const items = normalizeUnifiedHistory([run], [batchRun]);
  const standaloneItem = items.find((item) => item.source === 'standalone');
  const batchItem = items.find((item) => item.source === 'batch');
  assert.equal(standaloneItem.raw, run);
  assert.equal(batchItem.raw, batchRun);
  assert.equal(batchItem.raw.devices[0].quality_issues_contract.qa_review_count, 0);
});

test('same source identity is deduplicated but same timestamp across sources is not', () => {
  const run = standalone({ run_id: '20260822_160000', started_at: '2026-08-22T16:00:00+09:00' });
  const batchRun = batch({ created_at: '2026-08-22T16:00:00+09:00' });
  const items = normalizeUnifiedHistory([run, { ...run }], [batchRun, { ...batchRun }]);
  assert.equal(items.length, 2);
  assert.deepEqual(items.map((item) => item.source).sort(), ['batch', 'standalone']);
});

test('normalized rows preserve execution state and duration inputs', () => {
  const items = normalizeUnifiedHistory(
    [standalone({ process_status: 'error', status: 'error', duration_seconds: 0 })],
    [batch({ state: 'finished', duration_seconds: 607 })],
  );
  const failed = items.find((item) => item.source === 'standalone');
  const passed = items.find((item) => item.source === 'batch');
  assert.equal(failed.state, 'error');
  assert.equal(failed.durationSeconds, 0);
  assert.equal(passed.state, 'finished');
  assert.equal(passed.durationSeconds, 607);
});
