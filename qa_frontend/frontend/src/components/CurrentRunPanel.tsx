import { useEffect, useMemo, useState } from 'react';
import type { BatchStatus, RunStatus, RuntimeDashboard } from '../api';
import type { CurrentRunState } from '../currentRun';
import { projectCurrentRun } from '../currentRun';

export type CurrentRunPanelProps = {
  readonly batchStatus: BatchStatus | null;
  readonly status: RunStatus | null;
  readonly dashboard: RuntimeDashboard | null;
  readonly runLabel: string;
  readonly fullValidationScenarioIds: readonly string[];
  readonly stop: () => void;
};

function assertNever(value: never): never {
  throw new Error(`Unexpected Current Run state: ${String(value)}`);
}

function stateLabel(state: CurrentRunState): string {
  switch (state) {
    case 'idle':
      return 'Idle';
    case 'running':
      return 'Running';
    case 'finished':
      return 'Validation completed';
    case 'stopped':
      return 'Validation stopped';
    case 'failed':
      return 'Validation failed';
    case 'error':
      return 'Validation error';
    default:
      return assertNever(state);
  }
}

function deviceStatusClass(statusLabel: string): string {
  return ['Completed', 'Running'].includes(statusLabel) ? 'currentRunStatusGood' : 'currentRunStatusWarn';
}

function runStatusClass(state: CurrentRunState): string {
  if (state === 'running' || state === 'finished') return 'currentRunStatusGood';
  if (state === 'stopped' || state === 'failed' || state === 'error') return 'currentRunStatusWarn';
  return 'currentRunStatusNeutral';
}

export function CurrentRunPanel({ batchStatus, status, dashboard, runLabel, fullValidationScenarioIds, stop }: CurrentRunPanelProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const projection = useMemo(
    () => projectCurrentRun({ batchStatus, status, dashboard, runLabel, fullValidationScenarioIds, nowMs }),
    [batchStatus, dashboard, fullValidationScenarioIds, nowMs, runLabel, status],
  );

  useEffect(() => {
    if (!projection.active) return undefined;
    const interval = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [projection.active]);

  return (
    <section className={`panel currentRunPanel currentRunState-${projection.state}`} aria-labelledby="current-run-title">
      <header className="currentRunHeader">
        <div>
          <h2 id="current-run-title">Current Run</h2>
          <span className={`currentRunStatus ${runStatusClass(projection.state)}`} role="status">
            {stateLabel(projection.state)}
          </span>
        </div>
        {projection.active && (
          <button type="button" className="danger currentRunStop" onClick={stop}>
            Stop Run
          </button>
        )}
      </header>

      {projection.state === 'idle' ? (
        <p className="currentRunIdle">No validation is currently running.</p>
      ) : (
        <>
          <div className="currentRunSummary" aria-label="Current Run summary">
            <div>
              <span>Run</span>
              <strong>{projection.runLabel}</strong>
            </div>
            <div>
              <span>Progress</span>
              <strong>{projection.primaryProgressLabel ?? 'Progress unavailable'}</strong>
            </div>
            <div>
              <span>Elapsed</span>
              <strong>{projection.elapsedLabel}</strong>
            </div>
          </div>

          {projection.actionableWarning && (
            <div className="currentRunWarning" role="alert">
              <strong>Attention</strong>
              <span>{projection.actionableWarning}</span>
            </div>
          )}

          {projection.devices.length > 0 ? (
            <div className="currentRunDevices" aria-label="Devices in current run">
              {projection.devices.map((device) => (
                <article key={device.serial} className="currentRunDeviceCard">
                  <div className="currentRunDeviceHeader">
                    <div>
                      <strong>{device.model}</strong>
                      <small className={deviceStatusClass(device.statusLabel)}>{device.statusLabel}</small>
                    </div>
                    <strong>{device.progressLabel}</strong>
                  </div>
                  {device.statusLabel === 'Running' && (
                    <p className="currentRunScenario">
                      Current: {device.currentScenarioLabel ?? 'Preparing next scenario…'}
                    </p>
                  )}
                  <details className="currentRunDeviceDetails">
                    <summary>Device details</summary>
                    <dl>
                      <dt>Serial</dt>
                      <dd>{device.serial}</dd>
                      <dt>State</dt>
                      <dd>{device.state}</dd>
                      <dt>Scenario ID</dt>
                      <dd>{device.currentScenarioId ?? '-'}</dd>
                      {device.technicalError && (
                        <>
                          <dt>Error</dt>
                          <dd>{device.technicalError}</dd>
                        </>
                      )}
                    </dl>
                  </details>
                </article>
              ))}
            </div>
          ) : projection.active ? (
            <div className="currentRunDeviceCard currentRunSingleDevice">
              <strong>Current device</strong>
              <span>Device details are available in Run details.</span>
              <p className="currentRunScenario">
                Current: {projection.currentScenarioLabel ?? 'Preparing next scenario…'}
              </p>
            </div>
          ) : null}

          {!projection.active && (
            <p className="currentRunCompletion">
              {projection.state === 'finished'
                ? 'Execution completed. Review the Review Required summary and Run History below.'
                : 'Execution did not complete. Review the run diagnostics and history below.'}
            </p>
          )}

          <details className="currentRunDetails">
            <summary>Run details</summary>
            <dl>
              <dt>Run ID</dt>
              <dd>{projection.runId ?? '-'}</dd>
              <dt>Current scenario ID</dt>
              <dd>{projection.currentScenarioId ?? '-'}</dd>
              <dt>Processed scenarios</dt>
              <dd>{projection.processedScenarios} / {projection.totalScenarios || '-'}</dd>
              <dt>Devices</dt>
              <dd>{projection.finishedDevices} / {projection.totalDevices || '-'}</dd>
            </dl>
            <ul className="currentRunTechnicalList">
              {projection.technicalDetails.map((detail) => <li key={detail}>{detail}</li>)}
            </ul>
            {projection.technicalError && <pre className="currentRunErrorDetails">{projection.technicalError}</pre>}
          </details>
        </>
      )}
    </section>
  );
}
