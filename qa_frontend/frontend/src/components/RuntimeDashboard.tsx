import React, { useState, useEffect, useRef } from 'react';
import { BatchStatus, HelperStatus, RunStatus, RuntimeDashboard } from '../api';
import { formatDuration, formatBytes, healthClass, languageLabel } from '../utils/formatters';

export interface RuntimeDashboardProps {
  dashboard: RuntimeDashboard | null;
  batchStatus: BatchStatus | null;
  status: RunStatus | null;
  helper: HelperStatus | null;
  adb: Record<string, unknown> | null;
  pollingLatencyMs: number | null;
}

export function RuntimeDashboardPanel({ dashboard, batchStatus, status, helper, adb, pollingLatencyMs }: RuntimeDashboardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const prevStateRef = useRef<string | null>(null);
  const batchActive = Boolean(batchStatus && batchStatus.state !== 'idle');
  const monitorState = batchActive ? batchStatus?.state : status?.state;

  useEffect(() => {
    const currentState = monitorState ?? 'idle';
    if (prevStateRef.current !== currentState) {
      if (['running', 'starting'].includes(currentState)) {
        setIsOpen(true);
      } else if (['idle', 'stopped', 'finished'].includes(currentState)) {
        setIsOpen(false);
      }
      prevStateRef.current = currentState;
    }
  }, [monitorState]);

  if (batchActive) {
    return <BatchLiveMonitor batchStatus={batchStatus} pollingLatencyMs={pollingLatencyMs} isOpen={isOpen} setIsOpen={setIsOpen} />;
  }

  return (
    <details className="panel dashboardPanel" open={isOpen} onToggle={(e) => setIsOpen(e.currentTarget.open)}>
      <summary style={{ cursor: 'pointer', paddingBottom: isOpen ? '12px' : '0' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', width: '90%' }}>
          <h2 style={{ margin: 0 }}>Live Monitor</h2>
          <div className={`statusBadge ${healthClass(status?.state)}`} style={{ marginLeft: '12px' }}>{status?.state ?? 'idle'}</div>
        </div>
      </summary>
      <div style={{ paddingTop: '8px', borderTop: '1px solid var(--color-border)' }}>
      {dashboard?.parse_error && <div className="notice">Dashboard parse warning: {dashboard.parse_error}</div>}
      <div className="metricGrid">
        <div>
          <span>Elapsed</span>
          <strong>{formatDuration(dashboard?.elapsed_seconds ?? 0)}</strong>
        </div>
        <div>
          <span>Passed</span>
          <strong>{dashboard?.passed_scenarios ?? 0}</strong>
        </div>
        <div>
          <span>Warning</span>
          <strong>{dashboard?.warning_scenarios ?? 0}</strong>
        </div>
        <div>
          <span>Failed</span>
          <strong>{dashboard?.failed_scenarios ?? 0}</strong>
        </div>
        <div>
          <span>Steps</span>
          <strong>{dashboard?.total_step_count ?? 0}</strong>
        </div>
        <div>
          <span>Overlays</span>
          <strong>{dashboard?.overlay_count ?? 0}</strong>
        </div>
        <div>
          <span>Excel Saves</span>
          <strong>{dashboard?.save_excel_count ?? 0}</strong>
        </div>
        <div>
          <span>Log Size</span>
          <strong>{formatBytes(dashboard?.log_size ?? 0)}</strong>
        </div>
        <div>
          <span>Poll</span>
          <strong>{pollingLatencyMs ?? '-'} ms</strong>
        </div>
      </div>
      <div className="dashboardGrid">
        <div>
          <h3>Run State</h3>
          <dl>
            <dt>Run</dt>
            <dd>{dashboard?.run_id ?? '-'}</dd>
            <dt>Mode</dt>
            <dd>{dashboard?.mode ?? status?.mode ?? '-'}</dd>
            <dt>Launch</dt>
            <dd>{dashboard?.launch_mode ?? status?.launch_mode ?? '-'}</dd>
            <dt>Language</dt>
            <dd>{languageLabel(dashboard?.language_mode ?? status?.language_mode)}</dd>
            <dt>Locale</dt>
            <dd>{dashboard?.device_locale ?? status?.device_locale ?? '-'}</dd>
            <dt>Started</dt>
            <dd>{dashboard?.started_at ?? status?.started_at ?? '-'}</dd>
            <dt>Scenario</dt>
            <dd>{dashboard?.current_scenario ?? '-'}</dd>
            <dt>Current Step</dt>
            <dd>{dashboard?.current_step ?? '-'}</dd>
            <dt>Traversal</dt>
            <dd>{dashboard?.traversal_result ?? '-'}</dd>
            <dt>Stop Reason</dt>
            <dd>{dashboard?.stop_reason ?? '-'}</dd>
          </dl>
        </div>
        <div>
          <h3>Health</h3>
          <div className="healthList">
            <span className={`statusBadge ${healthClass(dashboard?.preflight_state)}`}>preflight {dashboard?.preflight_state ?? '-'}</span>
            <span className={`statusBadge ${healthClass(dashboard?.popup_result)}`}>popup {dashboard?.popup_result ?? '-'}</span>
            <span className={`statusBadge ${healthClass(dashboard?.helper_status ?? helper?.status as string)}`}>helper {dashboard?.helper_status ?? String(helper?.status ?? '-')}</span>
            <span className={`statusBadge ${healthClass(dashboard?.adb_status ?? adb?.status as string)}`}>adb {dashboard?.adb_status ?? String(adb?.status ?? '-')}</span>
          </div>
          <dl>
            <dt>Focus Pkg</dt>
            <dd>{dashboard?.last_focus_package ?? '-'}</dd>
            <dt>Focus Label</dt>
            <dd>{dashboard?.last_focus_label ?? '-'}</dd>
          </dl>
        </div>
      </div>
      <div className="dashboardGrid">
        <div>
          <h3>Scenario Progress</h3>
          <div className="progressList">
            {(dashboard?.scenario_progress ?? []).map((item) => (
              <div key={item.id} className="progressRow">
                <span className={`statusDot ${healthClass(item.status)}`}></span>
                <strong>{item.id}</strong>
                <small>{item.status} · {item.steps} steps</small>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3>Event Feed</h3>
          <div className="eventFeed">
            {(dashboard?.event_feed ?? []).slice().reverse().map((event) => (
              <div key={`${event.line}-${event.type}`} className="eventRow">
                <span>{event.type}</span>
                <small>{event.scenario ?? 'run'} · line {event.line}</small>
                <p>{event.message}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
      </div>
    </details>
  );
}

function BatchLiveMonitor({
  batchStatus,
  pollingLatencyMs,
  isOpen,
  setIsOpen,
}: {
  batchStatus: BatchStatus | null;
  pollingLatencyMs: number | null;
  isOpen: boolean;
  setIsOpen: (value: boolean) => void;
}) {
  const batch = batchStatus?.batch;
  const current = batchStatus?.current;
  const progress = batchStatus?.progress;
  const logs = batchStatus?.logs;
  const preflight = logs?.latest_preflight_status;
  const batchState = batch?.state ?? batchStatus?.state ?? 'idle';
  const batchFinished = ['finished', 'failed', 'stopped', 'error'].includes(batchState);
  const deviceTotal = batch?.total_devices ?? batchStatus?.devices?.length ?? 0;
  const finishedDevices = batch?.finished_devices ?? batchStatus?.devices?.filter((device) => !['pending', 'running'].includes(device.state)).length ?? 0;
  const scenarioCompleted = progress?.completed_scenarios ?? 0;
  const scenarioSelected = progress?.selected_scenarios ?? progress?.total_scenarios ?? 0;
  const scenarioObserved = progress?.observed_scenarios ?? 0;
  const currentStepCount = typeof current?.current_step_index === 'number' ? current.current_step_index + 1 : 0;
  const observedSteps = Math.max(progress?.observed_steps ?? 0, progress?.total_steps ?? 0, progress?.completed_steps ?? 0, currentStepCount);
  const observedEvents = progress?.observed_runtime_events ?? 0;
  const scenarioMetricLabel = 'Scenarios';
  const scenarioObservedDisplay = scenarioObserved || (current?.current_scenario_id ? 1 : 0);
  const scenarioMetricValue = batchFinished
    ? `${scenarioCompleted} completed / ${scenarioSelected} selected (${scenarioObservedDisplay} observed)`
    : `${scenarioObservedDisplay} observed / ${scenarioSelected} selected`;
  const counterTitle = batchFinished ? 'Quality Counter' : 'Observed Counter';
  const runtimeState = current?.current_scenario_runtime_state ?? (current?.current_scenario_id ? 'observing' : '-');
  const latestEvent = current?.latest_scenario_event ?? current?.current_step_result?.toLowerCase() ?? '-';
  const latestRuntimeEvent = current?.latest_runtime_event ?? current?.latest_step_log ?? logs?.latest_log_line ?? null;

  return (
    <details className="panel dashboardPanel" open={isOpen} onToggle={(e) => setIsOpen(e.currentTarget.open)}>
      <summary style={{ cursor: 'pointer', paddingBottom: isOpen ? '12px' : '0' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', width: '90%' }}>
          <h2 style={{ margin: 0 }}>Live Monitor</h2>
          <div className={`statusBadge ${healthClass(batchStatus?.state)}`} style={{ marginLeft: '12px' }}>
            {batchStatus?.state ?? 'idle'}
          </div>
        </div>
      </summary>
      <div style={{ paddingTop: '8px', borderTop: '1px solid var(--color-border)' }}>
        <div className="metricGrid">
          <div>
            <span>Completed Devices</span>
            <strong>{finishedDevices} / {deviceTotal} completed</strong>
          </div>
          <div>
            <span>{scenarioMetricLabel}</span>
            <strong>{scenarioMetricValue}</strong>
          </div>
          <div>
            <span>Observed Runtime Events</span>
            <strong>{observedEvents || observedSteps}</strong>
          </div>
          <div>
            <span>Poll</span>
            <strong>{pollingLatencyMs ?? '-'} ms</strong>
          </div>
        </div>
        <div className="dashboardGrid">
          <div>
            <h3>Batch</h3>
            <dl>
              <dt>Batch</dt>
              <dd>{batch?.batch_id ?? batchStatus?.batch_id ?? '-'}</dd>
              <dt>State</dt>
              <dd>{batchState}</dd>
              <dt>Mode</dt>
              <dd>{batchStatus?.mode ?? '-'}</dd>
              <dt>Started</dt>
              <dd>{batch?.started_at ?? '-'}</dd>
              <dt>Finished</dt>
              <dd>{batch?.finished_at ?? '-'}</dd>
            </dl>
          </div>
          <div>
            <h3>Current Device</h3>
            <dl>
              <dt>Serial</dt>
              <dd>{current?.current_device_serial ?? batchStatus?.current_device ?? '-'}</dd>
              <dt>Model</dt>
              <dd>{current?.current_device_model ?? '-'}</dd>
              <dt>State</dt>
              <dd>{current?.current_device_state ?? '-'}</dd>
            </dl>
          </div>
        </div>
        <div className="dashboardGrid">
          <div>
            <h3>Current Scenario</h3>
            <dl>
              <dt>Name</dt>
              <dd>{current?.current_scenario_name ?? '-'}</dd>
              <dt>ID</dt>
              <dd>{current?.current_scenario_id ?? '-'}</dd>
              <dt>Runtime State</dt>
              <dd>{runtimeState}</dd>
              <dt>Latest Event</dt>
              <dd>{latestEvent}</dd>
              <dt>Progress</dt>
              <dd>{batchFinished ? `${scenarioCompleted} completed` : 'observing'}</dd>
            </dl>
          </div>
          <div>
            <h3>Current Step / Event</h3>
            <dl>
              <dt>Observed Step</dt>
              <dd>{typeof current?.current_step_index === 'number' ? current.current_step_index : `${observedEvents} events observed`}</dd>
              {current?.current_step_label && (
                <>
                  <dt>Label</dt>
                  <dd>{current.current_step_label}</dd>
                </>
              )}
              {current?.current_step_action && (
                <>
                  <dt>Action</dt>
                  <dd>{current.current_step_action}</dd>
                </>
              )}
              {current?.current_step_target && (
                <>
                  <dt>Target</dt>
                  <dd>{current.current_step_target}</dd>
                </>
              )}
              {current?.current_step_result && (
                <>
                  <dt>Latest Result</dt>
                  <dd>{current.current_step_result}</dd>
                </>
              )}
              <dt>Latest Runtime Event</dt>
              <dd>{latestRuntimeEvent ?? '-'}</dd>
              <dt>Latest Step Log</dt>
              <dd>{current?.latest_step_log ?? current?.current_step_log ?? '-'}</dd>
            </dl>
          </div>
        </div>
        <div className="dashboardGrid">
          <div>
            <h3>{counterTitle}</h3>
            {!batchFinished && <small style={{ color: 'var(--color-text-dim)' }}>Observed during live log parsing. Final quality remains in Run History and reports.</small>}
            <div className="healthList">
              <span className="statusBadge healthOk">PASS {progress?.pass_count ?? 0}</span>
              <span className="statusBadge healthWarn">WARN {progress?.warn_count ?? 0}</span>
              <span className="statusBadge healthBad">FAIL {progress?.fail_count ?? 0}</span>
              <span className="statusBadge healthNeutral">REVIEW {progress?.review_count ?? 0}</span>
            </div>
          </div>
          <div>
            <h3>Preflight</h3>
            <div className="healthList">
              <span className={`statusBadge ${healthClass(preflight?.device_connected ?? undefined)}`}>device {preflight?.device_connected ?? '-'}</span>
              <span className={`statusBadge ${healthClass(preflight?.screen_awake ?? undefined)}`}>wake {preflight?.screen_awake ?? '-'}</span>
              <span className={`statusBadge ${healthClass(preflight?.unlock_swipe ?? undefined)}`}>unlock {preflight?.unlock_swipe ?? '-'}</span>
              <span className={`statusBadge ${healthClass(preflight?.app_foreground ?? undefined)}`}>app {preflight?.app_foreground ?? '-'}</span>
              <span className={`statusBadge ${healthClass(preflight?.helper ?? undefined)}`}>helper {preflight?.helper ?? '-'}</span>
              <span className={`statusBadge ${healthClass(preflight?.talkback ?? undefined)}`}>talkback {preflight?.talkback ?? '-'}</span>
            </div>
          </div>
        </div>
        <div className="dashboardGrid">
          <div>
            <h3>Latest Runtime Event</h3>
            <pre style={{ minHeight: '80px' }}>{latestRuntimeEvent ?? 'Waiting for runtime event...'}</pre>
          </div>
          <div>
            <h3>Raw Latest Log</h3>
            <pre style={{ minHeight: '80px' }}>{logs?.latest_log_line ?? 'Waiting for batch log...'}</pre>
          </div>
        </div>
      </div>
    </details>
  );
}
