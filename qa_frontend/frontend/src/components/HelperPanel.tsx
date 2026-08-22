import React from 'react';
import { helperBadgeText } from '../utils/formatters';
import type { HelperStatus } from '../api';

export interface HelperPanelProps {
  helper: HelperStatus | null;
  talkbackState?: string | null;
  running: boolean;
  installHelper: () => void;
  enableHelper: () => void;
  openAccessibilitySettings: () => void;
}

export function HelperPanel({
  helper,
  talkbackState,
  running,
  installHelper,
  enableHelper,
  openAccessibilitySettings,
}: HelperPanelProps) {
  const helperReady = helper?.status === 'ok';
  const talkbackReady = talkbackState === 'enabled';
  const talkbackLabel = talkbackReady ? 'Enabled' : talkbackState === 'disabled' ? 'Disabled' : 'Unknown';
  const overallReady = helperReady && talkbackReady;
  const overallLabel = helper === null || talkbackState === null || talkbackState === undefined
    ? 'Unknown'
    : overallReady
      ? 'Ready'
      : 'Not ready';
  const talkbackStatusClass = talkbackReady ? 'healthOk' : talkbackState === 'disabled' ? 'healthBad' : 'healthNeutral';
  const overallStatusClass = overallLabel === 'Ready' ? 'healthOk' : overallLabel === 'Unknown' ? 'healthNeutral' : 'healthBad';

  return (
    <article className="panel readinessPanel">
      <div className="panelHeader">
        <h2>Helper and TalkBack</h2>
        <span className={`statusBadge ${overallStatusClass}`}>
          {overallLabel}
        </span>
      </div>
      <div className="readinessRows">
        <div>
          <span>Helper</span>
          <strong>{helper ? helperBadgeText(helper.status) : 'Unknown'}</strong>
        </div>
        <div>
          <span>TalkBack</span>
          <strong className={talkbackStatusClass}>{talkbackLabel}</strong>
        </div>
      </div>
      <details className="technicalDetails">
        <summary>Technical helper details</summary>
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
      </details>
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
  );
}
