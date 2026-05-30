import React from 'react';
import { RunStatus } from '../api';
import { languageLabel } from '../utils/formatters';

type LanguageMode = 'current' | 'ko-KR' | 'en-US';

export interface RunPanelProps {
  launchMode: 'warm' | 'clean';
  setLaunchMode: (mode: 'warm' | 'clean') => void;
  languageMode: LanguageMode;
  setLanguageMode: (mode: LanguageMode) => void;
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
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ fontSize: '12px', color: 'var(--color-text-dim)' }}>
            <strong>Current:</strong> {effectiveMode === 'smoke' ? 'Smoke' : 'Full'} · {status?.launch_mode ?? launchMode} · {status?.language_mode ?? languageMode} · sel: {selectedCount}
          </span>
          {status?.run_id && (
            <span style={{ fontSize: '12px', color: 'var(--color-text-dim)' }}>
              (ID: {status.run_id} | Ret: {status.returncode ?? '-'})
            </span>
          )}
        </div>
      </div>

      <div className="runGrid">
        <div>
          <div className="launchMode" style={{ marginBottom: '0' }}>
            <label style={{ padding: '4px 8px' }}>
              <input
                type="radio"
                name="launch_mode"
                checked={launchMode === 'clean'}
                onChange={() => setLaunchMode('clean')}
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Clean launch</span>
            </label>
            <label style={{ padding: '4px 8px' }}>
              <input
                type="radio"
                name="launch_mode"
                checked={launchMode === 'warm'}
                onChange={() => setLaunchMode('warm')}
                disabled={running}
              />
              <span style={{ fontSize: '14px' }}>Warm launch</span>
            </label>
          </div>
        </div>

        <div>
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
      </div>

      <div className="buttonRow" style={{ marginTop: '12px', marginBottom: '0', justifyContent: 'flex-start' }}>
        <button onClick={() => start('smoke')} disabled={running} style={{ minWidth: '100px' }}>
          Smoke
          <small style={{ marginTop: '0', fontSize: '10px' }}>quick check</small>
        </button>
        <button onClick={() => start('full')} disabled={running} style={{ minWidth: '100px' }}>
          Full
          <small style={{ marginTop: '0', fontSize: '10px' }}>regression</small>
        </button>
        <button className="danger" onClick={stop} disabled={!running} style={{ minWidth: '100px', alignSelf: 'center' }}>
          Stop
        </button>
      </div>
    </article>
  );
}
