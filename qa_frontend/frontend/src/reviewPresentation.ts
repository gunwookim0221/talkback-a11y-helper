import type { MismatchSummary, QualityIssue, RecentBatch } from './api';
import { friendlyScenarioName } from './utils/formatters';

export type ReviewProjection = {
  available: boolean;
  items: QualityIssue[];
  qaReviewCount: number;
  automationDiagnosticCount: number;
  reason?: string;
};

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
