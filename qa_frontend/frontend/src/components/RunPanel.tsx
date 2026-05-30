import React from 'react';
import { RunStatus } from '../api';
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
}: RunPanelProps) {
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
          <div className="runMode" style={{ marginBottom: '0', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <label style={{ padding: '4px 8px', gridTemplateColumns: 'auto auto', gap: '4px' }}>
              <input
                type="radio"
                name="planned_mode"
                checked={plannedMode === 'smoke'}
                onChange={() => setPlannedMode('smoke')}
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Smoke</span>
            </label>
            <label style={{ padding: '4px 8px', gridTemplateColumns: 'auto auto', gap: '4px' }}>
              <input
                type="radio"
                name="planned_mode"
                checked={plannedMode === 'full'}
                onChange={() => setPlannedMode('full')}
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Full</span>
            </label>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '20px' }}>
        <div style={{ fontSize: '13px', color: 'var(--color-text-dim)' }}>
          <strong>Current:</strong> {effectiveMode === 'smoke' ? 'Smoke' : 'Full'} &middot; {String(status?.launch_mode ?? launchMode).replace(/^\w/, c => c.toUpperCase())} &middot; {String(status?.language_mode ?? languageMode).replace(/^\w/, c => c.toUpperCase())} &middot; Selected {selectedCount}
        </div>
        <div className="buttonRow" style={{ marginBottom: '0', justifyContent: 'flex-end', gap: '12px' }}>
          <button onClick={() => start(plannedMode)} disabled={running} style={{ minWidth: '100px' }}>
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
