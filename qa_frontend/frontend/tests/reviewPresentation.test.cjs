const test = require('node:test');
const assert = require('node:assert/strict');

const {
  evidenceText,
  getReviewProjection,
  historyDeviceLabel,
  historyExecutionLabel,
  historyScopeLabel,
  reviewLabelForRun,
  reviewReason,
  reviewScenarioName,
  reviewStateFromError,
  reviewStateFromSummary,
  reviewStateLabel,
  reviewStatus,
} = require('../.test-dist/reviewPresentation.js');
const { formatValidatorDuration } = require('../.test-dist/utils/formatters.js');

function payload(overrides = {}) {
  return {
    summary: {
      fail_count: 1,
      issue_count: 0,
      review_count: 1,
      clean_count: 0,
      matched: 0,
      true_mismatch: 1,
      empty_speech: 0,
      empty_visible: 0,
      review: 0,
      runtime_warning: 0,
    },
    scenario_summary: [],
    signals: [],
    quality_issues: [{
      scenario_id: 'device_water_leak_sensor_plugin',
      plugin_name: 'Water Leak Sensor',
      step: '2',
      visible_label: '',
      merged_announcement: '',
      mismatch_type: 'EMPTY_VISIBLE',
      final_result: 'FAIL',
      raw_final_result: 'FAIL',
      failure_reason: 'speech_visible_diverged',
      validator_status: 'QA_REVIEW',
      crop_path: 'qa_frontend_runs/run/crops/water-leak-step-2.png',
    }],
    automation_diagnostics: [{ scenario_id: 'automation', step: '1' }],
    quality_issues_contract: {
      schema_version: 'quality-issues-v1',
      classification_source: 'review_workbook_contract',
      qa_review_count: 1,
      automation_diagnostic_count: 1,
    },
    ...overrides,
  };
}

test('QA Review projection excludes automation diagnostics and preserves crop identity', () => {
  const projection = getReviewProjection(payload());
  assert.equal(projection.available, true);
  assert.equal(projection.items.length, 1);
  assert.equal(projection.automationDiagnosticCount, 1);
  assert.equal(projection.items[0].crop_path, 'qa_frontend_runs/run/crops/water-leak-step-2.png');
});

test('zero and multiple QA Review items retain authoritative count and separate evidence paths', () => {
  const empty = getReviewProjection(payload({
    quality_issues: [],
    quality_issues_contract: {
      schema_version: 'quality-issues-v1',
      qa_review_count: 0,
      automation_diagnostic_count: 2,
    },
  }));
  assert.equal(empty.available, true);
  assert.equal(empty.items.length, 0);
  assert.equal(empty.automationDiagnosticCount, 2);

  const multiple = getReviewProjection(payload({
    quality_issues: [
      ...payload().quality_issues,
      { ...payload().quality_issues[0], scenario_id: 'device_smoke_sensor_plugin', crop_path: 'qa-run/crops/smoke-step-4.png' },
    ],
    quality_issues_contract: { schema_version: 'quality-issues-v1', qa_review_count: 2 },
  }));
  assert.equal(multiple.items.length, 2);
  assert.notEqual(multiple.items[0].crop_path, multiple.items[1].crop_path);
  assert.equal(multiple.items[0].raw_final_result, 'FAIL');
});

test('historical classification unavailable does not become zero review items', () => {
  const projection = getReviewProjection(payload({
    quality_issues: [{ scenario_id: 'legacy', step: '1', final_result: 'FAIL' }],
    quality_issues_contract: { schema_version: 'legacy', classification_available: false },
  }));
  assert.equal(projection.available, false);
  assert.equal(projection.items.length, 0);
  assert.match(projection.reason, /분류 정보/);
});

test('friendly names, evidence fallbacks, status, and reason stay validator-facing', () => {
  const item = payload().quality_issues[0];
  assert.equal(reviewScenarioName(item), 'Water Leak Sensor');
  assert.equal(evidenceText(item.visible_label, 'visible'), '화면 텍스트 없음');
  assert.equal(evidenceText(item.merged_announcement, 'speech'), '발화 관측 안 됨');
  assert.equal(reviewStatus(item), '미검토');
  assert.equal(reviewReason(item), 'Speech visible diverged');
  assert.equal(reviewScenarioName({ scenario_id: 'future_scenario' }), 'future_scenario');
});

test('history labels distinguish execution state, scope, and multi-device summaries', () => {
  assert.equal(historyExecutionLabel('success'), '완료');
  assert.equal(historyExecutionLabel('failed'), '실행 오류');
  assert.equal(historyExecutionLabel('finished'), '완료');
  assert.equal(
    historyExecutionLabel({ state: 'finished', scenario_result_status: 'failed', return_code: 0 }.state),
    '완료',
  );
  assert.equal(historyExecutionLabel('stopped'), '실행 중단');
  assert.equal(historyExecutionLabel('error'), '실행 오류');
  assert.equal(
    historyScopeLabel('full', 3, ['home_main', 'devices_main', 'life_main'], ['home_main', 'devices_main', 'life_main']),
    'Full Validation · 3 scenarios',
  );
  assert.equal(
    historyScopeLabel('full', 1, ['home_main'], ['home_main', 'devices_main']),
    'Custom Run · 1 scenarios',
  );
  assert.equal(historyDeviceLabel(['Galaxy Z Flip6', 'Fold8', 'S25', 'A55']), 'Galaxy Z Flip6 + Fold8 + 2');
});

test('review state distinguishes active loading from unavailable artifacts and errors', () => {
  assert.equal(reviewStateLabel({ kind: 'loading' }), '검토 상태 확인 중');
  assert.equal(reviewLabelForRun(false, undefined), '검토 상태 확인 불가');
  assert.equal(reviewLabelForRun(false, { kind: 'loading' }), '검토 상태 확인 불가');
  assert.equal(reviewLabelForRun(true, undefined), '검토 상태 확인 중');
  assert.equal(
    reviewStateLabel(reviewStateFromError(new Error('404: xlsx output not available'))),
    '검토 상태 확인 불가',
  );
  assert.equal(reviewStateLabel(reviewStateFromError(new Error('network unavailable'))), '검토 상태 오류');
});

test('review state preserves authoritative available counts and legacy fallback', () => {
  assert.equal(reviewStateLabel(reviewStateFromSummary(payload())), '검토 필요 1건');
  assert.equal(
    reviewStateLabel(reviewStateFromSummary(payload({
      quality_issues: [],
      quality_issues_contract: { schema_version: 'quality-issues-v1', qa_review_count: 0 },
    }))),
    '검토할 항목 없음',
  );
  assert.equal(
    reviewStateLabel(reviewStateFromSummary(payload({
      quality_issues_contract: { schema_version: 'legacy', classification_available: false },
    }))),
    '검토 상태 확인 불가',
  );
});

test('validator duration keeps zero, seconds, minutes, hours, and unknown distinct', () => {
  assert.equal(formatValidatorDuration(0), '0초');
  assert.equal(formatValidatorDuration(32), '32초');
  assert.equal(formatValidatorDuration(59), '59초');
  assert.equal(formatValidatorDuration(60), '1분');
  assert.equal(formatValidatorDuration(125), '2분');
  assert.equal(formatValidatorDuration(9780), '2시간 43분');
  assert.equal(formatValidatorDuration(null), '시간 확인 불가');
  assert.equal(formatValidatorDuration(undefined), '시간 확인 불가');
});
