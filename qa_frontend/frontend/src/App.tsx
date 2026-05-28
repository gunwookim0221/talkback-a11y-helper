import { useEffect, useMemo, useState } from 'react';
import { api, OutputFile, RecentRun, RunStatus, Scenario, RuntimeDashboard } from './api';
import { applyPresetSelection, PRESETS, ScenarioPresetId } from './presets';
import { DEFAULT_SCENARIO_ID, initialScenarioSelection } from './selection';

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString();
}

function formatDuration(seconds: number) {
  if (seconds <= 0) {
    return '0s';
  }
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes === 0) {
    return `${remaining}s`;
  }
  return `${minutes}m ${remaining}s`;
}

function formatBytes(value: number) {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function healthClass(value: string | null | undefined) {
  const normalized = String(value ?? '').toLowerCase();
  if (['finished', 'passed', 'success', 'ok', 'enabled', 'cleared', 'completed'].includes(normalized)) {
    return 'healthOk';
  }
  if (['running', 'queued', 'unknown', 'dismissed_unverified', 'partial', 'stopped'].includes(normalized)) {
    return 'healthWarn';
  }
  if (['failed', 'error', 'blocked', 'adb_error', 'helper_error', 'uncleared'].includes(normalized)) {
    return 'healthBad';
  }
  return 'healthNeutral';
}

function scenarioRunText(run: RecentRun) {
  if (run.scenario_result_status === 'failed') {
    return `Scenarios failed (${run.failed_scenarios})`;
  }
  if (run.scenario_result_status === 'passed') {
    return 'Scenarios passed';
  }
  if (run.scenario_result_status === 'partial') {
    return `Partial (${run.completed_scenarios}/${run.total_scenarios})`;
  }
  return `Scenarios ${run.scenario_result_status}`;
}

function resolveSmokeSteps(scenarioId: string) {
  if ([
    'global_nav_main',
    'home_main',
    'devices_main',
    'life_main',
    'routines_main',
    'menu_main',
    'settings_entry_example',
  ].includes(scenarioId)) {
    return 6;
  }
  if (scenarioId.startsWith('life_') || scenarioId.startsWith('device_')) {
    return 8;
  }
  return 8;
}

function describeScenarioSteps(scenario: Scenario, mode: 'smoke' | 'full') {
  const sourceSteps = scenario.max_steps;
  if (mode === 'smoke') {
    const smokeSteps = resolveSmokeSteps(scenario.id);
    return sourceSteps ? `${smokeSteps} smoke steps · source ${sourceSteps}` : `${smokeSteps} smoke steps`;
  }
  return sourceSteps ? `${sourceSteps} full steps` : 'full steps use source config';
}

export default function App() {
  const [adb, setAdb] = useState<Record<string, unknown> | null>(null);
  const [helper, setHelper] = useState<Record<string, unknown> | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [dashboard, setDashboard] = useState<RuntimeDashboard | null>(null);
  const [log, setLog] = useState('');
  const [outputs, setOutputs] = useState<OutputFile[]>([]);
  const [recentRuns, setRecentRuns] = useState<RecentRun[]>([]);
  const [pollingLatencyMs, setPollingLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [launchMode, setLaunchMode] = useState<'warm' | 'clean'>('clean');
  const [plannedMode, setPlannedMode] = useState<'smoke' | 'full'>('smoke');

  const running = status?.state === 'running';
  const enabledCount = useMemo(() => scenarios.filter((scenario) => scenario.enabled).length, [scenarios]);
  const selectedCount = selected.size;
  const effectiveMode = status?.state === 'running' ? ((status.mode as 'smoke' | 'full' | null) ?? plannedMode) : plannedMode;
  const stepPolicyText =
    effectiveMode === 'smoke' ? 'reduced max_steps for selected scenarios' : 'source runtime_config max_steps';
  const currentRunSummary = useMemo(
    () => recentRuns.find((run) => run.run_id === status?.run_id) ?? null,
    [recentRuns, status?.run_id],
  );
  const currentRunReadyForDownload = Boolean(status?.run_id && status.state !== 'running' && status.log_path);

  async function refreshStatic() {
    const [adbStatus, helperStatus, scenarioResponse, outputResponse, recentRunsResponse] = await Promise.all([
      api.adbStatus(),
      api.helperStatus(),
      api.scenarios(),
      api.outputs(),
      api.recentRuns(),
    ]);
    setAdb(adbStatus);
    setHelper(helperStatus);
    setScenarios(scenarioResponse.scenarios);
    setSelected(initialScenarioSelection(scenarioResponse.scenarios));
    setOutputs(outputResponse.outputs);
    setRecentRuns(recentRunsResponse.runs);
  }

  async function refreshRun() {
    const started = performance.now();
    const [runStatus, runDashboard, runLog, outputResponse, recentRunsResponse] = await Promise.all([
      api.runStatus(),
      api.runDashboard(),
      api.runLog(),
      api.outputs(),
      api.recentRuns(),
    ]);
    setStatus(runStatus);
    setDashboard(runDashboard);
    setLog(runLog.text);
    setOutputs(outputResponse.outputs);
    setRecentRuns(recentRunsResponse.runs);
    setPollingLatencyMs(Math.round(performance.now() - started));
  }

  useEffect(() => {
    refreshStatic().then(refreshRun).catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      refreshRun().catch((err) => setError(String(err)));
    }, 1500);
    return () => window.clearInterval(id);
  }, []);

  async function start(mode: 'smoke' | 'full') {
    setError('');
    setPlannedMode(mode);
    try {
      setStatus(await api.startRun(mode, Array.from(selected), launchMode));
      await refreshRun();
    } catch (err) {
      setError(String(err));
    }
  }

  async function stop() {
    setError('');
    try {
      setStatus(await api.stopRun());
      await refreshRun();
    } catch (err) {
      setError(String(err));
    }
  }

  async function installHelper() {
    setError('');
    try {
      setHelper(await api.installHelper());
      setHelper(await api.helperStatus());
    } catch (err) {
      setError(String(err));
    }
  }

  function toggleScenario(id: string) {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  }

  function applyPreset(presetId: ScenarioPresetId) {
    setSelected(applyPresetSelection(presetId, scenarios, selected));
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>TalkBack QA Control Panel</h1>
          <p>Current Phase 1 runs use the existing runtime_config.json without rewriting it.</p>
        </div>
        <div className={`state state-${status?.state ?? 'idle'}`}>{status?.state ?? 'idle'}</div>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="grid">
        <article className="panel">
          <h2>ADB</h2>
          <div className="metric">{String(adb?.status ?? 'unknown')}</div>
          <pre>{JSON.stringify(adb?.devices ?? [], null, 2)}</pre>
        </article>

        <article className="panel">
          <h2>Helper</h2>
          <div className="metric">{String(helper?.status ?? 'unknown')}</div>
          <p>{helper?.enabled ? 'Helper accessibility service enabled' : 'Helper service is not ready'}</p>
          <button onClick={installHelper} disabled={running}>Install APK</button>
        </article>

        <article className="panel controls">
          <h2>Run</h2>
          <p className="runDescription">
            Smoke is a quick sanity check with reduced steps. Full is a regression run that keeps source
            runtime_config max_steps.
          </p>
          <p className="scenarioHint">Clean launch is the default and recommended mode for consistent SmartThings entry.</p>
          <div className="launchMode">
            <label>
              <input
                type="radio"
                name="launch_mode"
                checked={launchMode === 'clean'}
                onChange={() => setLaunchMode('clean')}
                disabled={running}
              />
              <span>Clean launch</span>
              <small>Recommended. Restarts SmartThings before running.</small>
            </label>
            <label>
              <input
                type="radio"
                name="launch_mode"
                checked={launchMode === 'warm'}
                onChange={() => setLaunchMode('warm')}
                disabled={running}
              />
              <span>Warm launch</span>
              <small>Debug. Keeps current SmartThings state when possible.</small>
            </label>
          </div>
          <div className="buttonRow">
            <button onClick={() => start('smoke')} disabled={running}>
              Smoke
              <small>Quick check · reduced steps</small>
            </button>
            <button onClick={() => start('full')} disabled={running}>
              Full
              <small>Full regression · source max_steps</small>
            </button>
            <button className="danger" onClick={stop} disabled={!running}>Stop</button>
          </div>
          <div className="modeSummary">
            <strong>Current mode:</strong> {effectiveMode === 'smoke' ? 'Smoke' : 'Full'}
            <span>Step policy: {status?.max_steps_policy ?? (effectiveMode === 'smoke' ? 'smoke_override' : 'source_preserved')}</span>
            <small>{stepPolicyText}</small>
          </div>
          <dl>
            <dt>Run ID</dt>
            <dd>{status?.run_id ?? '-'}</dd>
            <dt>Mode</dt>
            <dd>{status?.mode ?? '-'}</dd>
            <dt>Return</dt>
            <dd>{status?.returncode ?? '-'}</dd>
            <dt>Launch</dt>
            <dd>{status?.launch_mode ?? launchMode}</dd>
            <dt>Selected</dt>
            <dd>{selectedCount}</dd>
            <dt>Config</dt>
            <dd>{status?.runtime_config_path ?? '-'}</dd>
          </dl>
        </article>
      </section>

      <section className="panel preflightPanel">
        <h2>Runtime Preflight</h2>
        {status?.error && <div className="notice">{status.error}</div>}
        <dl>
          <dt>Preflight</dt>
          <dd>{status?.preflight_state ?? '-'}</dd>
          <dt>Reason</dt>
          <dd>{status?.preflight_reason ?? '-'}</dd>
          <dt>Helper</dt>
          <dd>{status?.helper_state ?? String(helper?.status ?? '-')}</dd>
          <dt>TalkBack</dt>
          <dd>{status?.talkback_state ?? '-'}</dd>
          <dt>Foreground</dt>
          <dd>{status?.foreground_package ?? '-'}</dd>
          <dt>Popup</dt>
          <dd>
            {status?.popup_detected
              ? `${status.popup_package ?? 'external'} · ${status.popup_result ?? status.popup_preflight_state ?? 'detected'}`
              : status?.popup_result ?? '-'}
          </dd>
          <dt>Settings</dt>
          <dd>{status?.accessibility_settings_opened ? 'opened on device' : '-'}</dd>
        </dl>
      </section>

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
            <span>Scenarios</span>
            <strong>{dashboard?.completed_scenarios ?? 0}/{dashboard?.scenario_progress.length ?? selectedCount}</strong>
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

      <section className="split">
        <article className="panel scenarios">
          <h2>Scenarios</h2>
          <p>
            {selectedCount} selected for this run. Source runtime_config has {enabledCount} enabled; source enabled is shown
            for reference and does not define the initial run selection.
          </p>
          <p className="scenarioHint">
            global_nav_main is selected by default for a predictable sanity check. The source enabled flags are display-only;
            this run uses your current checkbox selection.
          </p>
          <p className="scenarioHint">
            Presets only change scenario checkboxes. Use the Smoke or Full buttons above to choose the execution mode.
          </p>
          <div className="presetActions">
            {PRESETS.map((preset) => (
              <button key={preset.id} onClick={() => applyPreset(preset.id)} disabled={running}>
                {preset.label}
                <small>{preset.description}</small>
              </button>
            ))}
          </div>
          {!scenarios.some((scenario) => scenario.id === DEFAULT_SCENARIO_ID) && (
            <div className="notice">Default scenario global_nav_main is not available. Select a scenario before running.</div>
          )}
          <div className="scenarioList">
            {scenarios.map((scenario) => (
              <label key={scenario.id}>
                <input
                  type="checkbox"
                  checked={selected.has(scenario.id)}
                  onChange={() => toggleScenario(scenario.id)}
                  disabled={running}
                />
                <span>{scenario.id}</span>
                <small>{describeScenarioSteps(scenario, effectiveMode)}</small>
              </label>
            ))}
          </div>
        </article>

        <div className="stack">
          <article className="panel">
            <h2>Outputs</h2>
            <div className="downloadActions">
              <a
                className={`downloadButton ${!currentRunSummary?.xlsx_exists ? 'disabled' : ''}`}
                href={currentRunSummary?.xlsx_exists ? `/api/outputs/${encodeURIComponent(currentRunSummary.xlsx_filename ?? '')}` : undefined}
                aria-disabled={!currentRunSummary?.xlsx_exists}
              >
                Download XLSX
              </a>
              <a
                className={`downloadButton ${!currentRunReadyForDownload ? 'disabled' : ''}`}
                href={currentRunReadyForDownload ? '/api/run/log/download' : undefined}
                aria-disabled={!currentRunReadyForDownload}
              >
                Download Log
              </a>
            </div>
            {currentRunSummary && (
              <p className="scenarioHint">
                Current run downloads: {currentRunSummary.xlsx_filename ?? 'xlsx pending'} · {currentRunSummary.log_filename ?? 'log pending'}
              </p>
            )}
            <div className="outputList">
              {outputs.map((file) => (
                <a key={file.filename} href={`/api/outputs/${encodeURIComponent(file.filename)}`}>
                  <span>{file.filename}</span>
                  <small>{Math.round(file.size / 1024)} KB · {formatTime(file.modified)}</small>
                </a>
              ))}
            </div>
          </article>

          <article className="panel">
            <h2>Recent Runs</h2>
            <div className="recentRuns">
              {recentRuns.map((run) => (
                <div key={run.run_id} className="recentRunRow">
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
          </article>
        </div>
      </section>

      <section className="panel logPanel">
        <h2>Log Tail</h2>
        <pre>{log || 'No log yet.'}</pre>
      </section>
    </main>
  );
}
