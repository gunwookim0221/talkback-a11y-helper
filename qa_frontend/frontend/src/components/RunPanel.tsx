import React, { useState, useEffect, useMemo, useRef } from 'react';
import { api } from '../api';
import type { RunStatus, DeviceInfo, BatchStatus } from '../api';
import {
  currentLanguageLabel,
  getValidationReadiness,
  getRunSafety,
  resolveRunProfile,
} from '../runProfiles';
import type { RunProfileId } from '../runProfiles';

type LanguageMode = 'current' | 'ko-KR' | 'en-US';

export interface RunPanelProps {
  launchMode: 'warm' | 'clean';
  setLaunchMode: (mode: 'warm' | 'clean') => void;
  languageMode: LanguageMode;
  setLanguageMode: (mode: LanguageMode) => void;
  plannedMode: 'smoke' | 'full';
  setPlannedMode: (mode: 'smoke' | 'full') => void;
  running: boolean;
  start: (mode: 'smoke' | 'full') => void;
  stop: () => void;
  effectiveMode: 'smoke' | 'full';
  status: RunStatus | null;
  batchStatus: BatchStatus | null;
  stepPolicyText: string;
  selectedCount: number;
  fullValidationScenarioIds: readonly string[];
  onSelectFullValidation: () => void;
  selectedScenarios: Set<string>;
  effectiveLocale?: string | null;
  enableCoverageProbe: boolean;
  setEnableCoverageProbe: (enabled: boolean) => void;
  shadowValidation: boolean;
  setShadowValidation: (enabled: boolean) => void;
  evidenceLedger: boolean;
  setEvidenceLedger: (enabled: boolean) => void;
  identityShadowV2: boolean;
  setIdentityShadowV2: (enabled: boolean) => void;
  traversalIdentityV2: boolean;
  setTraversalIdentityV2: (enabled: boolean) => void;
  traversalProfiler: boolean;
  setTraversalProfiler: (enabled: boolean) => void;
  onSelectedDeviceReadinessChange?: (devices: readonly DeviceInfo[], loaded: boolean) => void;
}

function isReadyDevice(device: DeviceInfo): boolean {
  return device.state === 'device' && device.helper_ready === true && device.talkback_enabled === true;
}

function readyDeviceSerials(devices: readonly DeviceInfo[]): Set<string> {
  return new Set(
    [...devices]
      .filter(isReadyDevice)
      .sort((left, right) => left.serial.localeCompare(right.serial))
      .map((device) => device.serial),
  );
}

function shortDeviceId(serial: string): string {
  return serial.length > 12 ? `${serial.slice(0, 4)}…${serial.slice(-4)}` : serial;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function RunPanel({
  launchMode,
  setLaunchMode,
  languageMode,
  setLanguageMode,
  plannedMode,
  setPlannedMode,
  running,
  start,
  stop,
  effectiveMode,
  status,
  batchStatus,
  stepPolicyText,
  selectedCount,
  fullValidationScenarioIds,
  onSelectFullValidation,
  selectedScenarios,
  effectiveLocale,
  enableCoverageProbe,
  setEnableCoverageProbe,
  shadowValidation,
  setShadowValidation,
  evidenceLedger, setEvidenceLedger, identityShadowV2, setIdentityShadowV2,
  traversalIdentityV2, setTraversalIdentityV2,
  traversalProfiler, setTraversalProfiler,
  onSelectedDeviceReadinessChange,
}: RunPanelProps) {
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [devicesLoaded, setDevicesLoaded] = useState(false);
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [selectedDevices, setSelectedDevices] = useState<Set<string>>(new Set());
  const [runProfile, setRunProfile] = useState<RunProfileId>('full-validation');
  const [pendingConfirmation, setPendingConfirmation] = useState<'smoke' | 'custom' | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [launchInFlight, setLaunchInFlight] = useState(false);
  const confirmationRef = useRef<HTMLDivElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const launchInFlightRef = useRef(false);

  const fetchDevices = async () => {
    setLoadingDevices(true);
    try {
      const list = await api.devices();
      setDevices(list);
      setSelectedDevices(readyDeviceSerials(list));
      setDevicesLoaded(true);
    } catch (err) {
      console.error('Failed to fetch devices', err);
      try {
        const adb = await api.adbStatus();
        const fallback = adb.devices.map(device => ({
          ...device,
          model: 'Unknown',
          helper_ready: null,
          talkback_enabled: null,
          foreground_package: null,
        }));
        setDevices(fallback);
        setSelectedDevices(readyDeviceSerials(fallback));
        setDevicesLoaded(true);
      } catch (fallbackErr) {
        console.error('Failed to fetch fallback ADB devices', fallbackErr);
        setDevicesLoaded(true);
      }
    } finally {
      setLoadingDevices(false);
    }
  };

  useEffect(() => {
    fetchDevices();
  }, []);

  const toggleDevice = (serial: string) => {
    setSelectedDevices(prev => {
      const next = new Set(prev);
      if (next.has(serial)) next.delete(serial);
      else next.add(serial);
      return next;
    });
  };

  const controlsLocked = running || batchStatus?.state === 'running' || launchInFlight;
  const customOptionsEnabled = runProfile === 'custom-debug' && !controlsLocked;
  const selectedDeviceRecords = useMemo(
    () => devices.filter((device) => selectedDevices.has(device.serial)),
    [devices, selectedDevices],
  );

  useEffect(() => {
    onSelectedDeviceReadinessChange?.(selectedDeviceRecords, devicesLoaded);
  }, [devicesLoaded, onSelectedDeviceReadinessChange, selectedDeviceRecords]);

  const selectedReadyDeviceCount = selectedDeviceRecords.filter(isReadyDevice).length;
  const selectedHelperReady = selectedDeviceRecords.length > 0
    ? selectedDeviceRecords.every((device) => device.helper_ready === true)
    : null;
  const selectedTalkBackEnabled = selectedDeviceRecords.length > 0
    ? selectedDeviceRecords.every((device) => device.talkback_enabled === true)
    : null;
  const showLegacyShadowValidation =
    import.meta.env.DEV || import.meta.env.VITE_SHOW_LEGACY_SHADOW_VALIDATION === 'true';
  const readiness = getValidationReadiness({
    launchMode,
    plannedMode,
    enableCoverageProbe,
    shadowValidation,
    evidenceLedger,
    identityShadowV2,
    traversalIdentityV2,
    traversalProfiler,
    selectedScenarioCount: selectedCount,
    fullValidationScenarioCount: fullValidationScenarioIds.length,
  });
  const runSafety = getRunSafety({
    selectedScenarioIds: selectedScenarios,
    fullValidationScenarioIds,
    selectedDeviceCount: selectedDevices.size,
    selectedReadyDeviceCount,
    controlsLocked,
    helperReady: selectedHelperReady,
    talkbackEnabled: selectedTalkBackEnabled,
  });
  const profileBlockers =
    runSafety.runKind === 'full-validation' && plannedMode === 'full' && runProfile === 'full-validation'
      ? readiness.reasons
      : [];
  const runBlockers = [...runSafety.reasons, ...profileBlockers];
  const runDisabled = controlsLocked || !runSafety.ready || profileBlockers.length > 0;
  const runLabel = plannedMode === 'smoke'
    ? 'Quick Smoke'
    : runSafety.runKind === 'full-validation'
      ? 'Full Validation'
      : 'Custom Run';
  const fullProfileActive =
    runProfile === 'full-validation' && plannedMode === 'full' && runSafety.runKind === 'full-validation';
  const deviceCountClass = devices.length === 1 ? 'deviceCountOne' : devices.length <= 5 ? 'deviceCountFew' : 'deviceCountMany';

  useEffect(() => {
    if (!launchInFlight || (!running && batchStatus?.state !== 'running')) return;
    launchInFlightRef.current = false;
    setLaunchInFlight(false);
  }, [batchStatus?.state, launchInFlight, running]);

  useEffect(() => {
    if (!pendingConfirmation) return undefined;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = confirmationRef.current;
    const focusable = dialog?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
    );
    focusable?.[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setPendingConfirmation(null);
        return;
      }
      if (event.key !== 'Tab' || !focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    };
  }, [pendingConfirmation]);

  const applyRunProfile = (profile: RunProfileId) => {
    if (controlsLocked) return;
    setRunProfile(profile);
    if (profile === 'full-validation') onSelectFullValidation();
    const settings = resolveRunProfile(profile, {
      launchMode,
      plannedMode,
      enableCoverageProbe,
      shadowValidation,
      evidenceLedger,
      identityShadowV2,
      traversalIdentityV2,
      traversalProfiler,
    });
    setLaunchMode(settings.launchMode);
    setPlannedMode(settings.plannedMode);
    setEnableCoverageProbe(settings.enableCoverageProbe);
    setShadowValidation(settings.shadowValidation);
    setEvidenceLedger(settings.evidenceLedger);
    setIdentityShadowV2(settings.identityShadowV2);
    setTraversalIdentityV2(settings.traversalIdentityV2);
    setTraversalProfiler(settings.traversalProfiler);
  };

  const executeRun = async () => {
    if (launchInFlightRef.current) return;
    setRunError(null);
    if (!runSafety.ready || profileBlockers.length > 0) return;

    const selected = selectedDeviceRecords;
    if (selected.length !== selectedDevices.size || selected.some((device) => !isReadyDevice(device))) {
      setRunError('Selected devices changed readiness. Refresh and select ready devices before running.');
      return;
    }
    const scenario_ids = Array.from(selectedScenarios);

    launchInFlightRef.current = true;
    setLaunchInFlight(true);
    let launchAccepted = false;
    try {
      const res = await api.startBatch({
        mode: plannedMode,
        devices: selected.map(d => ({ serial: d.serial, model: d.model })),
        launch_mode: launchMode,
        language_mode: languageMode,
        scenario_ids,
        enable_coverage_probe: enableCoverageProbe,
        shadow_validation: plannedMode === 'full' && shadowValidation,
        evidence_ledger: evidenceLedger,
        identity_shadow_v2: identityShadowV2,
        traversal_identity_v2: traversalIdentityV2,
        traversal_profiler: traversalProfiler,
      });
      launchAccepted = res.state === 'running';
    } catch (err) {
      setRunError(errorMessage(err, 'Failed to start batch'));
    } finally {
      if (!launchAccepted) {
        launchInFlightRef.current = false;
        setLaunchInFlight(false);
      }
    }
  };

  const handleRunClick = () => {
    if (!runSafety.ready || profileBlockers.length > 0) return;
    if (plannedMode === 'smoke') {
      setPendingConfirmation('smoke');
      return;
    }
    if (runSafety.runKind === 'custom') {
      setPendingConfirmation('custom');
      return;
    }
    void executeRun();
  };

  const confirmSmokeRun = () => {
    setPendingConfirmation(null);
    void executeRun();
  };

  const confirmCustomRun = () => {
    setPendingConfirmation(null);
    void executeRun();
  };

  return (
    <article className="panel controls">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h2>Run</h2>
        {status?.run_id && (
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--color-text-dim)' }}>
              (ID: {status.run_id} | Ret: {status.returncode ?? '-'})
            </span>
          </div>
        )}
      </div>

      <section className="runProfiles" aria-label="Run Profile">
        <div className="runProfilesHeader">
          <div>
            <h3>Run Profile</h3>
            <small>Choose a safe operating preset, or unlock individual controls for debugging.</small>
          </div>
          <span className="profileDefault">Full Validation is default</span>
        </div>
        <button
          type="button"
          className={fullProfileActive ? 'runProfileActive runProfilePrimary' : 'runProfilePrimary'}
          aria-pressed={fullProfileActive}
          onClick={() => applyRunProfile('full-validation')}
          disabled={controlsLocked}
        >
          Full Validation
          <small>Clean · {fullValidationScenarioIds.length} canonical Full scenarios · approval diagnostics on</small>
        </button>
        <details className="advancedRunOptions">
          <summary>Additional run profiles</summary>
          <div className="runProfileChoices">
          <button
            type="button"
            className={runProfile === 'quick-smoke' ? 'runProfileActive' : ''}
            aria-pressed={runProfile === 'quick-smoke'}
            onClick={() => applyRunProfile('quick-smoke')}
            disabled={controlsLocked}
          >
            Quick Smoke
            <small>Clean · Selected Smoke · fast verification</small>
          </button>
          <button
            type="button"
            className={runProfile === 'custom-debug' ? 'runProfileActive' : ''}
            aria-pressed={runProfile === 'custom-debug'}
            onClick={() => applyRunProfile('custom-debug')}
            disabled={controlsLocked}
          >
            Custom / Debug
            <small>Unlock all run options</small>
          </button>
          </div>
          <div className="developerRun">
            <strong>Developer compatibility path</strong>
            <p>Runs the existing single-device API explicitly. It is not the normal multi-device validator path.</p>
            <button type="button" onClick={() => start(plannedMode)} disabled={controlsLocked}>
              Run single-device compatibility path
            </button>
          </div>
        </details>
      </section>

      <div style={{ marginBottom: '20px' }}>
        <div className="deviceHeader">
          <h3 style={{ margin: 0, fontSize: '12px', color: 'var(--color-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Devices</h3>
          <div className="deviceActions">
          <button type="button" onClick={() => setSelectedDevices(readyDeviceSerials(devices))} disabled={loadingDevices || controlsLocked}>
            Select all ready
          </button>
          <button type="button" onClick={() => setSelectedDevices(new Set())} disabled={loadingDevices || controlsLocked}>
            Clear
          </button>
          <button type="button" onClick={fetchDevices} disabled={loadingDevices || controlsLocked}>
            {loadingDevices ? '...' : 'Refresh'}
          </button>
          </div>
        </div>
        <div className={`deviceSelectionGrid ${deviceCountClass}`}>
          {devices.length === 0 && !loadingDevices ? (
            <div style={{ fontSize: '13px', color: 'var(--color-text-dim)' }}>No devices connected.</div>
          ) : (
            devices.map(d => {
              let statusText = '';
              if (d.state !== 'device') statusText = d.state === 'offline' ? 'Offline' : 'Error';
              else if (d.helper_ready === null || d.talkback_enabled === null) statusText = 'Readiness unknown';
              else if (!d.helper_ready) statusText = 'Helper not ready';
              else if (!d.talkback_enabled) statusText = 'TalkBack not ready';
              else statusText = 'Ready';

              const isSelectable = isReadyDevice(d);

              return (
                <label key={d.serial} className={`deviceCard ${isSelectable ? 'deviceCardReady' : 'deviceCardUnavailable'}`}>
                  <input 
                    type="checkbox" 
                    checked={selectedDevices.has(d.serial)}
                    onChange={() => toggleDevice(d.serial)}
                    disabled={!isSelectable || controlsLocked}
                    style={{ marginTop: '3px' }}
                  />
                  <div className="deviceIdentity">
                    <strong>{d.model || 'Android device'}</strong>
                    <span>{shortDeviceId(d.serial)}</span>
                    <span className={statusText === 'Ready' ? 'deviceStatusReady' : 'deviceStatusUnavailable'}>{statusText}</span>
                    {d.foreground_package && (
                      <details className="deviceTechnicalDetails">
                        <summary>Technical details</summary>
                        <span>Serial: {d.serial}</span>
                        <span>Foreground: {d.foreground_package}</span>
                      </details>
                    )}
                  </div>
                </label>
              );
            })
          )}
        </div>
        {devices.length > 0 && (
          <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--color-text-dim)', textAlign: 'right' }}>
            Selected devices: {selectedDevices.size} / {devices.filter(isReadyDevice).length} ready
          </div>
        )}
        {batchStatus && batchStatus.state !== 'idle' && (
          <details className="advancedRunOptions batchStatusDetails">
            <summary>Batch device details</summary>
            <div style={{ marginTop: '12px', padding: '10px', background: 'var(--color-bg-dim)', borderRadius: '6px', fontSize: '12px' }}>
              <div style={{ fontWeight: 500, marginBottom: '6px' }}>
                Batch: {batchStatus.batch_id} - <span style={{ color: batchStatus.state === 'running' ? 'var(--color-primary)' : 'inherit' }}>{batchStatus.state}</span>
              </div>
              <div style={{ display: 'grid', gap: '4px' }}>
                {batchStatus.devices.map(d => (
                  <div key={d.serial} style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>{d.model} <span style={{color: 'var(--color-text-dim)', fontSize: '10px'}}>({d.serial})</span></span>
                    <span style={{ color: d.state === 'running' ? 'var(--color-primary)' : d.state === 'passed' ? 'var(--color-success)' : d.state === 'failed' ? 'var(--color-danger)' : 'var(--color-text-dim)' }}>{d.state}</span>
                  </div>
                ))}
              </div>
            </div>
          </details>
        )}
      </div>

      <details className="advancedRunOptions">
        <summary>Advanced run options</summary>
      <div className="runGrid">
        <div>
          <h3 style={{ margin: '0 0 6px', fontSize: '12px', color: 'var(--color-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Launch</h3>
          <div className="launchMode" style={{ marginBottom: '0' }}>
            <label style={{ padding: '4px 8px' }}>
              <input
                type="radio"
                name="launch_mode"
                checked={launchMode === 'clean'}
                onChange={() => setLaunchMode('clean')}
                disabled={!customOptionsEnabled}
              />
              <span style={{ fontSize: '14px' }}>Clean</span>
            </label>
            <label style={{ padding: '4px 8px' }}>
              <input
                type="radio"
                name="launch_mode"
                checked={launchMode === 'warm'}
                onChange={() => setLaunchMode('warm')}
                disabled={!customOptionsEnabled}
              />
              <span style={{ fontSize: '14px' }}>Warm</span>
            </label>
          </div>
        </div>

        <div>
          <h3 style={{ margin: '0 0 6px', fontSize: '12px', color: 'var(--color-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Language</h3>
          <div className="languageMode" style={{ marginBottom: '0', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <label style={{ padding: '4px 8px', gridTemplateColumns: 'auto auto', gap: '4px' }}>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'current'}
                onChange={() => setLanguageMode('current')}
                disabled={controlsLocked}
              />
              <span style={{ fontSize: '14px' }}>{currentLanguageLabel(effectiveLocale)}</span>
            </label>
            <label style={{ padding: '4px 8px', gridTemplateColumns: 'auto auto', gap: '4px' }}>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'ko-KR'}
                onChange={() => setLanguageMode('ko-KR')}
                disabled={controlsLocked}
              />
              <span style={{ fontSize: '14px' }}>Korean</span>
            </label>
            <label style={{ padding: '4px 8px', gridTemplateColumns: 'auto auto', gap: '4px' }}>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'en-US'}
                onChange={() => setLanguageMode('en-US')}
                disabled={controlsLocked}
              />
              <span style={{ fontSize: '14px' }}>English</span>
            </label>
          </div>
        </div>

        <div>
          <h3 style={{ margin: '0 0 6px', fontSize: '12px', color: 'var(--color-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Mode</h3>
          <div className="launchMode" style={{ marginBottom: '0' }}>
            <label style={{ padding: '4px 8px' }}>
              <input
                type="radio"
                name="planned_mode"
                checked={plannedMode === 'smoke'}
                onChange={() => setPlannedMode('smoke')}
                disabled={!customOptionsEnabled}
              />
              <span style={{ fontSize: '14px' }}>Selected Smoke</span>
              <small style={{ fontSize: '11px', margin: 0 }}>selected scenarios with reduced max_steps</small>
            </label>
            <label style={{ padding: '4px 8px' }}>
              <input
                type="radio"
                name="planned_mode"
                checked={plannedMode === 'full'}
                onChange={() => setPlannedMode('full')}
                disabled={!customOptionsEnabled}
              />
              <span style={{ fontSize: '14px' }}>Selected Full</span>
              <small style={{ fontSize: '11px', margin: 0 }}>selected scenarios with source max_steps</small>
            </label>
          </div>
        </div>

        <div>
          <h3 style={{ margin: '0 0 6px', fontSize: '12px', color: 'var(--color-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Execution Options</h3>
          <div className="launchMode" style={{ marginBottom: '0' }}>
            <label title="Collect additional coverage diagnostics after traversal." style={{ padding: '4px 8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="checkbox"
                checked={enableCoverageProbe}
                onChange={(e) => setEnableCoverageProbe(e.target.checked)}
                disabled={!customOptionsEnabled}
              />
              <span style={{ fontSize: '14px' }}>Runtime Coverage Probe</span>
            </label>
            <div style={{ padding: '0 8px', marginTop: '-4px' }}>
              <small style={{ fontSize: '11px', color: 'var(--color-text-dim)', display: 'block' }}>
                Runs coverage-driven TalkBack probe after traversal to validate expected device/plugin content. Recommended for Full runs.
              </small>
            </div>
            <label title="Uses the production traversal engine. Turn off to run the legacy compatibility traversal." style={{ padding: '4px 8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input type="checkbox" checked={traversalIdentityV2} onChange={e => { setTraversalIdentityV2(e.target.checked); if (e.target.checked) { setIdentityShadowV2(true); setEvidenceLedger(true); } }} disabled={!customOptionsEnabled} />
              <span style={{ fontSize: '14px' }}>Traversal Engine</span>
            </label>
            <div style={{ padding: '0 8px', marginTop: '-4px' }}><small style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>V2 is the production default. Turn it off to run Legacy Compatibility traversal.</small></div>
            <details style={{ padding: '4px 8px' }}>
              <summary style={{ cursor: 'pointer', fontSize: '13px', color: 'var(--color-text-dim)' }}>Advanced Diagnostics</summary>
              <div style={{ paddingTop: '6px' }}>
                <label title="Collect detailed traversal evidence." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={evidenceLedger} onChange={e => { setEvidenceLedger(e.target.checked); if (!e.target.checked) { setIdentityShadowV2(false); setTraversalIdentityV2(false); } }} disabled={!customOptionsEnabled} />
                  <span style={{ fontSize: '14px' }}>Evidence Ledger</span>
                </label>
                <label title="Collect runtime metrics and generate profiler artifacts. Does not change traversal behavior." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={traversalProfiler} onChange={e => setTraversalProfiler(e.target.checked)} disabled={!customOptionsEnabled} />
                  <span style={{ fontSize: '14px' }}>Runtime Profiler</span>
                </label>
                <div style={{ padding: '0', marginTop: '-4px' }}><small style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>Collect runtime metrics and generate profiler artifacts. Does not change traversal behavior.</small></div>
                <label title="Compare legacy and V2 identity results without changing traversal." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={identityShadowV2} onChange={e => { setIdentityShadowV2(e.target.checked); if (e.target.checked) setEvidenceLedger(true); else setTraversalIdentityV2(false); }} disabled={!customOptionsEnabled} />
                  <span style={{ fontSize: '14px' }}>Identity Shadow V2 (Read-only)</span>
                </label>
                <div style={{ padding: '0', marginTop: '-4px' }}><small style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>Read-only comparison. Requires Evidence Ledger and enables it automatically.</small></div>
                {showLegacyShadowValidation && (
                <div className="legacyShadowControl">
                <label title="Run the legacy validation pipeline after the run; legacy results remain authoritative." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input
                    type="checkbox"
                    checked={shadowValidation}
                    onChange={(e) => setShadowValidation(e.target.checked)}
                    disabled={!customOptionsEnabled || plannedMode !== 'full'}
                  />
                  <span style={{ fontSize: '14px' }}>Legacy Shadow Validation (Experimental)</span>
                </label>
                <div style={{ padding: '0', marginTop: '-4px' }}>
                  <small style={{ fontSize: '11px', color: 'var(--color-text-dim)', display: 'block' }}>
                    Legacy validation is retained for comparison and is planned for removal. Legacy remains authoritative.
                  </small>
                </div>
                </div>
                )}
              </div>
            </details>
          </div>
        </div>
      </div>

      </details>

      <div className="runFooter">
        <div>
          <div style={{ fontSize: '13px', color: 'var(--color-text-dim)' }}>
            <strong>Current:</strong> {runLabel} &middot; {String(status?.launch_mode ?? launchMode).replace(/^\w/, c => c.toUpperCase())} &middot; {languageMode === 'current' ? currentLanguageLabel(effectiveLocale) : String(status?.language_mode ?? languageMode).replace(/^\w/, c => c.toUpperCase())} &middot; Selected {selectedCount} / {fullValidationScenarioIds.length}
          </div>
          <div className={`validationReadiness ${runBlockers.length === 0 ? 'validationReady' : 'validationNotReady'}`} aria-live="polite">
            <strong>{runBlockers.length === 0 ? 'READY' : 'NOT READY'}</strong>
            <span>
              {runBlockers.length > 0
                ? runBlockers.join(' · ')
                : plannedMode === 'smoke'
                  ? 'Quick Smoke is ready for a fast check; it is not Full Validation.'
                : runSafety.runKind === 'custom'
                  ? 'Custom Run scope selected. Confirmation is required before start.'
                  : 'Full Validation inputs are enabled.'}
            </span>
          </div>
          {runError && <div className="notice" role="alert">{runError}</div>}
        </div>
        <div className="buttonRow" style={{ marginBottom: '0', justifyContent: 'flex-end', gap: '12px' }}>
          <button type="button" onClick={handleRunClick} disabled={runDisabled} style={{ minWidth: '130px' }}>
            {runLabel}
          </button>
          <button type="button" className="danger" onClick={stop} disabled={!controlsLocked} style={{ minWidth: '100px' }}>
            Stop
          </button>
        </div>
      </div>

      {pendingConfirmation && (
        <div className="confirmationBackdrop" role="presentation" onClick={() => setPendingConfirmation(null)}>
          <div
            className="confirmationDialog"
            ref={confirmationRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="run-confirmation-title"
            onClick={event => event.stopPropagation()}
          >
            <h2 id="run-confirmation-title">{pendingConfirmation === 'custom' ? 'Custom Run' : 'Quick Smoke'}</h2>
            {pendingConfirmation === 'custom' ? (
              <>
                <p>{selectedCount} / {fullValidationScenarioIds.length} scenarios are selected.</p>
                <p>This is an explicit Custom Run and is not the complete Full Validation scope.</p>
              </>
            ) : (
              <>
                <p>
                  Smoke Run은 빠른 확인을 위한 실행이며<br />
                  정식 검증 결과로 사용되지 않습니다.
                </p>
                <p>계속 실행하시겠습니까?</p>
              </>
            )}
            <div className="buttonRow">
              <button type="button" onClick={() => setPendingConfirmation(null)}>Cancel</button>
              <button
                type="button"
                className="primary"
                onClick={pendingConfirmation === 'custom' ? confirmCustomRun : confirmSmokeRun}
              >
                {pendingConfirmation === 'custom' ? 'Start Custom Run' : 'Run Smoke'}
              </button>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}
