import React, { useEffect, useState, useMemo } from 'react';
import { RecentRun, api, RecentBatch } from '../api';
import { formatTime, formatDuration, healthClass, scenarioRunText, languageLabel, scenarioReasonText } from '../utils/formatters';

type MismatchSummary = {
  summary: {
    matched: number;
    true_mismatch: number;
    empty_speech: number;
    empty_visible: number;
    review: number;
    runtime_warning: number;
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

  const renderDeviceDetails = (runData: any) => {
    const failedScenarios = (runData?.scenarios || []).filter((s: any) => s.status === 'failed');
    const warningScenarios = (runData?.scenarios || []).filter((s: any) => s.status === 'warning');
    const passedScenarios = (runData?.scenarios || []).filter((s: any) => s.status === 'passed');

    return (
      <div style={{ marginTop: '12px' }}>
        <details open>
          <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>Run Details</summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingLeft: '8px', marginTop: '8px' }}>
            <details>
              <summary>Failed ({failedScenarios.length})</summary>
              <div className="scenarioDetailList">
                {failedScenarios.length ? (
                  failedScenarios.map((scenario: any) => (
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
            <details>
              <summary>Warning ({warningScenarios.length})</summary>
              <div className="scenarioDetailList">
                {warningScenarios.length ? (
                  warningScenarios.map((scenario: any) => (
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
              <summary>Passed ({passedScenarios.length})</summary>
              <div className="scenarioDetailList">
                {passedScenarios.length ? (
                  passedScenarios.map((scenario: any) => (
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
          </div>
        </details>
        
        {runData?.quality && (
          <details open style={{ marginTop: '16px' }}>
            <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>TalkBack Quality</summary>
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

        {runData?.quality_issues && runData.quality_issues.length > 0 && (
          <details open style={{ marginTop: '16px' }}>
            <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>Quality Issues</summary>
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
                    <strong style={{ fontSize: '13px', wordBreak: 'break-all' }}>{issue.scenario_id} step {issue.step}</strong>
                  </div>
                  
                  <div style={{ fontSize: '12px', color: 'var(--color-text-dim)', width: '100%' }}>
                    <strong>Mismatch:</strong> {issue.mismatch_type}
                  </div>
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
                    <div style={{ marginTop: '8px', border: '1px solid var(--color-border)', borderRadius: '4px', padding: '4px', backgroundColor: 'var(--color-bg-alt)' }}>
                      <img 
                        src={`/api/batch/file?path=${encodeURIComponent(issue.crop_path)}`} 
                        alt="Crop thumbnail" 
                        style={{ maxWidth: '100%', maxHeight: '150px', objectFit: 'contain' }}
                        onError={(e) => {
                          const target = e.target as HTMLImageElement;
                          target.style.display = 'none';
                          if (target.nextSibling) {
                            (target.nextSibling as HTMLElement).style.display = 'block';
                          }
                        }}
                      />
                      <div style={{ display: 'none', fontSize: '11px', color: 'var(--color-text-dim)', textAlign: 'center' }}>
                        {issue.crop_path.split('/').pop()}
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </details>
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
      return <span className="statusBadge healthBad">TALKBACK FAIL ({counts.fail_count})</span>;
    }
    if (counts.issue_count > 0) {
      return <span className="statusBadge healthWarn">TALKBACK ISSUE ({counts.issue_count})</span>;
    }
    if (counts.review_count > 0) {
      return <span className="statusBadge" style={{ background: 'var(--color-neutral)', color: '#fff' }}>TALKBACK REVIEW ({counts.review_count})</span>;
    }
    return <span className="statusBadge healthOk">TALKBACK CLEAN</span>;
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
                    {batch.mode} &middot; {new Date(batch.created_at).toLocaleString()} &middot; devices: {batch.device_count} (passed: {batch.passed_count}, failed: {batch.failed_count})
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
                  {renderDeviceDetails(d)}
               </div>
            ))}
          </div>
        </div>
      )}

    </article>
  );
}
