import React, { useEffect, useState, useMemo } from 'react';
import { RecentRun, api, RecentBatch, RecentBatchDevice, CoverageProbeSummary, ShadowValidationSummary } from '../api';
import { CrashIssuesPanel } from './CrashIssuesPanel';
import { IdentityShadowCard } from './IdentityShadowCard';
import { formatTime, formatDuration, healthClass, scenarioRunText, languageLabel, scenarioReasonText } from '../utils/formatters';

type MismatchSummary = {
  summary: {
    matched: number;
    true_mismatch: number;
    empty_speech: number;
    empty_visible: number;
    review: number;
    runtime_warning: number;
    shadow_pass_count?: number;
    shadow_review_count?: number;
    shadow_warn_count?: number;
    shadow_fail_count?: number;
    focusable_required_expected_count?: number;
    focusable_required_covered_count?: number;
    focusable_required_missed_count?: number;
    focusable_review_expected_count?: number;
    focusable_review_unknown_count?: number;
    focusable_optional_expected_count?: number;
    focusable_coverage_rate?: number | null;
  };
  scenario_summary: Array<{
    scenario_id: string;
    plugin_name: string;
    matched: number;
    true_mismatch: number;
    empty_speech: number;
    empty_visible: number;
    review: number;
  runtime_warning: number;
    shadow_pass_count?: number;
    shadow_review_count?: number;
    shadow_warn_count?: number;
    shadow_fail_count?: number;
    scenario_shadow_verdict?: string;
    focusable_required_missed?: number;
    focusable_review_unknown?: number;
    focusable_coverage_rate?: number | null;
    status: 'fail' | 'issue' | 'review' | 'clean';
  }>;
  signals: Array<{ 
    scenario: string; 
    plugin_name: string;
    step: string;
    visible: string; 
    spoken: string; 
    mismatch_type: string; 
    final_result: string;
    shadow_verdict?: string;
    shadow_verdict_reason?: string;
    shadow_verdict_source?: string;
    scenario_shadow_verdict?: string;
    failure_reason: string;
    focus_confidence: string;
    repeat_count?: number;
    first_step?: string;
    last_step?: string;
    steps?: string;
    is_repeated_issue_group?: boolean;
    category: string; 
  }>;
  focusable_coverage?: {
    summary?: {
      focusable_required_expected_count?: number;
      focusable_required_covered_count?: number;
      focusable_required_missed_count?: number;
      focusable_review_expected_count?: number;
      focusable_review_unknown_count?: number;
      focusable_optional_expected_count?: number;
      focusable_coverage_rate?: number | null;
    };
    scenarios?: Array<{
      scenario_id: string;
      focusable_required_missed?: number;
      focusable_review_unknown?: number;
      focusable_coverage_rate?: number | null;
    }>;
    issues?: Array<{
      scenario_id: string;
      focusable_label: string;
      focusable_view_id?: string;
      focusable_taxonomy: string;
      focusable_coverage_status: string;
      focusable_coverage_reason?: string;
      focusable_taxonomy_reason?: string;
    }>;
  };
  coverage_probe?: CoverageProbeSummary | null;
};

export interface RecentRunsPanelProps {
  recentRuns: RecentRun[];
  selectedRecentRunId: string | null;
  setSelectedRecentRunId: (id: string | null) => void;
  selectedRecentRun: RecentRun | null;
  selectedFailedScenarios: NonNullable<RecentRun['scenarios']>;
  selectedWarningScenarios: NonNullable<RecentRun['scenarios']>;
  selectedPassedScenarios: NonNullable<RecentRun['scenarios']>;
}

export function RecentRunsPanel({
  recentRuns,
  selectedRecentRunId,
  setSelectedRecentRunId,
  selectedRecentRun,
  selectedFailedScenarios,
  selectedWarningScenarios,
  selectedPassedScenarios,
}: RecentRunsPanelProps) {
  const [mismatchSummaries, setMismatchSummaries] = useState<Record<string, MismatchSummary | null>>({});
  const [recentBatches, setRecentBatches] = useState<RecentBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);

  useEffect(() => {
    let timer: number;
    const fetchBatches = async () => {
      try {
        const res = await api.recentBatches();
        setRecentBatches(res);
      } catch (err) {
        // ignore
      }
      timer = window.setTimeout(fetchBatches, 5000);
    };
    fetchBatches();
    return () => window.clearTimeout(timer);
  }, []);

  const mismatchSummary = selectedRecentRun?.run_id ? mismatchSummaries[selectedRecentRun.run_id] : null;
  const selectedBatch = useMemo(() => recentBatches.find(b => b.batch_id === selectedBatchId), [recentBatches, selectedBatchId]);
  const [batchLogPreviews, setBatchLogPreviews] = useState<Record<string, string>>({});
  const [batchMismatchSummaries, setBatchMismatchSummaries] = useState<Record<string, MismatchSummary | null>>({});

  const resolveBatchDeviceId = (device: RecentBatchDevice) => {
    const outputDir = device.output_dir?.replace(/\\/g, '/');
    const leaf = outputDir?.split('/').filter(Boolean).pop();
    return leaf || `${device.model}_${device.serial}`;
  };

  useEffect(() => {
    if (!selectedBatch) {
      setBatchLogPreviews({});
      return;
    }
    
    const logFetches: Promise<void>[] = [];
    const newPreviews: Record<string, string> = {};
    selectedBatch.devices?.forEach(d => {
      let path = (d as any).runner_log_path || d.log_path;
      if (!path) {
        newPreviews[d.serial] = 'No log file found.';
      } else {
        logFetches.push(
          api.getBatchLogTail(path).then(res => {
            newPreviews[d.serial] = res.text || 'Empty log.';
          }).catch(err => {
            newPreviews[d.serial] = 'Error fetching log: ' + String(err);
          })
        );
      }
    });
  }, [selectedBatch]);

  const renderDeviceDetails = (runData: any, crashContext?: { runId: string; deviceId: string }) => {
    const failedScenarios = (runData?.scenarios || []).filter((s: any) => s.status === 'failed');
    const warningScenarios = (runData?.scenarios || []).filter((s: any) => s.status === 'warning');
    const unavailableScenarios = (runData?.scenarios || []).filter((s: any) => ['not_available', 'not_available_candidate', 'no_target_candidate'].includes(s.status));
    const passedScenarios = (runData?.scenarios || []).filter((s: any) => s.status === 'passed');
    const shadowScenarioById = new Map(
      (runData?.shadow_scenarios || [])
        .filter((item: any) => item?.scenario_id)
        .map((item: any) => [item.scenario_id, item])
    );
    const shadowQuality = runData?.shadow_quality;
    const focusableCoverage = runData?.focusable_coverage;
    const focusableSummary = focusableCoverage?.summary;
    const coverageProbe = (
      runData?.coverage_probe_summary ?? runData?.coverage_probe
    ) as CoverageProbeSummary | null | undefined;
    const shadowValidation = runData?.shadow_validation as ShadowValidationSummary | null | undefined;
    const probeCandidateCount = coverageProbe?.candidate_count ?? coverageProbe?.total_candidate_count ?? 0;
    const probeAttemptedCount = coverageProbe?.attempted_count ?? coverageProbe?.total_attempted_count ?? 0;
    const probeSuccessCount = coverageProbe?.success_count ?? coverageProbe?.total_success_count ?? 0;
    const probeFailedCount = coverageProbe?.failed_count ?? coverageProbe?.total_failed_count ?? 0;
    const probeDedupSkippedCount = (
      coverageProbe?.dedup_skipped_count ?? coverageProbe?.promotion_dedup_skipped_count ?? 0
    );
    const probeScreenSkippedCount = (
      coverageProbe?.screen_skipped_count ?? coverageProbe?.total_screen_skipped_count
    );
    const probeScenarioFilteredCount = (
      coverageProbe?.scenario_filtered_count ?? coverageProbe?.total_scenario_filtered_count
    );
    const coverageProbeUnavailableMessage = coverageProbe?.probe_enabled === false
      ? 'Runtime Probe: OFF'
      : coverageProbe?.probe_enabled === true
        ? 'Runtime Probe: ON, but no V8 probe artifacts were generated.'
        : 'Runtime Probe appears to be OFF for this run, or no V8 probe artifacts were generated.';
    const focusableIssues = runData?.focusable_issues || focusableCoverage?.issues || [];
    const focusableScenarioById = new Map(
      (focusableCoverage?.scenarios || runData?.shadow_scenarios || [])
        .filter((item: any) => item?.scenario_id)
        .map((item: any) => [item.scenario_id, item])
    );

    const scenarioShadowText = (scenario: any) => {
      const shadow = shadowScenarioById.get(scenario.id) as any;
      return shadow?.scenario_shadow_verdict ? `Shadow: ${shadow.scenario_shadow_verdict}` : null;
    };

    const scenarioCoverageText = (scenario: any) => {
      const coverage = focusableScenarioById.get(scenario.id) as any;
      const requiredMissed = Number(coverage?.focusable_required_missed || 0);
      const reviewUnknown = Number(coverage?.focusable_review_unknown || 0);
      if (!requiredMissed && !reviewUnknown) {
        return null;
      }
      return `Coverage: required misses ${requiredMissed}, review unknown ${reviewUnknown}`;
    };

    return (
      <div style={{ marginTop: '12px' }}>
        <details open>
          <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>Run Details</summary>
          <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', marginTop: '6px', paddingLeft: '8px' }}>
            Scenario-level result summary. This is separate from device result and TalkBack row quality.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingLeft: '8px', marginTop: '8px' }}>
            <details>
              <summary>Scenario Failed ({failedScenarios.length})</summary>
              <div className="scenarioDetailList">
                {failedScenarios.length ? (
                  failedScenarios.map((scenario: any) => (
                    <div key={scenario.id} className="scenarioDetailRow">
                      <strong>{scenario.id}</strong>
                      <small>reason={scenarioReasonText(scenario) || 'failed'}</small>
                      {scenarioShadowText(scenario) ? <small>{scenarioShadowText(scenario)}</small> : null}
                      {scenarioCoverageText(scenario) ? <small>{scenarioCoverageText(scenario)}</small> : null}
                    </div>
                  ))
                ) : (
                  <small>No failed scenarios.</small>
                )}
              </div>
            </details>
            <details>
              <summary>Scenario Warning ({warningScenarios.length})</summary>
              <div className="scenarioDetailList">
                {warningScenarios.length ? (
                  warningScenarios.map((scenario: any) => (
                    <div key={scenario.id} className="scenarioDetailRow">
                      <strong>{scenario.id}</strong>
                      <small>reason={scenarioReasonText(scenario) || 'warning'}</small>
                      {scenarioShadowText(scenario) ? <small>{scenarioShadowText(scenario)}</small> : null}
                      {scenarioCoverageText(scenario) ? <small>{scenarioCoverageText(scenario)}</small> : null}
                    </div>
                  ))
                ) : (
                  <small>No warning scenarios.</small>
                )}
              </div>
            </details>
            <details>
              <summary>Scenario Not Available ({unavailableScenarios.length})</summary>
              <div className="scenarioDetailList">
                {unavailableScenarios.length ? (
                  unavailableScenarios.map((scenario: any) => (
                    <div key={scenario.id} className="scenarioDetailRow">
                      <strong>{scenario.id}</strong>
                      <small>
                        {scenario.availability_status || scenario.status}
                        {scenario.availability_confidence ? ` · ${scenario.availability_confidence}` : ''}
                        {scenario.availability_target ? ` · target=${scenario.availability_target}` : ''}
                      </small>
                      <small>{scenario.availability_reason || scenarioReasonText(scenario) || 'not available candidate'}</small>
                      {scenarioShadowText(scenario) ? <small>{scenarioShadowText(scenario)}</small> : null}
                      {scenarioCoverageText(scenario) ? <small>{scenarioCoverageText(scenario)}</small> : null}
                    </div>
                  ))
                ) : (
                  <small>No not-available candidates.</small>
                )}
              </div>
            </details>
            <details>
              <summary>Scenario Passed ({passedScenarios.length})</summary>
              <div className="scenarioDetailList">
                {passedScenarios.length ? (
                  passedScenarios.map((scenario: any) => (
                    <div key={scenario.id} className="scenarioDetailRow">
                      <strong>{scenario.id}</strong>
                      {typeof scenario.steps === 'number' ? <small>{scenario.steps} steps</small> : null}
                      {scenarioShadowText(scenario) ? <small>{scenarioShadowText(scenario)}</small> : null}
                      {scenarioCoverageText(scenario) ? <small>{scenarioCoverageText(scenario)}</small> : null}
                    </div>
                  ))
                ) : (
                  <small>No passed scenarios.</small>
                )}
              </div>
            </details>
          </div>
        </details>

        {shadowValidation?.available && (
          <details open className="shadowValidationCard">
            <summary>
              V10 Shadow Validation
              <span className={`shadowStatusBadge shadowStatus-${shadowValidation.status}`}>
                {shadowValidation.status}
              </span>
            </summary>
            <div className="shadowValidationHint">
              Capability routing comparison only. Legacy remains authoritative.
            </div>
            <div className="shadowMetricGrid">
              {[
                ['Inventory', shadowValidation.inventory_count, 'neutral'],
                ['Identified', shadowValidation.identified_count, 'neutral'],
                ['Identify Unknown', shadowValidation.identify_unknown_count, 'unknown'],
                ['MATCH', shadowValidation.match_count, 'match'],
                ['UNKNOWN', shadowValidation.unknown_count, 'unknown'],
                ['AMBIGUOUS', shadowValidation.ambiguous_count, 'warning'],
                ['MISMATCH', shadowValidation.mismatch_count, 'warning'],
                ['FAILED', shadowValidation.failed_count, 'failed'],
                ['Promotion Eligible', shadowValidation.promotion_eligible_count, 'match'],
                ['Legacy Preserved', shadowValidation.legacy_preserved ? 'YES' : 'NO', shadowValidation.legacy_preserved ? 'match' : 'failed'],
                ['Runtime', shadowValidation.runtime_seconds == null ? '-' : formatDuration(Math.round(shadowValidation.runtime_seconds)), 'neutral'],
              ].map(([label, value, tone]) => (
                <div key={String(label)} className={`shadowMetric shadowMetric-${tone}`}>
                  <small>{label}</small>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>

            {(['MATCH', 'UNKNOWN', 'AMBIGUOUS', 'MISMATCH', 'FAILED'] as const).some(
              result => (shadowValidation.result_groups[result] || []).length > 0,
            ) && (
              <div className="shadowFamilyGroups">
                {(['MATCH', 'UNKNOWN', 'AMBIGUOUS', 'MISMATCH', 'FAILED'] as const).map(result => {
                  const families = shadowValidation.result_groups[result] || [];
                  if (!families.length) return null;
                  return (
                    <div key={result} className={`shadowFamilyGroup shadowFamily-${result.toLowerCase()}`}>
                      <strong>{result}</strong>
                      <span>{families.join(' · ')}</span>
                    </div>
                  );
                })}
              </div>
            )}

            {shadowValidation.promotion_readiness && (
              <div className="promotionReadiness">
                <div className="promotionReadinessHeader">
                  <strong>Promotion Readiness</strong>
                  <span className={`readinessBadge readiness-${shadowValidation.promotion_readiness.overall_status.toLowerCase()}`}>
                    {shadowValidation.promotion_readiness.overall_status}
                  </span>
                </div>
                <div className="promotionReadinessHint">
                  Evaluation only. Controlled routing remains disabled.
                </div>
                <div className="readinessCountGrid">
                  {(['READY', 'HOLD', 'BLOCKED', 'INSUFFICIENT_DATA', 'UNKNOWN_ONLY'] as const).map(status => (
                    <div key={status} className={`readinessCount readiness-${status.toLowerCase()}`}>
                      <small>{status.replace('_', ' ')}</small>
                      <strong>{shadowValidation.promotion_readiness?.status_counts[status] ?? 0}</strong>
                    </div>
                  ))}
                </div>
                <div className="readinessFamilyList">
                  {shadowValidation.promotion_readiness.families.map(item => (
                    <div key={item.plugin_family} className="readinessFamilyRow">
                      <strong>{item.plugin_family}</strong>
                      <span className={`readinessBadge readiness-${item.status.toLowerCase()}`}>
                        {item.status}
                      </span>
                      <small>
                        {item.ready_candidate ? 'READY CANDIDATE · ' : ''}
                        MATCH {item.counts.MATCH} · UNKNOWN {item.counts.UNKNOWN} ·
                        confidence {item.minimum_confidence} · {item.reason}
                      </small>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {shadowValidation.error && (
              <div className="shadowValidationError">
                {shadowValidation.error_stage ? `${shadowValidation.error_stage}: ` : ''}
                {shadowValidation.error}
              </div>
            )}

            {crashContext && (
              <div className="shadowArtifactActions">
                {shadowValidation.artifacts.report && (
                  <a
                    href={`/api/batch/file?path=${encodeURIComponent(shadowValidation.artifacts.report)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Shadow Report
                  </a>
                )}
                {shadowValidation.artifacts.compare && (
                  <a
                    href={`/api/batch/file?path=${encodeURIComponent(shadowValidation.artifacts.compare)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Compare JSON
                  </a>
                )}
                {shadowValidation.artifacts.readiness_report && (
                  <a
                    href={`/api/batch/file?path=${encodeURIComponent(shadowValidation.artifacts.readiness_report)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Readiness Report
                  </a>
                )}
                {shadowValidation.artifacts.readiness_json && (
                  <a
                    href={`/api/batch/file?path=${encodeURIComponent(shadowValidation.artifacts.readiness_json)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Readiness JSON
                  </a>
                )}
                {shadowValidation.artifacts.folder_available && (
                  <button
                    type="button"
                    onClick={() => {
                      api.openShadowFolder(crashContext.runId, crashContext.deviceId)
                        .catch(error => window.alert(`Unable to open shadow folder: ${String(error)}`));
                    }}
                  >
                    Open Shadow Folder
                  </button>
                )}
              </div>
            )}
          </details>
        )}
        
        {runData?.quality && (
          <details open style={{ marginTop: '16px' }}>
            <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>TalkBack Rows</summary>
            <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', marginTop: '4px' }}>
              Row / utterance-level quality counts from result rows. This is separate from scenario result status.
            </div>
            <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '8px' }}>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>FAIL</small>
                  <strong style={{ fontSize: '1.4em', color: runData.quality.fail > 0 ? 'var(--color-danger)' : 'inherit' }}>{runData.quality.fail}</strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>ISSUE</small>
                  <strong style={{ fontSize: '1.4em', color: runData.quality.issue > 0 ? 'var(--color-warning)' : 'inherit' }}>{runData.quality.issue}</strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>REVIEW</small>
                  <strong style={{ fontSize: '1.4em', color: runData.quality.review > 0 ? 'var(--color-neutral)' : 'inherit' }}>{runData.quality.review}</strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>CLEAN</small>
                  <strong style={{ fontSize: '1.4em', color: 'var(--color-success)' }}>{runData.quality.clean}</strong>
                </div>
              </div>
            </div>
          </details>
        )}

        {shadowQuality && (
          <details open style={{ marginTop: '16px' }}>
            <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>Shadow Verdict</summary>
            <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', marginTop: '4px' }}>
              Reporting-only V6 shadow quality signal. This does not change PASS/WARN/FAIL.
            </div>
            <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '8px' }}>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>Shadow Pass</small>
                  <strong style={{ fontSize: '1.4em', color: 'var(--color-success)' }}>{shadowQuality.pass ?? 0}</strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>Shadow Review</small>
                  <strong style={{ fontSize: '1.4em', color: 'var(--color-neutral)' }}>{shadowQuality.review ?? 0}</strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>Shadow Warn</small>
                  <strong style={{ fontSize: '1.4em', color: (shadowQuality.warn ?? 0) > 0 ? 'var(--color-warning)' : 'inherit' }}>{shadowQuality.warn ?? 0}</strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>Shadow Fail</small>
                  <strong style={{ fontSize: '1.4em', color: (shadowQuality.fail ?? 0) > 0 ? 'var(--color-danger)' : 'inherit' }}>{shadowQuality.fail ?? 0}</strong>
                </div>
              </div>
            </div>
          </details>
        )}

        {focusableSummary && (
          <details open style={{ marginTop: '16px' }}>
            <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>Focusable Coverage</summary>
            <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', marginTop: '4px' }}>
              Reporting-only V7 focusable coverage signal. This does not change PASS/WARN/FAIL.
            </div>
            <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', marginBottom: '8px' }}>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>Required Misses</small>
                  <strong style={{ fontSize: '1.4em', color: (focusableSummary.focusable_required_missed_count ?? 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>
                    {focusableSummary.focusable_required_missed_count ?? 0}
                  </strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>Review Unknown</small>
                  <strong style={{ fontSize: '1.4em', color: (focusableSummary.focusable_review_unknown_count ?? 0) > 0 ? 'var(--color-warning)' : 'inherit' }}>
                    {focusableSummary.focusable_review_unknown_count ?? 0}
                  </strong>
                </div>
                <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                  <small>Coverage Rate</small>
                  <strong style={{ fontSize: '1.4em' }}>
                    {typeof focusableSummary.focusable_coverage_rate === 'number' ? `${focusableSummary.focusable_coverage_rate}%` : '-'}
                  </strong>
                </div>
              </div>
              {focusableIssues.length > 0 ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                  <div className="scenarioDetailRow" style={{ alignItems: 'flex-start' }}>
                    <strong>Required Missing ({focusableIssues.filter((item: any) => item.focusable_taxonomy === 'REQUIRED').length})</strong>
                    {focusableIssues.filter((item: any) => item.focusable_taxonomy === 'REQUIRED').map((item: any, index: number) => (
                      <small key={`${item.scenario_id}-required-${index}`}>
                        {item.focusable_label || item.focusable_view_id || '-'} · {item.scenario_id}
                      </small>
                    ))}
                  </div>
                  <div className="scenarioDetailRow" style={{ alignItems: 'flex-start' }}>
                    <strong>Review Unknown ({focusableIssues.filter((item: any) => item.focusable_taxonomy === 'REVIEW').length})</strong>
                    {focusableIssues.filter((item: any) => item.focusable_taxonomy === 'REVIEW').map((item: any, index: number) => (
                      <small key={`${item.scenario_id}-review-${index}`}>
                        {item.focusable_label || item.focusable_view_id || '-'} · {item.scenario_id}
                      </small>
                    ))}
                  </div>
                </div>
              ) : (
                <small>No required misses or review unknown focusables.</small>
              )}
            </div>
          </details>
        )}

        <details open style={{ marginTop: '16px' }}>
          <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>
            Coverage Probe
            {coverageProbe?.available && coverageProbe.source && (
              <span className="statusBadge" style={{ marginLeft: '8px', fontSize: '10px', fontWeight: 'normal' }}>
                Source: {coverageProbe.source}
              </span>
            )}
          </summary>
          {coverageProbe?.available ? (
            <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '8px', marginBottom: '8px' }}>
                {[
                  ['Candidates', probeCandidateCount],
                  ['Attempted', probeAttemptedCount],
                  ['Succeeded', probeSuccessCount],
                  ['Failed', probeFailedCount],
                ].map(([label, value]) => (
                  <div key={String(label)} className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>{label}</small>
                    <strong style={{ fontSize: '1.4em' }}>{value}</strong>
                  </div>
                ))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '8px', marginBottom: '8px' }}>
                {[
                  ['Promotable', coverageProbe.promotable_count],
                  ['Promoted', coverageProbe.promoted_row_count],
                  ['Dedup Skipped', probeDedupSkippedCount],
                ].map(([label, value]) => (
                  <div key={String(label)} className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>{label}</small>
                    <strong style={{ fontSize: '1.4em' }}>{value}</strong>
                  </div>
                ))}
              </div>
              {(probeScreenSkippedCount != null || probeScenarioFilteredCount != null) && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                  {probeScreenSkippedCount != null && (
                    <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                      <small>Screen Skipped</small>
                      <strong style={{ fontSize: '1.4em' }}>{probeScreenSkippedCount}</strong>
                    </div>
                  )}
                  {probeScenarioFilteredCount != null && (
                    <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                      <small>Scenario Filtered</small>
                      <strong style={{ fontSize: '1.4em' }}>{probeScenarioFilteredCount}</strong>
                    </div>
                  )}
                </div>
              )}
              {probeCandidateCount === 0 && (
                <small style={{ color: 'var(--color-text-dim)', padding: '4px 2px' }}>
                  Probe artifacts found, but no candidates were recorded.
                </small>
              )}
            </div>
          ) : (
            <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
              <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '16px 8px' }}>
                <strong style={{ color: 'var(--color-text-dim)' }}>Not Available</strong>
                <small style={{ color: coverageProbe?.probe_enabled === true ? 'var(--color-warning)' : 'var(--color-text-dim)' }}>
                  {coverageProbeUnavailableMessage}
                </small>
              </div>
            </div>
          )}
        </details>

        {runData?.quality_issues && runData.quality_issues.length > 0 && (
          <details open style={{ marginTop: '16px' }}>
            <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>Quality Issues</summary>
            <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', marginTop: '4px', fontStyle: 'italic' }}>
              Shows user-impacting TalkBack text/speech issues only.
            </div>
            <div className="scenarioDetailList" style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {runData.quality_issues.map((issue: any, i: number) => (
                <div key={i} className="scenarioDetailRow" style={{ display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'flex-start', padding: '12px' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', width: '100%' }}>
                    <span className={`statusBadge ${issue.final_result.toLowerCase()}`} style={{ 
                        backgroundColor: issue.final_result === 'FAIL' ? 'var(--color-danger)' : (issue.final_result === 'WARN' ? 'var(--color-warning)' : 'var(--color-neutral)'),
                        color: '#fff', padding: '2px 6px', borderRadius: '4px', fontSize: '12px', fontWeight: 'bold'
                    }}>
                      {issue.final_result === 'WARN' ? 'ISSUE' : (issue.final_result === 'PASS' ? 'CLEAN' : issue.final_result)}
                    </span>
                    <strong style={{ fontSize: '13px', wordBreak: 'break-all' }}>
                      {issue.scenario_id} step {issue.step}
                      {issue.is_repeated_issue_group ? ` · repeated ${issue.repeat_count} rows (${issue.first_step}-${issue.last_step})` : ''}
                    </strong>
                  </div>
                  
                  <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', width: '100%' }}>
                    <strong>Mismatch:</strong> {issue.mismatch_type}
                  </div>
                  {issue.shadow_verdict && (
                    <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', width: '100%' }}>
                      <strong>Shadow:</strong> {issue.shadow_verdict}
                      {issue.shadow_verdict_reason ? ` · ${issue.shadow_verdict_reason}` : ''}
                    </div>
                  )}
                  <div style={{ fontSize: '12px', color: 'var(--color-text)', width: '100%' }}>
                    <strong>Visible text:</strong> {issue.visible_label || '-'}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--color-text)', width: '100%' }}>
                    <strong>TalkBack speech:</strong> {issue.merged_announcement || '-'}
                  </div>
                  {issue.review_note && (
                    <div style={{ fontSize: '12px', color: 'var(--color-text)', width: '100%', fontStyle: 'italic' }}>
                      <strong>Note:</strong> {issue.review_note}
                    </div>
                  )}
                  {issue.crop_path ? (
                    <div style={{ marginTop: '8px', border: '1px solid var(--color-border)', borderRadius: '4px', padding: '4px', backgroundColor: 'var(--color-bg-alt)', display: 'inline-block' }}>
                      <a href={`/api/batch/file?path=${encodeURIComponent(issue.crop_path)}`} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                        <img 
                          src={`/api/batch/file?path=${encodeURIComponent(issue.crop_path)}`} 
                          alt="crop" 
                          style={{ width: '160px', maxHeight: '120px', objectFit: 'contain', borderRadius: '4px', cursor: 'zoom-in' }}
                          onError={(e) => {
                            const target = e.target as HTMLImageElement;
                            const parentAnchor = target.parentElement;
                            if (parentAnchor) {
                              parentAnchor.style.display = 'none';
                              const fallback = parentAnchor.nextElementSibling as HTMLElement;
                              if (fallback) {
                                fallback.style.display = 'block';
                              }
                            }
                          }}
                        />
                      </a>
                      <div style={{ display: 'none', fontSize: '11px', color: 'var(--color-text-dim)', textAlign: 'center', padding: '4px' }}>
                        <div style={{ marginBottom: '4px' }}>crop image unavailable</div>
                        <div>{issue.crop_path.split('/').pop()}</div>
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </details>
        )}

        {crashContext && <IdentityShadowCard runId={crashContext.runId} deviceId={crashContext.deviceId} />}

        {crashContext && (
          <CrashIssuesPanel runId={crashContext.runId} deviceId={crashContext.deviceId} />
        )}
      </div>
    );
  };


  useEffect(() => {
    const runIds = new Set(recentRuns.slice(0, 10).map(r => r.run_id));
    if (selectedRecentRun?.run_id) {
      runIds.add(selectedRecentRun.run_id);
    }
    
    const toFetch = Array.from(runIds)
      .map(id => recentRuns.find(r => r.run_id === id))
      .filter((r): r is RecentRun => Boolean(r && r.xlsx_exists && mismatchSummaries[r.run_id] === undefined));
    
    if (toFetch.length === 0) return;
    
    let ignore = false;
    Promise.all(
      toFetch.map(r => 
        api.runMismatch(r.run_id)
          .then(summary => ({ run_id: r.run_id, summary }))
          .catch(() => ({ run_id: r.run_id, summary: null }))
      )
    ).then(results => {
      if (ignore) return;
      setMismatchSummaries(prev => {
        const next = { ...prev };
        results.forEach(res => {
          next[res.run_id] = res.summary as MismatchSummary | null;
        });
        return next;
      });
    });
    
    return () => { ignore = true; };
  }, [recentRuns, selectedRecentRun?.run_id]);

  function renderTalkBackBadge(runId: string) {
    const summary = mismatchSummaries[runId];
    if (summary === undefined) return null;
    if (summary === null) return null;

    const counts = summary.summary;
    if (counts.fail_count > 0) {
      return <span className="statusBadge healthBad">ROW FAIL ({counts.fail_count})</span>;
    }
    if (counts.issue_count > 0) {
      return <span className="statusBadge healthWarn">ROW ISSUE ({counts.issue_count})</span>;
    }
    if (counts.review_count > 0) {
      return <span className="statusBadge" style={{ background: 'var(--color-neutral)', color: '#fff' }}>ROW REVIEW ({counts.review_count})</span>;
    }
    return <span className="statusBadge healthOk">ROW CLEAN</span>;
  }

  return (
    <article className="panel">
      <h2>Run History</h2>
      <p style={{ fontSize: '12px', color: 'var(--color-text-dim)', marginBottom: '16px' }}>
        <strong>Batch Runs:</strong> Multi-device or sequential batch executions.<br/>
        <strong>Single Runs:</strong> Legacy single-device direct executions.
      </p>
      {recentBatches.length > 0 && (
        <>
          <h3 style={{ fontSize: '13px', textTransform: 'uppercase', color: 'var(--color-text-dim)', margin: '0 0 8px 0' }}>Batch Runs</h3>
          <div className="recentRuns" style={{ marginBottom: '20px' }}>
            {recentBatches.map(batch => (
              <div
                key={batch.batch_id}
                role="button"
                tabIndex={0}
                className={`recentRunRow ${selectedBatchId === batch.batch_id ? 'selected' : ''}`}
                onClick={() => { setSelectedBatchId(batch.batch_id); setSelectedRecentRunId(null); }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    setSelectedBatchId(batch.batch_id);
                    setSelectedRecentRunId(null);
                  }
                }}
              >
                <div>
                  <strong>{batch.batch_id}</strong>
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', margin: '6px 0' }}>
                    <span className={`statusBadge ${batch.state === 'running' ? 'healthOk' : batch.state === 'finished' ? 'healthOk' : 'healthBad'}`}>
                      {batch.state}
                    </span>
                  </div>
                  <small>
                    {batch.mode} &middot; {new Date(batch.created_at).toLocaleString()}
                    {typeof batch.duration_seconds === 'number' ? ` · duration: ${formatDuration(batch.duration_seconds)}` : ''}
                    &middot; devices: {batch.device_count} (devices passed: {batch.passed_count}, devices failed: {batch.failed_count})
                  </small>
                  {batch.devices && batch.devices.length > 0 && (
                    <div style={{ marginTop: '8px', paddingLeft: '8px', borderLeft: '2px solid var(--color-border)' }}>
                      <div style={{ fontSize: '11px', color: 'var(--color-text-dim)', marginBottom: '4px', textTransform: 'uppercase' }}>Devices:</div>
                      <ul style={{ margin: 0, padding: 0, listStyle: 'none', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {batch.devices.slice(0, 5).map(d => (
                          <li key={d.serial} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span style={{ color: d.state === 'running' ? 'var(--color-primary)' : d.state === 'passed' ? 'var(--color-success)' : d.state === 'failed' ? 'var(--color-danger)' : 'var(--color-text-dim)' }}>
                              &bull;
                            </span>
                            <span>
                              {d.model} <span style={{ color: 'var(--color-text-dim)' }}>/ {d.serial}</span> &middot; {d.state} {d.return_code != null ? `· ret: ${d.return_code}` : ''}
                              {d.quality && ` · fail:${d.quality.fail} issue:${d.quality.issue} review:${d.quality.review} clean:${d.quality.clean}`}
                              {d.shadow_quality && ` · shadow fail:${d.shadow_quality.fail} warn:${d.shadow_quality.warn} review:${d.shadow_quality.review}`}
                              {d.focusable_coverage?.summary && ` · coverage required:${d.focusable_coverage.summary.focusable_required_missed_count ?? 0} review:${d.focusable_coverage.summary.focusable_review_unknown_count ?? 0}`}
                            </span>
                            <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto' }}>
                              {d.log_path && (
                                <a href={`/api/batch/file?path=${encodeURIComponent(d.log_path)}`} target="_blank" rel="noreferrer" style={{ fontSize: '11px', textDecoration: 'none', color: 'var(--color-primary)', background: 'rgba(52, 152, 219, 0.1)', padding: '2px 6px', borderRadius: '4px' }}>Log</a>
                              )}
                              {d.xlsx_path && (
                                <a href={`/api/batch/file?path=${encodeURIComponent(d.xlsx_path)}`} style={{ fontSize: '11px', textDecoration: 'none', color: 'var(--color-success)', background: 'rgba(46, 204, 113, 0.1)', padding: '2px 6px', borderRadius: '4px' }}>XLSX</a>
                              )}
                            </div>
                          </li>
                        ))}
                        {batch.devices.length > 5 && (
                          <li style={{ color: 'var(--color-text-dim)', fontStyle: 'italic' }}>and {batch.devices.length - 5} more...</li>
                        )}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {selectedBatch && (
        <div className="runDetails">
          <div className="runDetailsHeader">
            <h3>Batch Details</h3>
            <span>{selectedBatch.batch_id}</span>
          </div>
          <div style={{ padding: '12px', fontSize: '13px' }}>
            <div style={{ marginBottom: '16px' }}>
              <strong>Status:</strong> {selectedBatch.state} &middot; <strong>Mode:</strong> {selectedBatch.mode} &middot; <strong>Devices:</strong> {selectedBatch.device_count}
            </div>
            {selectedBatch.devices && selectedBatch.devices.map(d => (
               <div key={d.serial} style={{ padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', marginBottom: '16px', background: 'var(--color-bg-dim)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <strong>{d.model}</strong> <small style={{ color: 'var(--color-text-dim)' }}>/ {d.serial}</small>
                    </div>
                    <span className={`statusBadge ${d.state === 'running' ? 'healthWarn' : d.state === 'passed' ? 'healthOk' : d.state === 'failed' ? 'healthBad' : ''}`}>{d.state}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', marginTop: '8px', marginBottom: '8px' }}>
                    {d.log_path && <a href={`/api/batch/file?path=${encodeURIComponent(d.log_path)}`} target="_blank" rel="noreferrer" style={{ color: 'var(--color-primary)' }}>View Log</a>}
                    {d.xlsx_path && <a href={`/api/batch/file?path=${encodeURIComponent(d.xlsx_path)}`} target="_blank" rel="noreferrer" style={{ color: 'var(--color-success)' }}>View XLSX</a>}
                  </div>
                  <details style={{ marginTop: '16px', marginBottom: '16px' }}>
                    <summary style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--color-text-dim)', textTransform: 'uppercase' }}>Log Preview</summary>
                    <pre style={{ background: 'var(--color-bg-dark, #1e1e1e)', color: '#d4d4d4', padding: '12px', borderRadius: '6px', fontSize: '11px', maxHeight: '300px', overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginTop: '8px' }}>
                      {batchLogPreviews[d.serial] || 'Loading log...'}
                    </pre>
                  </details>
                  {renderDeviceDetails(d, { runId: selectedBatch.batch_id, deviceId: resolveBatchDeviceId(d) })}
               </div>
            ))}
          </div>
        </div>
      )}

    </article>
  );
}
