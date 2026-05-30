import { useEffect, useMemo, useRef, useState } from 'react';
import { api, HelperStatus, OutputFile, RecentRun, RunStatus, Scenario, RuntimeDashboard } from './api';
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
  if (['finished', 'passed', 'success', 'ok', 'enabled', 'cleared'].includes(normalized)) {
    return 'healthOk';
  }
  if ([
    'running',
    'queued',
    'unknown',
    'dismissed_unverified',
    'partial',
    'stopped',
    'warning',
    'disabled',
    'not_installed',
    'apk_not_found',
    'needs setup',
  ].includes(normalized)) {
    return 'healthWarn';
  }
  if (['failed', 'error', 'blocked', 'adb_error', 'helper_error', 'uncleared'].includes(normalized)) {
    return 'healthBad';
  }
  return 'healthNeutral';
}

function helperBadgeText(status: string | undefined) {
  switch (status) {
    case 'ok':
      return 'OK';
    case 'disabled':
      return 'Needs setup';
    case 'not_installed':
      return 'Not installed';
    case 'apk_not_found':
      return 'APK not found';
    case 'error':
      return 'Error';
    default:
      return status ?? 'unknown';
  }
}

function scenarioRunText(run: RecentRun) {
  if (run.scenario_result_status === 'failed') {
    return `Scenarios failed (${run.failed_scenarios})`;
  }
  if (run.scenario_result_status === 'passed') {
    return 'Scenarios passed';
  }
  if (run.scenario_result_status === 'warning') {
    return `Scenarios warning (${run.warning_scenarios ?? 0})`;
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

type LanguageMode = 'current' | 'ko-KR' | 'en-US';

function languageLabel(languageMode: string | null | undefined) {
  switch (languageMode) {
    case 'ko-KR':
      return 'Korean (ko-KR)';
    case 'en-US':
      return 'English (en-US)';
    case 'current':
      return 'Current device language';
    default:
      return languageMode ?? '-';
  }
}

function scenarioReasonText(scenario: NonNullable<RecentRun['scenarios']>[number]) {
  return scenario.reason || scenario.stop_reason || scenario.traversal_result || '';
}

export default function App() {
  const [adb, setAdb] = useState<Record<string, unknown> | null>(null);
  const [helper, setHelper] = useState<HelperStatus | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [dashboard, setDashboard] = useState<RuntimeDashboard | null>(null);
  const [log, setLog] = useState('');
  const [outputs, setOutputs] = useState<OutputFile[]>([]);
  const [recentRuns, setRecentRuns] = useState<RecentRun[]>([]);
  const [selectedRecentRunId, setSelectedRecentRunId] = useState<string | null>(null);
  const [pollingLatencyMs, setPollingLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [launchMode, setLaunchMode] = useState<'warm' | 'clean'>('clean');
  const [languageMode, setLanguageMode] = useState<LanguageMode>('current');
  const [plannedMode, setPlannedMode] = useState<'smoke' | 'full'>('smoke');
  const preflightRef = useRef<HTMLElement | null>(null);
  const scrolledBlockedRunRef = useRef<string | null>(null);

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
  const selectedRecentRun = useMemo(
    () =>
      recentRuns.find((run) => run.run_id === selectedRecentRunId) ??
      currentRunSummary ??
      recentRuns[0] ??
      null,
    [currentRunSummary, recentRuns, selectedRecentRunId],
  );
  const selectedRunScenarios = selectedRecentRun?.scenarios ?? [];
  const selectedFailedScenarios = selectedRunScenarios.filter((scenario) => scenario.status === 'failed');
  const selectedWarningScenarios = selectedRunScenarios.filter((scenario) => scenario.status === 'warning');
  const selectedPassedScenarios = selectedRunScenarios.filter((scenario) => scenario.status === 'passed');
  const currentRunReadyForDownload = Boolean(status?.run_id && status.state !== 'running' && status.log_path);
  const languageStatus = (status?.language_status ?? {}) as Record<string, unknown>;
  const manualLanguageChangeRequired = Boolean(
    status?.manual_language_change_required || languageStatus.manual_language_change_required,
  );
  const requestedLocale = String(status?.target_locale ?? languageStatus.target_locale ?? languageMode);
  const currentDeviceLocale = String(status?.device_locale ?? languageStatus.device_locale ?? '-');
  const languageError = String(status?.language_error ?? languageStatus.error ?? '');
  const talkBackDisabled = status?.talkback_state === 'disabled';
  const helperBlocked = helper?.status === 'disabled' || helper?.status === 'apk_not_found';
  const genericPreflightBlocked = Boolean(
    status?.state === 'error' && !manualLanguageChangeRequired && !talkBackDisabled && status?.preflight_state,
  );
  const shouldScrollToPreflight = Boolean(
    manualLanguageChangeRequired || talkBackDisabled || ['blocked', 'error'].includes(String(status?.preflight_state ?? '')),
  );

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

  useEffect(() => {
    if (!shouldScrollToPreflight || !status?.run_id) {
      return;
    }
    if (scrolledBlockedRunRef.current === status.run_id) {
      return;
    }
    scrolledBlockedRunRef.current = status.run_id;
    preflightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [shouldScrollToPreflight, status?.run_id]);

  async function start(mode: 'smoke' | 'full') {
    setError('');
    setPlannedMode(mode);
    try {
      setStatus(await api.startRun(mode, Array.from(selected), launchMode, languageMode));
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
      await api.installHelper();
      setHelper(await api.helperStatus());
    } catch (err) {
      setError(String(err));
      api.helperStatus().then(setHelper).catch(() => undefined);
    }
  }

  async function enableHelper() {
    setError('');
    try {
      await api.enableHelper();
      setHelper(await api.helperStatus());
    } catch (err) {
      setError(String(err));
      api.helperStatus().then(setHelper).catch(() => undefined);
    }
  }

  async function openAccessibilitySettings() {
    setError('');
    try {
      await api.openAccessibilitySettings();
      setHelper(await api.helperStatus());
    } catch (err) {
      setError(String(err));
    }
  }

  async function openLanguageSettings() {
    setError('');
    try {
      await api.openLanguageSettings();
      await refreshRun();
    } catch (err) {
      setError(String(err));
    }
  }

  async function enableTalkBack() {
    setError('');
    try {
      await api.enableTalkBack();
      await refreshRun();
    } catch (err) {
      setError(String(err));
      refreshRun().catch(() => undefined);
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

      {manualLanguageChangeRequired && (
        <section className="actionBanner actionBannerWarn">
          <div>
            <h2>Run blocked: language change required</h2>
            <p>
              This device does not allow changing system language via ADB. Open Language Settings and change the
              language manually, then run again with Current device language.
            </p>
            <small>Requested: {requestedLocale} · Current device locale: {currentDeviceLocale}</small>
            {languageError && <small>{languageError}</small>}
          </div>
          <div className="actionBannerActions">
            <button onClick={openLanguageSettings} disabled={running}>Open Language Settings</button>
          </div>
        </section>
      )}

      {!manualLanguageChangeRequired && talkBackDisabled && (
        <section className="actionBanner actionBannerWarn">
          <div>
            <h2>Run blocked: TalkBack disabled</h2>
            <p>TalkBack A11y Helper is enabled, but Samsung/Google TalkBack is disabled.</p>
            <small>TalkBack will be enabled on the connected device.</small>
          </div>
          <div className="actionBannerActions">
            <button onClick={enableTalkBack} disabled={running}>Enable TalkBack via ADB</button>
            <button onClick={openAccessibilitySettings} disabled={running}>Open Accessibility Settings</button>
          </div>
        </section>
      )}

      {!manualLanguageChangeRequired && !talkBackDisabled && helperBlocked && (
        <section className="actionBanner actionBannerWarn">
          <div>
            <h2>Setup required: TalkBack A11y Helper</h2>
            <p>
              {helper?.status === 'apk_not_found'
                ? 'Build the TalkBack A11y Helper APK before installing it on the device.'
                : 'TalkBack A11y Helper is installed, but its accessibility service is disabled.'}
            </p>
            {helper?.build_command && <small>Build command: {helper.build_command}</small>}
          </div>
          <div className="actionBannerActions">
            {helper?.status === 'disabled' && <button onClick={enableHelper} disabled={running}>Enable Helper via ADB</button>}
            {helper?.status === 'disabled' && <button onClick={openAccessibilitySettings} disabled={running}>Open Accessibility Settings</button>}
            {helper?.status === 'apk_not_found' && <button disabled>Install APK</button>}
          </div>
        </section>
      )}

      {genericPreflightBlocked && (
        <section className="actionBanner actionBannerBad">
          <div>
            <h2>Run blocked: runtime preflight</h2>
            <p>{status?.error ?? 'Runtime preflight blocked the run.'}</p>
            <small>Reason: {status?.preflight_reason ?? '-'}</small>
          </div>
        </section>
      )}

      {error && <div className="error">{error}</div>}

      <section className="grid">
        <article className="panel">
          <h2>ADB</h2>
          <div className="metric">{String(adb?.status ?? 'unknown')}</div>
          <pre>{JSON.stringify(adb?.devices ?? [], null, 2)}</pre>
        </article>

        <article className="panel">
          <div className="panelHeader">
            <h2>{helper?.helper_name ?? 'TalkBack A11y Helper'}</h2>
            <span className={`statusBadge ${healthClass(helper?.status)}`}>{helperBadgeText(helper?.status)}</span>
          </div>
          <div className="helperDetails">
            {helper?.status === 'ok' && (
              <>
                <p>APK installed</p>
                <p>Accessibility service enabled</p>
              </>
            )}
            {helper?.status === 'disabled' && (
              <>
                <p>APK installed</p>
                <p>Accessibility service disabled</p>
              </>
            )}
            {helper?.status === 'not_installed' && (
              <>
                <p>APK found</p>
                <p>Package not installed on device</p>
              </>
            )}
            {helper?.status === 'apk_not_found' && (
              <>
                <p>Build helper APK first</p>
                <code>{helper.build_command}</code>
                <small>Searched: {helper.apk_searched.join(', ')}</small>
              </>
            )}
            {helper?.status === 'error' && <p>{helper.error ?? 'Backend or ADB error'}</p>}
            {helper?.apk_path && <small>APK path: {helper.apk_path}</small>}
          </div>
          <div className="helperActions">
            {helper?.status === 'ok' && (
              <>
                <button onClick={installHelper} disabled={running}>Reinstall APK</button>
                <button onClick={openAccessibilitySettings} disabled={running}>Open Accessibility Settings</button>
              </>
            )}
            {helper?.status === 'disabled' && (
              <>
                <button onClick={enableHelper} disabled={running}>Enable via ADB</button>
                <button onClick={openAccessibilitySettings} disabled={running}>Open Accessibility Settings</button>
              </>
            )}
            {helper?.status === 'not_installed' && (
              <button onClick={installHelper} disabled={running}>Install APK</button>
            )}
            {helper?.status === 'apk_not_found' && (
              <button disabled>Install APK</button>
            )}
          </div>
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
          <div className="languageMode">
            <strong>Language</strong>
            <label>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'current'}
                onChange={() => setLanguageMode('current')}
                disabled={running}
              />
              <span>Current device language</span>
              <small>Run without changing the device language.</small>
            </label>
            <label>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'ko-KR'}
                onChange={() => setLanguageMode('ko-KR')}
                disabled={running}
              />
              <span>Korean (ko-KR)</span>
              <small>Switch to Korean before running.</small>
            </label>
            <label>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'en-US'}
                onChange={() => setLanguageMode('en-US')}
                disabled={running}
              />
              <span>English (en-US)</span>
              <small>Switch to English before running.</small>
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
            <dt>Language</dt>
            <dd>{languageLabel(status?.language_mode ?? languageMode)}</dd>
            <dt>Locale</dt>
            <dd>{status?.device_locale ?? '-'}</dd>
            <dt>Selected</dt>
            <dd>{selectedCount}</dd>
            <dt>Config</dt>
            <dd>{status?.runtime_config_path ?? '-'}</dd>
          </dl>
        </article>
      </section>

      <section className="panel preflightPanel" ref={preflightRef}>
        <h2>Runtime Preflight</h2>
        {status?.error && <div className="notice">{status.error}</div>}
        {manualLanguageChangeRequired && (
          <div className="notice">
            <p>
              The device locale did not verify as {requestedLocale}. Open Language Settings and change the language
              manually, then run again with Current device language.
            </p>
            <div className="helperActions">
              <button onClick={openLanguageSettings} disabled={running}>Open Language Settings</button>
            </div>
          </div>
        )}
        {status?.talkback_state === 'disabled' && (
          <div className="notice">
            <p>TalkBack A11y Helper is enabled, but Samsung/Google TalkBack is disabled. Enable TalkBack and retry.</p>
            <p>TalkBack will be enabled on the connected device.</p>
            <div className="helperActions">
              <button onClick={enableTalkBack} disabled={running}>Enable TalkBack via ADB</button>
              <button onClick={openAccessibilitySettings} disabled={running}>Open Accessibility Settings</button>
            </div>
          </div>
        )}
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
        </div>
      </section>

      <section className="panel logPanel">
        <h2>Log Tail</h2>
        <pre>{log || 'No log yet.'}</pre>
      </section>
    </main>
  );
}
