import React from 'react';
import { RunStatus } from '../api';

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
  );
}
