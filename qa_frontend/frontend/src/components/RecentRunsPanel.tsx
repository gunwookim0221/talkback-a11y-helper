import React from 'react';
import { RecentRun } from '../api';
import { formatTime, formatDuration, healthClass, scenarioRunText, languageLabel, scenarioReasonText } from '../utils/formatters';

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
        </div>
      )}
    </article>
  );
}
