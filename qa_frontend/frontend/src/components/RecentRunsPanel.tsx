import React, { useEffect, useState } from 'react';
import { RecentRun, api } from '../api';
import { formatTime, formatDuration, healthClass, scenarioRunText, languageLabel, scenarioReasonText } from '../utils/formatters';

type MismatchSummary = {
  matched: number;
  true_mismatch: number;
  empty_speech: number;
  empty_visible: number;
  review: number;
  runtime_warning: number;
  previews: Array<{ 
    scenario: string; 
    plugin_name: string;
    step: string;
    visible: string; 
    spoken: string; 
    mismatch_type: string; 
    final_result: string;
    failure_reason: string;
    focus_confidence: string;
    category: string; 
  }>;
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
  const [mismatchSummary, setMismatchSummary] = useState<MismatchSummary | null>(null);

  useEffect(() => {
    if (!selectedRecentRunId) {
      setMismatchSummary(null);
      return;
    }
    const run = recentRuns.find(r => r.run_id === selectedRecentRunId);
    if (!run || !run.xlsx_exists) {
      setMismatchSummary(null);
      return;
    }
    let ignore = false;
    api.runMismatch(selectedRecentRunId).then(summary => {
      if (!ignore) setMismatchSummary(summary);
    }).catch(err => {
      console.error('Failed to load mismatch summary:', err);
      if (!ignore) setMismatchSummary(null);
    });
    return () => { ignore = true; };
  }, [selectedRecentRunId, recentRuns]);

  return (
    <article className="panel">
      <h2>Recent Runs</h2>
      <div className="recentRuns">
        {recentRuns.map((run) => (
          <div
            key={run.run_id}
            role="button"
            tabIndex={0}
            className={`recentRunRow ${selectedRecentRun?.run_id === run.run_id ? 'selected' : ''}`}
            onClick={() => setSelectedRecentRunId(run.run_id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                setSelectedRecentRunId(run.run_id);
              }
            }}
          >
            <div>
              <strong>{run.run_id}</strong>
              <div className="recentStatusLine">
                <span className={`statusBadge ${healthClass(run.process_status)}`}>Run {run.process_status}</span>
                <span className={`statusBadge ${healthClass(run.scenario_result_status)}`}>
                  {scenarioRunText(run)}
                </span>
              </div>
              <small>
                {run.mode} · {formatTime(Date.parse(run.started_at) / 1000)} · {formatDuration(run.duration_seconds)}
                {` · ${languageLabel(run.language_mode)}`}
                {run.device_locale ? ` · locale ${run.device_locale}` : ''}
                {run.event_warning_count ? ` · ${run.event_warning_count} events` : ''}
                {run.summary_source === 'summary_json' ? ' · summary cached' : ''}
              </small>
            </div>
            <div className="recentRunActions">
              <a
                className={`downloadButton ${!run.xlsx_exists ? 'disabled' : ''}`}
                href={run.xlsx_exists ? `/api/outputs/${encodeURIComponent(run.xlsx_filename ?? '')}` : undefined}
                aria-disabled={!run.xlsx_exists}
              >
                XLSX
              </a>
              <a
                className={`downloadButton ${!run.log_exists ? 'disabled' : ''}`}
                href={run.log_exists ? `/api/runs/recent/${encodeURIComponent(run.run_id)}/log` : undefined}
                aria-disabled={!run.log_exists}
              >
                Log
              </a>
            </div>
          </div>
        ))}
      </div>
      {selectedRecentRun && (
        <div className="runDetails">
          <div className="runDetailsHeader">
            <h3>Run Details</h3>
            <span>{selectedRecentRun.run_id}</span>
          </div>
          <details open>
            <summary>Failed ({selectedFailedScenarios.length})</summary>
            <div className="scenarioDetailList">
              {selectedFailedScenarios.length ? (
                selectedFailedScenarios.map((scenario) => (
                  <div key={scenario.id} className="scenarioDetailRow">
                    <strong>{scenario.id}</strong>
                    <small>reason={scenarioReasonText(scenario) || 'failed'}</small>
                  </div>
                ))
              ) : (
                <small>No failed scenarios.</small>
              )}
            </div>
          </details>
          <details open>
            <summary>Warning ({selectedWarningScenarios.length})</summary>
            <div className="scenarioDetailList">
              {selectedWarningScenarios.length ? (
                selectedWarningScenarios.map((scenario) => (
                  <div key={scenario.id} className="scenarioDetailRow">
                    <strong>{scenario.id}</strong>
                    <small>reason={scenarioReasonText(scenario) || 'warning'}</small>
                  </div>
                ))
              ) : (
                <small>No warning scenarios.</small>
              )}
            </div>
          </details>
          <details>
            <summary>Passed ({selectedPassedScenarios.length})</summary>
            <div className="scenarioDetailList">
              {selectedPassedScenarios.length ? (
                selectedPassedScenarios.map((scenario) => (
                  <div key={scenario.id} className="scenarioDetailRow">
                    <strong>{scenario.id}</strong>
                    {typeof scenario.steps === 'number' ? <small>{scenario.steps} steps</small> : null}
                  </div>
                ))
              ) : (
                <small>No passed scenarios.</small>
              )}
            </div>
          </details>
          
          {mismatchSummary && (
            <details open>
              <summary>TalkBack Quality</summary>
              <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', marginBottom: '12px' }}>
                  <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>Matched</small>
                    <strong style={{ fontSize: '1.2em' }}>{mismatchSummary.matched}</strong>
                  </div>
                  <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>True Mismatch</small>
                    <strong style={{ fontSize: '1.2em', color: mismatchSummary.true_mismatch > 0 ? 'var(--color-danger)' : 'inherit' }}>{mismatchSummary.true_mismatch}</strong>
                  </div>
                  <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>Empty Speech</small>
                    <strong style={{ fontSize: '1.2em', color: mismatchSummary.empty_speech > 0 ? 'var(--color-warning)' : 'inherit' }}>{mismatchSummary.empty_speech}</strong>
                  </div>
                  <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>Empty Visible</small>
                    <strong style={{ fontSize: '1.2em', color: mismatchSummary.empty_visible > 0 ? 'var(--color-warning)' : 'inherit' }}>{mismatchSummary.empty_visible}</strong>
                  </div>
                  <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>Review</small>
                    <strong style={{ fontSize: '1.2em', color: mismatchSummary.review > 0 ? 'var(--color-neutral)' : 'inherit' }}>{mismatchSummary.review}</strong>
                  </div>
                  <div className="scenarioDetailRow" style={{ textAlign: 'center', padding: '12px 8px' }}>
                    <small>Runtime Warning</small>
                    <strong style={{ fontSize: '1.2em', color: mismatchSummary.runtime_warning > 0 ? 'var(--color-danger)' : 'inherit' }}>{mismatchSummary.runtime_warning}</strong>
                  </div>
                </div>

                {mismatchSummary.previews.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      <strong>Quality Signals</strong>
                      <small style={{ color: 'var(--color-text-dim)' }}>Shows true mismatches, empty signals, reviews, and warnings.</small>
                    </div>
                    {mismatchSummary.previews.map((preview, i) => (
                      <div key={i} className="scenarioDetailRow" style={{ gap: '6px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div>
                            <strong>{preview.plugin_name || preview.scenario}</strong>
                            <div style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>
                              {preview.scenario} / step {preview.step}
                            </div>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
                            <span className="statusBadge healthWarn" style={{ fontSize: '10px' }}>category: {preview.category}</span>
                            {preview.mismatch_type && (
                              <span style={{ fontSize: '10px', color: 'var(--color-text-dim)' }}>type: {preview.mismatch_type}</span>
                            )}
                          </div>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr', gap: '4px', marginTop: '4px' }}>
                          <small>visible:</small>
                          <span style={{ fontSize: '13px' }}>{preview.visible || '(empty)'}</span>
                          <small>spoken:</small>
                          <span style={{ fontSize: '13px' }}>{preview.spoken || '(empty)'}</span>
                          {preview.failure_reason && (
                            <>
                              <small>failure_reason:</small>
                              <span style={{ fontSize: '13px', color: 'var(--color-danger)' }}>{preview.failure_reason}</span>
                            </>
                          )}
                          {preview.focus_confidence && (
                            <>
                              <small>focus_conf:</small>
                              <span style={{ fontSize: '13px' }}>{preview.focus_confidence}</span>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </details>
          )}

        </div>
      )}
    </article>
  );
}
