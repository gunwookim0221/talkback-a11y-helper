import React from 'react';
import { HelperStatus, RunStatus, RuntimeDashboard } from '../api';
import { formatDuration, formatBytes, healthClass, languageLabel } from '../utils/formatters';

export interface RuntimeDashboardProps {
  dashboard: RuntimeDashboard | null;
  status: RunStatus | null;
  helper: HelperStatus | null;
  adb: Record<string, unknown> | null;
  pollingLatencyMs: number | null;
}

export function RuntimeDashboardPanel({ dashboard, status, helper, adb, pollingLatencyMs }: RuntimeDashboardProps) {
  return (
    <section className="panel dashboardPanel">
      <div className="panelHeader">
        <h2>Runtime Dashboard</h2>
        <div className={`statusBadge ${healthClass(status?.state)}`}>{status?.state ?? 'idle'}</div>
      </div>
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
    </section>
  );
}
