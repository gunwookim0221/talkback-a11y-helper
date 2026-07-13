import React, { useState, useEffect } from 'react';
import { RunStatus, api, DeviceInfo, BatchStatus } from '../api';
import { languageLabel } from '../utils/formatters';

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
  stepPolicyText: string;
  selectedCount: number;
  selectedScenarios: Set<string>;
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
  stepPolicyText,
  selectedCount,
  selectedScenarios,
  enableCoverageProbe,
  setEnableCoverageProbe,
  shadowValidation,
  setShadowValidation,
  evidenceLedger, setEvidenceLedger, identityShadowV2, setIdentityShadowV2,
  traversalIdentityV2, setTraversalIdentityV2,
  traversalProfiler, setTraversalProfiler,
}: RunPanelProps) {
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [selectedDevices, setSelectedDevices] = useState<Set<string>>(new Set());

  const fetchDevices = async () => {
    setLoadingDevices(true);
    try {
      const list = await api.devices();
      setDevices(list);
      // Auto-select ready devices
      setSelectedDevices(new Set(list.filter(d => d.state === 'device').map(d => d.serial)));
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
        setSelectedDevices(new Set(fallback.filter(d => d.state === 'device').map(d => d.serial)));
      } catch (fallbackErr) {
        console.error('Failed to fetch fallback ADB devices', fallbackErr);
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

  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);

  useEffect(() => {
    let timer: number;
    const pollBatch = async () => {
      try {
        const res = await api.getBatchStatus();
        setBatchStatus(res);
        if (res.state === 'running') {
          timer = window.setTimeout(pollBatch, 2000);
        } else {
          timer = window.setTimeout(pollBatch, 5000);
        }
      } catch (err) {
        timer = window.setTimeout(pollBatch, 5000);
      }
    };
    pollBatch();
    return () => window.clearTimeout(timer);
  }, []);

  const handleRunClick = async () => {
    if (selectedDevices.size > 0) {
      const selected = devices.filter(d => selectedDevices.has(d.serial) && d.state === 'device');
      if (selected.length === 0) {
         alert('No valid devices selected.');
         return;
      }
      try {
        const scenario_ids = selectedScenarios ? Array.from(selectedScenarios) : [];
        if (scenario_ids.length === 0) {
          alert('Please select at least one scenario before running.');
          return;
        }

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
        setBatchStatus(res);
      } catch (err: any) {
        alert(err.message || 'Failed to start batch');
      }
    } else {
      start(plannedMode);
    }
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

      <div style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <h3 style={{ margin: 0, fontSize: '12px', color: 'var(--color-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Devices</h3>
          <button onClick={fetchDevices} disabled={loadingDevices || running} style={{ fontSize: '11px', padding: '2px 8px', minWidth: 'auto' }}>
            {loadingDevices ? '...' : 'Refresh'}
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {devices.length === 0 && !loadingDevices ? (
            <div style={{ fontSize: '13px', color: 'var(--color-text-dim)' }}>No devices connected.</div>
          ) : (
            devices.map(d => {
              let statusText = '';
              if (d.state !== 'device') statusText = d.state === 'offline' ? 'Offline' : 'Error';
              else if (d.helper_ready === null || d.talkback_enabled === null) statusText = 'Connected';
              else if (!d.helper_ready) statusText = 'Helper missing';
              else if (!d.talkback_enabled) statusText = 'TalkBack disabled';
              else statusText = 'Ready';

              const isSelectable = d.state === 'device';

              return (
                <label key={d.serial} style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', padding: '8px 12px', background: 'var(--color-bg-dim)', borderRadius: '6px', opacity: isSelectable ? 1 : 0.6, cursor: isSelectable && !running ? 'pointer' : 'not-allowed', border: '1px solid var(--color-border)' }}>
                  <input 
                    type="checkbox" 
                    checked={selectedDevices.has(d.serial)} 
                    onChange={() => toggleDevice(d.serial)}
                    disabled={!isSelectable || running}
                    style={{ marginTop: '3px' }}
                  />
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <div style={{ fontWeight: 500, fontSize: '14px' }}>
                      {d.model} <span style={{ color: 'var(--color-text-dim)', fontSize: '12px', fontWeight: 'normal' }}>({d.serial})</span>
                    </div>
                    <div style={{ fontSize: '12px', color: statusText === 'Ready' ? 'var(--color-success)' : 'var(--color-danger)', marginTop: '2px' }}>
                      {statusText}
                    </div>
                    {d.foreground_package && (
                      <div style={{ fontSize: '11px', color: 'var(--color-text-dim)', marginTop: '2px', wordBreak: 'break-all' }}>
                        pkg: {d.foreground_package}
                      </div>
                    )}
                  </div>
                </label>
              );
            })
          )}
        </div>
        {devices.length > 0 && (
          <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--color-text-dim)', textAlign: 'right' }}>
            Selected devices: {selectedDevices.size}
          </div>
        )}
        {batchStatus && batchStatus.state !== 'idle' && (
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
        )}
      </div>

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
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Clean</span>
            </label>
            <label style={{ padding: '4px 8px' }}>
              <input
                type="radio"
                name="launch_mode"
                checked={launchMode === 'warm'}
                onChange={() => setLaunchMode('warm')}
                disabled={running}
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
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Current</span>
            </label>
            <label style={{ padding: '4px 8px', gridTemplateColumns: 'auto auto', gap: '4px' }}>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'ko-KR'}
                onChange={() => setLanguageMode('ko-KR')}
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Korean</span>
            </label>
            <label style={{ padding: '4px 8px', gridTemplateColumns: 'auto auto', gap: '4px' }}>
              <input
                type="radio"
                name="language_mode"
                checked={languageMode === 'en-US'}
                onChange={() => setLanguageMode('en-US')}
                disabled={running}
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
                disabled={running}
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
                disabled={running}
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
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Runtime Coverage Probe</span>
            </label>
            <div style={{ padding: '0 8px', marginTop: '-4px' }}>
              <small style={{ fontSize: '11px', color: 'var(--color-text-dim)', display: 'block' }}>
                Runs coverage-driven TalkBack probe after traversal to validate expected device/plugin content. Recommended for Full runs.
              </small>
            </div>
            <label title="Uses the production traversal engine. Turn off to run the legacy compatibility traversal." style={{ padding: '4px 8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input type="checkbox" checked={traversalIdentityV2} onChange={e => { setTraversalIdentityV2(e.target.checked); if (e.target.checked) { setIdentityShadowV2(true); setEvidenceLedger(true); } }} disabled={running} />
              <span style={{ fontSize: '14px' }}>Traversal Engine</span>
            </label>
            <div style={{ padding: '0 8px', marginTop: '-4px' }}><small style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>V2 is the production default. Turn it off to run Legacy Compatibility traversal.</small></div>
            <details style={{ padding: '4px 8px' }}>
              <summary style={{ cursor: 'pointer', fontSize: '13px', color: 'var(--color-text-dim)' }}>Advanced Diagnostics</summary>
              <div style={{ paddingTop: '6px' }}>
                <label title="Collect detailed traversal evidence." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={evidenceLedger} onChange={e => { setEvidenceLedger(e.target.checked); if (!e.target.checked) { setIdentityShadowV2(false); setTraversalIdentityV2(false); } }} disabled={running} />
                  <span style={{ fontSize: '14px' }}>Evidence Ledger</span>
                </label>
                <label title="Collect runtime metrics and generate profiler artifacts. Does not change traversal behavior." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={traversalProfiler} onChange={e => setTraversalProfiler(e.target.checked)} disabled={running} />
                  <span style={{ fontSize: '14px' }}>Runtime Profiler</span>
                </label>
                <div style={{ padding: '0', marginTop: '-4px' }}><small style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>Collect runtime metrics and generate profiler artifacts. Does not change traversal behavior.</small></div>
                <label title="Compare legacy and V2 identity results without changing traversal." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={identityShadowV2} onChange={e => { setIdentityShadowV2(e.target.checked); if (e.target.checked) setEvidenceLedger(true); else setTraversalIdentityV2(false); }} disabled={running} />
                  <span style={{ fontSize: '14px' }}>Identity Shadow V2 (Read-only)</span>
                </label>
                <div style={{ padding: '0', marginTop: '-4px' }}><small style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>Read-only comparison. Requires Evidence Ledger and enables it automatically.</small></div>
                <label title="Run the legacy validation pipeline after the run; legacy results remain authoritative." style={{ padding: '4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input
                    type="checkbox"
                    checked={shadowValidation}
                    onChange={(e) => setShadowValidation(e.target.checked)}
                    disabled={running || plannedMode !== 'full'}
                  />
                  <span style={{ fontSize: '14px' }}>Legacy Shadow Validation (Experimental)</span>
                </label>
                <div style={{ padding: '0', marginTop: '-4px' }}>
                  <small style={{ fontSize: '11px', color: 'var(--color-text-dim)', display: 'block' }}>
                    Legacy validation is retained for comparison and is planned for removal. Legacy remains authoritative.
                  </small>
                </div>
              </div>
            </details>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '20px' }}>
        <div style={{ fontSize: '13px', color: 'var(--color-text-dim)' }}>
          <strong>Current:</strong> {effectiveMode === 'smoke' ? 'Selected Smoke' : 'Selected Full'} &middot; {String(status?.launch_mode ?? launchMode).replace(/^\w/, c => c.toUpperCase())} &middot; {String(status?.language_mode ?? languageMode).replace(/^\w/, c => c.toUpperCase())} &middot; Selected {selectedCount}
        </div>
        <div className="buttonRow" style={{ marginBottom: '0', justifyContent: 'flex-end', gap: '12px' }}>
          <button onClick={handleRunClick} disabled={running || batchStatus?.state === 'running'} style={{ minWidth: '100px' }}>
            Run
          </button>
          <button className="danger" onClick={stop} disabled={!running} style={{ minWidth: '100px' }}>
            Stop
          </button>
        </div>
      </div>
    </article>
  );
}
