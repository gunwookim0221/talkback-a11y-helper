import { useEffect, useState } from 'react';
import type { MismatchSummary, QualityIssue, RecentBatch, RecentRun } from '../api';
import { api } from '../api';

export type AutomationDiagnosticsPanelProps = {
  readonly run: RecentRun | null;
  readonly batchId?: string | null;
};

function batchDiagnostics(batch: RecentBatch | null): QualityIssue[] {
  return (batch?.devices ?? []).flatMap((device) => device.automation_diagnostics ?? []);
}

function batchDiagnosticCount(batch: RecentBatch | null, diagnostics: QualityIssue[]): number {
  const contracts = batch?.devices ?? [];
  return contracts.reduce(
    (total, device) => total + (device.quality_issues_contract?.automation_diagnostic_count ?? device.automation_diagnostics?.length ?? 0),
    diagnostics.length,
  ) - diagnostics.length;
}

export function AutomationDiagnosticsPanel({ run, batchId = null }: AutomationDiagnosticsPanelProps) {
  const [payload, setPayload] = useState<MismatchSummary | null>(null);
  const [batch, setBatch] = useState<RecentBatch | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let ignore = false;
    setPayload(null);
    setBatch(null);
    setError(false);

    if (batchId) {
      setLoading(true);
      api.recentBatches()
        .then((batches) => {
          if (!ignore) setBatch(batches.find((candidate) => candidate.batch_id === batchId) ?? null);
        })
        .catch(() => {
          if (!ignore) setError(true);
        })
        .finally(() => {
          if (!ignore) setLoading(false);
        });
      return () => { ignore = true; };
    }

    if (!run?.run_id || !run.xlsx_exists) {
      setLoading(false);
      return () => { ignore = true; };
    }

    setLoading(true);
    api.runMismatch(run.run_id)
      .then((nextPayload) => {
        if (!ignore) setPayload(nextPayload);
      })
      .catch(() => {
        if (!ignore) setError(true);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => { ignore = true; };
  }, [batchId, run?.run_id, run?.xlsx_exists]);

  const diagnostics = batchId ? batchDiagnostics(batch) : payload?.automation_diagnostics ?? [];
  const contractAvailable = batchId
    ? Boolean(batch?.devices?.length) && (batch?.devices ?? []).every((device) => {
      const contract = device.quality_issues_contract;
      return Boolean(contract) && contract.classification_available !== false && contract.schema_version !== 'legacy';
    })
    : Boolean(payload?.quality_issues_contract)
      && payload?.quality_issues_contract?.classification_available !== false
      && payload?.quality_issues_contract?.schema_version !== 'legacy';
  const count = batchId
    ? batchDiagnosticCount(batch, diagnostics)
    : payload?.quality_issues_contract?.automation_diagnostic_count ?? diagnostics.length;

  return (
    <section className="advancedInfoPanel" aria-labelledby="automation-diagnostics-title">
      <div className="advancedPanelHeader">
        <div>
          <h3 id="automation-diagnostics-title">Automation Diagnostics</h3>
          <p>자동화 진행/복구 진단이며 validator QA Review 항목에는 포함되지 않습니다.</p>
        </div>
        {run && <small>Run: {run.run_id}</small>}
        {batchId && <small>Batch: {batchId}</small>}
      </div>
      {!run && !batchId ? (
        <p className="advancedEmptyState">Recent Runs에서 실행을 선택하면 진단을 확인할 수 있습니다.</p>
      ) : loading ? (
        <p className="advancedEmptyState" role="status">Automation Diagnostics를 불러오는 중입니다…</p>
      ) : error || !contractAvailable ? (
        <p className="advancedEmptyState" role="status">자동화 진단 상태 확인 불가</p>
      ) : count === 0 ? (
        <p className="advancedEmptyState">자동화 진단이 없습니다.</p>
      ) : (
        <>
          <p className="advancedCount">자동화 진단 {count}건</p>
          <div className="automationDiagnosticList">
            {diagnostics.map((item, index) => (
              <article className="automationDiagnosticCard" key={`${item.scenario_id}-${item.step}-${index}`}>
                <strong>{item.plugin_name || item.scenario_id || 'Unknown scenario'}</strong>
                <span>Step {item.step || '-'}</span>
                <span>{item.failure_reason || item.mismatch_type || '진단 정보 확인 필요'}</span>
                <details>
                  <summary>Technical details</summary>
                  <dl>
                    <dt>Scenario ID</dt><dd>{item.scenario_id || '-'}</dd>
                    <dt>Diagnostic status</dt><dd>{item.validator_status || 'AUTOMATION_DIAGNOSTIC'}</dd>
                    <dt>Raw result</dt><dd>{item.raw_final_result || item.final_result || '-'}</dd>
                  </dl>
                </details>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
