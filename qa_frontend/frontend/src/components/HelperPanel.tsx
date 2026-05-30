import React from 'react';
import { HelperStatus } from '../api';

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

export interface HelperPanelProps {
  helper: HelperStatus | null;
  running: boolean;
  installHelper: () => void;
  enableHelper: () => void;
  openAccessibilitySettings: () => void;
}

export function HelperPanel({
  helper,
  running,
  installHelper,
  enableHelper,
  openAccessibilitySettings,
}: HelperPanelProps) {
  return (
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
  );
}
