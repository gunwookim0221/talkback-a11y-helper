import type { MismatchSummary, QualityIssue, RecentBatch, RecentRun } from './api';
import { friendlyScenarioName } from './utils/formatters';

export type ReviewProjection = {
  available: boolean;
  items: QualityIssue[];
  qaReviewCount: number;
  automationDiagnosticCount: number;
  reason?: string;
};

export type ReviewRequestState =
  | { kind: 'loading' }
  | { kind: 'available'; summary: MismatchSummary }
  | { kind: 'unavailable' }
  | { kind: 'classification_unavailable' }
  | { kind: 'error'; message: string };

export function reviewStateFromSummary(summary: MismatchSummary): ReviewRequestState {
  const contract = summary.quality_issues_contract;
  if (!contract || contract.classification_available === false || contract.schema_version === 'legacy') {
    return { kind: 'classification_unavailable' };
  }
  return { kind: 'available', summary };
}

export function reviewStateFromError(error: unknown): ReviewRequestState {
  const message = error instanceof Error ? error.message : String(error ?? '');
  const normalized = message.trim().toLowerCase();
  if (normalized === 'xlsx output not available' || normalized.endsWith(': xlsx output not available')) {
    return { kind: 'unavailable' };
  }
  return { kind: 'error', message: message || 'Review request failed' };
}

export function reviewStateLabel(state: ReviewRequestState | undefined): string {
  if (!state || state.kind === 'loading') return '검토 상태 확인 중';
  if (state.kind === 'unavailable' || state.kind === 'classification_unavailable') {
    return '검토 상태 확인 불가';
  }
  if (state.kind === 'error') return '검토 상태 오류';
  const contract = state.summary.quality_issues_contract;
  const count = contract?.qa_review_count ?? state.summary.quality_issues?.length ?? 0;
  return count > 0 ? `검토 필요 ${count}건` : '검토할 항목 없음';
}

export function reviewLabelForRun(
  reviewArtifactAvailable: boolean,
  state: ReviewRequestState | undefined,
): string {
  if (!reviewArtifactAvailable) return '검토 상태 확인 불가';
  return reviewStateLabel(state);
}

export function getReviewProjection(payload: MismatchSummary | null | undefined): ReviewProjection {
  if (!payload) {
    return {
      available: false,
      items: [],
      qaReviewCount: 0,
      automationDiagnosticCount: 0,
      reason: '검토 분류 결과를 불러오지 못했습니다.',
    };
  }

  const contract = payload.quality_issues_contract;
  if (!contract || contract.classification_available === false || contract.schema_version === 'legacy') {
    return {
      available: false,
      items: [],
      qaReviewCount: 0,
      automationDiagnosticCount: 0,
      reason: '이 실행에는 QA Review 분류 정보가 없어 검토 상태를 확인할 수 없습니다.',
    };
  }

  return {
    available: true,
    items: Array.isArray(payload.quality_issues) ? payload.quality_issues : [],
    qaReviewCount: contract.qa_review_count ?? payload.quality_issues?.length ?? 0,
    automationDiagnosticCount: contract.automation_diagnostic_count
      ?? payload.automation_diagnostics?.length
      ?? 0,
  };
}

export function getBatchReviewProjection(batch: RecentBatch | null | undefined): ReviewProjection {
  if (!batch || !Array.isArray(batch.devices) || batch.devices.length === 0) {
    return {
      available: false,
      items: [],
      qaReviewCount: 0,
      automationDiagnosticCount: 0,
      reason: '이 실행의 QA Review projection을 찾을 수 없습니다.',
    };
  }

  const items: QualityIssue[] = [];
  let automationDiagnosticCount = 0;
  for (const device of batch.devices) {
    const contract = device.quality_issues_contract;
    if (!contract || contract.classification_available === false || contract.schema_version === 'legacy') {
      return {
        available: false,
        items: [],
        qaReviewCount: 0,
        automationDiagnosticCount: 0,
        reason: '이 실행에는 QA Review 분류 정보가 없어 검토 상태를 확인할 수 없습니다.',
      };
    }
    if (Array.isArray(device.quality_issues)) items.push(...device.quality_issues);
    automationDiagnosticCount += contract.automation_diagnostic_count
      ?? device.automation_diagnostics?.length
      ?? 0;
  }
  return {
    available: true,
    items,
    qaReviewCount: batch.devices.reduce(
      (total, device) => total + (device.quality_issues_contract?.qa_review_count ?? device.quality_issues?.length ?? 0),
      0,
    ),
    automationDiagnosticCount,
  };
}

export function reviewCount(projection: ReviewProjection): number {
  return projection.qaReviewCount;
}

export function reviewScenarioName(item: QualityIssue): string {
  return friendlyScenarioName(item.scenario_id, item.plugin_name);
}

export function evidenceText(value: string | null | undefined, kind: 'visible' | 'speech'): string {
  if (String(value ?? '').trim()) return String(value);
  return kind === 'visible' ? '화면 텍스트 없음' : '발화 관측 안 됨';
}

export function reviewReason(item: QualityIssue): string {
  if (item.review_note) return item.review_note;
  if (item.failure_reason) {
    const readable = item.failure_reason.replace(/_/g, ' ').trim();
    if (readable) return readable.charAt(0).toUpperCase() + readable.slice(1);
  }
  const labels: Record<string, string> = {
    EMPTY_VISIBLE: '화면 텍스트 확인 필요',
    EMPTY_SPEECH: 'TalkBack 발화 확인 필요',
    TEXT_MISMATCH: '화면 텍스트와 발화 비교 필요',
    LABEL_MISMATCH: '접근성 이름 비교 필요',
    SPOKEN_MISMATCH: 'TalkBack 발화 비교 필요',
    MISMATCH: '화면과 발화 비교 필요',
  };
  return labels[item.mismatch_type] || '화면과 발화 비교 필요';
}

export function reviewStatus(item: QualityIssue): string {
  if (item.validator_status === 'CLASSIFICATION_UNAVAILABLE') return '검토 상태 확인 불가';
  return item.validator_status === 'QA_REVIEW' ? '미검토' : '검토 상태 확인 불가';
}

export function historyExecutionLabel(state: string | null | undefined): string {
  const normalized = String(state ?? '').toLowerCase();
  if (['success', 'finished', 'passed', 'completed'].includes(normalized)) return '완료';
  if (['stopped', 'partial'].includes(normalized)) return '실행 중단';
  if (['failed', 'error'].includes(normalized)) return '실행 오류';
  if (normalized === 'running') return '실행 중';
  return '상태 확인 필요';
}

export function historyExecutionClass(state: string | null | undefined): string {
  const label = historyExecutionLabel(state);
  if (label === '완료') return 'healthOk';
  if (label === '실행 오류') return 'healthBad';
  return 'healthWarn';
}

export function historyScopeLabel(
  mode: string | null | undefined,
  totalScenarios: number | null | undefined,
  scenarioIds: readonly string[] | null | undefined,
  fullValidationScenarioIds: readonly string[] = [],
): string {
  const count = Number(totalScenarios ?? scenarioIds?.length ?? 0);
  const selected = scenarioIds ?? [];
  const isFull = mode === 'full'
    && fullValidationScenarioIds.length > 0
    && selected.length === fullValidationScenarioIds.length
    && selected.every((id) => fullValidationScenarioIds.includes(id));
  const scope = isFull || (mode === 'full' && selected.length === 0 && count > 0) ? 'Full Validation' : 'Custom Run';
  return `${scope} · ${count || '-'} scenarios`;
}

export function historyDeviceLabel(models: readonly string[] | null | undefined): string {
  const labels = (models ?? []).map((model) => String(model || '').trim()).filter(Boolean);
  if (labels.length === 0) return 'Current device';
  if (labels.length <= 2) return labels.join(' + ');
  return `${labels.slice(0, 2).join(' + ')} + ${labels.length - 2}`;
}

export type UnifiedHistoryItem =
  | {
      key: string;
      source: 'standalone';
      timestamp: string | null;
      timestampMs: number | null;
      state: string;
      mode: string;
      scenarioIds: string[];
      totalScenarios: number;
      deviceModels: string[];
      durationSeconds: number | null;
      raw: RecentRun;
    }
  | {
      key: string;
      source: 'batch';
      timestamp: string | null;
      timestampMs: number | null;
      state: string;
      mode: string;
      scenarioIds: string[];
      totalScenarios: number;
      deviceModels: string[];
      durationSeconds: number | null;
      raw: RecentBatch;
    };

const UNIFIED_HISTORY_LIMIT = 20;

function parseStableHistoryTimestamp(value: string | null | undefined): number | null {
  const match = String(value ?? '').match(/(?:^|_)(\d{8})_(\d{6})$/);
  if (!match) return null;
  const [, datePart, timePart] = match;
  const year = Number(datePart.slice(0, 4));
  const month = Number(datePart.slice(4, 6));
  const day = Number(datePart.slice(6, 8));
  const hour = Number(timePart.slice(0, 2));
  const minute = Number(timePart.slice(2, 4));
  const second = Number(timePart.slice(4, 6));
  const date = new Date(year, month - 1, day, hour, minute, second);
  if (
    date.getFullYear() !== year
    || date.getMonth() !== month - 1
    || date.getDate() !== day
    || date.getHours() !== hour
    || date.getMinutes() !== minute
    || date.getSeconds() !== second
  ) return null;
  const timestamp = date.getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function parseHistoryTimestamp(value: string | null | undefined, fallback?: string | null): number | null {
  const parsed = value ? Date.parse(value) : Number.NaN;
  if (Number.isFinite(parsed)) return parsed;
  return parseStableHistoryTimestamp(fallback);
}

export function normalizeUnifiedHistory(
  recentRuns: readonly RecentRun[] = [],
  recentBatches: readonly RecentBatch[] = [],
  limit = UNIFIED_HISTORY_LIMIT,
): UnifiedHistoryItem[] {
  const standaloneItems: UnifiedHistoryItem[] = recentRuns.map((run) => ({
    key: `standalone:${run.run_id}`,
    source: 'standalone' as const,
    timestamp: run.started_at || null,
    timestampMs: parseHistoryTimestamp(run.started_at, run.run_id),
    state: run.process_status || run.status || 'unknown',
    mode: run.mode,
    scenarioIds: [...(run.scenario_ids ?? [])],
    totalScenarios: Number(run.total_scenarios ?? run.scenario_ids?.length ?? 0),
    deviceModels: [],
    durationSeconds: Number.isFinite(run.duration_seconds) ? run.duration_seconds : null,
    raw: run,
  }));
  const batchItems: UnifiedHistoryItem[] = recentBatches.map((batch) => ({
    key: `batch:${batch.batch_id}`,
    source: 'batch' as const,
    timestamp: batch.created_at || null,
    timestampMs: parseHistoryTimestamp(batch.created_at, batch.batch_id),
    state: batch.state || 'unknown',
    mode: batch.mode || 'unknown',
    scenarioIds: [...(batch.scenario_ids ?? [])],
    totalScenarios: Number(
      batch.scenario_ids?.length
        || batch.devices?.[0]?.total_scenarios
        || 0,
    ),
    deviceModels: (batch.devices ?? []).map((device) => device.model).filter(Boolean),
    durationSeconds: typeof batch.duration_seconds === 'number' && Number.isFinite(batch.duration_seconds)
      ? batch.duration_seconds
      : null,
    raw: batch,
  }));

  const unique = new Map<string, UnifiedHistoryItem>();
  [...standaloneItems, ...batchItems].forEach((item) => {
    if (!unique.has(item.key)) unique.set(item.key, item);
  });

  return [...unique.values()]
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftTimestamp = left.item.timestampMs;
      const rightTimestamp = right.item.timestampMs;
      if (leftTimestamp === null && rightTimestamp === null) return left.index - right.index;
      if (leftTimestamp === null) return 1;
      if (rightTimestamp === null) return -1;
      return rightTimestamp - leftTimestamp || left.index - right.index;
    })
    .slice(0, Math.max(0, limit))
    .map(({ item }) => item);
}
