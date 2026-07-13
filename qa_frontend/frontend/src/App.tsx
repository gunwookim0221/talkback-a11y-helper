import { useEffect, useMemo, useRef, useState } from 'react';
import { api, HelperStatus, OutputFile, RecentRun, RunStatus, Scenario, RuntimeDashboard } from './api';
import { applyPresetSelection, PRESETS, ScenarioPresetId } from './presets';
import { DEFAULT_SCENARIO_ID, initialScenarioSelection } from './selection';
import { ADBPanel } from './components/ADBPanel';
import { HelperPanel } from './components/HelperPanel';
import { RunPanel } from './components/RunPanel';
import { RuntimeDashboardPanel } from './components/RuntimeDashboard';
import { PluginDiscoveryPanel } from './components/PluginDiscoveryPanel';

import { RecentRunsPanel } from './components/RecentRunsPanel';
import { CorpusReadinessPanel } from './components/CorpusReadinessPanel';

import { formatTime, formatDuration, formatBytes, healthClass, helperBadgeText, scenarioRunText, resolveSmokeSteps, describeScenarioSteps, languageLabel, scenarioReasonText } from './utils/formatters';
import { useRunPolling } from './hooks/useRunPolling';
import { groupScenarios } from './utils/scenarioGrouping';
import { getDevicePluginName } from './utils/devicePluginMeta';
import { getLifePluginName } from './utils/lifePluginMeta';
import { getNavigationName, isOptionalNavigationScenario } from './utils/navigationMeta';

type LanguageMode = 'current' | 'ko-KR' | 'en-US';

export default function App() {
  const [adb, setAdb] = useState<Record<string, unknown> | null>(null);
  const [helper, setHelper] = useState<HelperStatus | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [outputs, setOutputs] = useState<OutputFile[]>([]);
  const [recentRuns, setRecentRuns] = useState<RecentRun[]>([]);
  const [selectedRecentRunId, setSelectedRecentRunId] = useState<string | null>(null);
  const [launchMode, setLaunchMode] = useState<'warm' | 'clean'>('clean');
  const [languageMode, setLanguageMode] = useState<LanguageMode>('current');
  const [plannedMode, setPlannedMode] = useState<'smoke' | 'full'>('smoke');
  const [enableCoverageProbe, setEnableCoverageProbe] = useState(false);
  const [shadowValidation, setShadowValidation] = useState(false);
  const [evidenceLedger, setEvidenceLedger] = useState(true);
  const [identityShadowV2, setIdentityShadowV2] = useState(true);
  const [traversalIdentityV2, setTraversalIdentityV2] = useState(true);
  const [fixTalkBackRunning, setFixTalkBackRunning] = useState(false);
  const [fixTalkBackMessage, setFixTalkBackMessage] = useState<string | null>(null);
  const preflightRef = useRef<HTMLElement | null>(null);
  const scrolledBlockedRunRef = useRef<string | null>(null);

  const {
    status,
    dashboard,
    batchStatus,
    log,
    pollingLatencyMs,
    error,
    clearError,
    reportError,
    refreshRun,
  } = useRunPolling({
    onOutputsChanged: () => {
      api.outputs()
        .then((res) => setOutputs(res.outputs))
        .catch((err) => console.warn('Outputs poll failed:', err));
    },
    onRunFinished: () => {
      api.recentRuns()
        .then((res) => setRecentRuns(res.runs))
        .catch((err) => console.warn('Recent runs poll failed:', err));
    },
  });

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
    const results = await Promise.allSettled([
      api.adbStatus().then(setAdb),
      api.helperStatus().then(setHelper),
      api.scenarios().then((response) => {
        setScenarios(response.scenarios);
        setSelected(initialScenarioSelection(response.scenarios));
      }),
      api.outputs().then((response) => setOutputs(response.outputs)),
      api.recentRuns().then((response) => setRecentRuns(response.runs)),
    ]);
    const rejected = results.find((result) => result.status === 'rejected');
    if (rejected?.status === 'rejected') {
      throw rejected.reason;
    }
  }

  useEffect(() => {
    refreshStatic().then(refreshRun).catch((err) => reportError(err));
  }, [refreshRun]);

  useEffect(() => {
    setEnableCoverageProbe(plannedMode === 'full');
  }, [plannedMode]);

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
    clearError();
    setPlannedMode(mode);
    try {
      await api.startRun(
        mode,
        Array.from(selected),
        launchMode,
        languageMode,
        enableCoverageProbe,
        mode === 'full' && shadowValidation,
        evidenceLedger,
        identityShadowV2,
        traversalIdentityV2,
      );
      await refreshRun();
    } catch (err) {
      reportError(err);
    }
  }

  async function stop() {
    clearError();
    try {
      if (batchStatus?.state === 'running') {
        await api.stopBatch();
      } else {
        await api.stopRun();
      }
      await refreshRun();
    } catch (err) {
      reportError(err);
    }
  }

  async function installHelper() {
    clearError();
    try {
      await api.installHelper();
      setHelper(await api.helperStatus());
    } catch (err) {
      reportError(err);
      api.helperStatus().then(setHelper).catch(() => undefined);
    }
  }

  async function enableHelper() {
    clearError();
    try {
      await api.enableHelper();
      setHelper(await api.helperStatus());
    } catch (err) {
      reportError(err);
      api.helperStatus().then(setHelper).catch(() => undefined);
    }
  }

  async function openAccessibilitySettings() {
    clearError();
    try {
      await api.openAccessibilitySettings();
      setHelper(await api.helperStatus());
    } catch (err) {
      reportError(err);
    }
  }

  async function openLanguageSettings() {
    clearError();
    try {
      await api.openLanguageSettings();
      await refreshRun();
    } catch (err) {
      reportError(err);
    }
  }

  async function enableTalkBack() {
    clearError();
    try {
      await api.enableTalkBack();
      await refreshRun();
    } catch (err) {
      reportError(err);
      refreshRun().catch(() => undefined);
    }
  }

  async function fixTalkBack() {
    clearError();
    setFixTalkBackMessage(null);
    setFixTalkBackRunning(true);
    try {
      const result = await api.fixTalkBack();
      setFixTalkBackMessage(result.message ?? (result.ok ? 'TalkBack is ready.' : 'TalkBack is still not ready.'));
      await refreshRun();
    } catch (err) {
      reportError(err);
      refreshRun().catch(() => undefined);
    } finally {
      setFixTalkBackRunning(false);
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

  function getScenarioHealth(scenarioId: string) {
    const summaryResult = currentRunSummary?.scenarios?.find(s => s.id === scenarioId);
    if (summaryResult) {
      if (summaryResult.status === 'passed') return 'PASS';
      if (summaryResult.status === 'warning') return 'WARN';
      if (summaryResult.status === 'failed') return 'FAIL';
    }
    const dashResult = dashboard?.scenario_progress?.find(p => p.id === scenarioId);
    if (dashResult) {
      if (dashResult.status === 'completed') return 'PASS';
      if (dashResult.status === 'failed') return 'FAIL';
    }
    return null;
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
            <button onClick={fixTalkBack} disabled={running || fixTalkBackRunning}>
              {fixTalkBackRunning ? 'Fixing TalkBack...' : 'Fix TalkBack'}
            </button>
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
          <div className="actionBannerActions">
            <button onClick={fixTalkBack} disabled={running || fixTalkBackRunning}>
              {fixTalkBackRunning ? 'Fixing TalkBack...' : 'Fix TalkBack'}
            </button>
            <button onClick={openAccessibilitySettings} disabled={running}>Open Accessibility Settings</button>
          </div>
        </section>
      )}

      {error && <div className="error">{error}</div>}
      {fixTalkBackMessage && <div className="notice">{fixTalkBackMessage}</div>}

      <section className="grid2">
        <ADBPanel adb={adb} />

        <HelperPanel
          helper={helper}
          running={running}
          installHelper={installHelper}
          enableHelper={enableHelper}
          openAccessibilitySettings={openAccessibilitySettings}
        />
      </section>

      <section style={{ marginTop: '14px' }}>
        <RunPanel
          launchMode={launchMode}
          setLaunchMode={setLaunchMode}
          languageMode={languageMode}
          setLanguageMode={setLanguageMode}
          plannedMode={plannedMode}
          setPlannedMode={setPlannedMode}
          running={running}
          start={start}
          stop={stop}
          effectiveMode={effectiveMode}
          status={status}
          stepPolicyText={stepPolicyText}
          selectedCount={selectedCount}
          selectedScenarios={selected}
          enableCoverageProbe={enableCoverageProbe}
          setEnableCoverageProbe={setEnableCoverageProbe}
          shadowValidation={shadowValidation}
          setShadowValidation={setShadowValidation}
          evidenceLedger={evidenceLedger}
          setEvidenceLedger={setEvidenceLedger}
          identityShadowV2={identityShadowV2}
          setIdentityShadowV2={setIdentityShadowV2}
          traversalIdentityV2={traversalIdentityV2}
          setTraversalIdentityV2={setTraversalIdentityV2}
        />
      </section>

      <section style={{ marginTop: '14px' }}>
        <PluginDiscoveryPanel running={running} reportError={reportError} />
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
              <button onClick={fixTalkBack} disabled={running || fixTalkBackRunning}>
                {fixTalkBackRunning ? 'Fixing TalkBack...' : 'Fix TalkBack'}
              </button>
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

      <RuntimeDashboardPanel
        dashboard={dashboard}
        batchStatus={batchStatus}
        status={status}
        helper={helper}
        adb={adb}
        pollingLatencyMs={pollingLatencyMs}
      />

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
            Presets only change scenario checkboxes. Use Selected Smoke or Selected Full above to choose the execution mode.
          </p>
          <p className="scenarioHint">
            Selected Full does not mean all plugins. Use All Plugins to run every plugin scenario, or All Scenarios to
            include navigation and main scenarios as well.
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
          <div className="scenarioGroupsContainer">
            {groupScenarios(scenarios).map((group) => (
              <div key={group.title} className="scenarioGroup">
                <h3 style={{ margin: '1rem 0 0.5rem', fontSize: '1rem', color: 'var(--color-text-dim)' }}>{group.title}</h3>
                <div className="scenarioList">
                  {group.scenarios.map((scenario) => {
                    let pluginName: string | null = null;
                    if (group.title === 'Device Plugins') {
                      pluginName = getDevicePluginName(scenario.id);
                    } else if (group.title === 'Life Plugins') {
                      pluginName = getLifePluginName(scenario.id);
                    } else if (group.title === 'Navigation') {
                      pluginName = getNavigationName(scenario.id);
                    }
                    const showOptionalBadge = group.title === 'Navigation' && isOptionalNavigationScenario(scenario.id);
                    return (
                      <label 
                        key={scenario.id} 
                        style={pluginName ? {
                          display: 'flex',
                          alignItems: 'flex-start',
                          padding: '0.75rem',
                          border: '1px solid var(--color-border)',
                          borderRadius: '6px',
                          background: 'var(--color-bg-alt, rgba(0,0,0,0.03))',
                          gap: '0.5rem'
                        } : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={selected.has(scenario.id)}
                          onChange={() => toggleScenario(scenario.id)}
                          disabled={running}
                          style={pluginName ? { marginTop: '0.2rem' } : undefined}
                        />
                        {pluginName ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            <strong style={{ fontSize: '1.05em', display: 'flex', gap: '8px', alignItems: 'center' }}>
                              {pluginName}
                              {showOptionalBadge && (
                                <span
                                  style={{
                                    fontSize: '10px',
                                    fontWeight: 500,
                                    padding: '2px 6px',
                                    borderRadius: '999px',
                                    border: '1px solid var(--color-border)',
                                    color: 'var(--color-text-dim)',
                                    background: 'var(--color-bg)',
                                  }}
                                >
                                  optional
                                </span>
                              )}
                              {getScenarioHealth(scenario.id) && (
                                <span className={`statusBadge ${getScenarioHealth(scenario.id) === 'PASS' ? 'healthOk' : getScenarioHealth(scenario.id) === 'WARN' ? 'healthWarn' : 'healthBad'}`} style={{ fontSize: '10px', padding: '2px 6px' }}>
                                  {getScenarioHealth(scenario.id)}
                                </span>
                              )}
                            </strong>
                            <span style={{ fontSize: '0.85em', color: 'var(--color-text-dim)' }}>{scenario.id}</span>
                            <small>{describeScenarioSteps(scenario, effectiveMode)}</small>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            <span style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                              {scenario.id}
                              {getScenarioHealth(scenario.id) && (
                                <span className={`statusBadge ${getScenarioHealth(scenario.id) === 'PASS' ? 'healthOk' : getScenarioHealth(scenario.id) === 'WARN' ? 'healthWarn' : 'healthBad'}`} style={{ fontSize: '10px', padding: '2px 6px' }}>
                                  {getScenarioHealth(scenario.id)}
                                </span>
                              )}
                            </span>
                            <small>{describeScenarioSteps(scenario, effectiveMode)}</small>
                          </div>
                        )}
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </article>

        <div className="stack">
          <CorpusReadinessPanel />
          <RecentRunsPanel
            recentRuns={recentRuns}
            selectedRecentRunId={selectedRecentRunId}
            setSelectedRecentRunId={setSelectedRecentRunId}
            selectedRecentRun={selectedRecentRun}
            selectedFailedScenarios={selectedFailedScenarios}
            selectedWarningScenarios={selectedWarningScenarios}
            selectedPassedScenarios={selectedPassedScenarios}
          />
        </div>
      </section>

      <section className="panel logPanel">
        <h2>Log Tail</h2>
        <pre>{log || 'No log yet.'}</pre>
      </section>
    </main>
  );
}
