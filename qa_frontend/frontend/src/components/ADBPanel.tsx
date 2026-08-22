import React from 'react';

export interface ADBPanelProps {
  adb: Record<string, unknown> | null;
}

function adbStatusLabel(adb: Record<string, unknown> | null): string {
  if (!adb) return 'Disconnected';
  const status = adb.status;
  return typeof status === 'string' && status.trim() ? status : 'Connected';
}

function adbDeviceCount(adb: Record<string, unknown> | null): number {
  return adb && Array.isArray(adb.devices) ? adb.devices.length : 0;
}

export function ADBPanel({ adb }: ADBPanelProps) {
  const statusLabel = adbStatusLabel(adb);
  const deviceCount = adbDeviceCount(adb);

  return (
    <article className="panel readinessPanel">
      <div className="panelHeader">
        <h2>ADB connection</h2>
        <span className={`statusBadge ${adb ? 'healthOk' : 'healthBad'}`} aria-label={`ADB status: ${statusLabel}`}>
          {statusLabel}
        </span>
      </div>
      <div className="readinessSummary">
        <strong>{deviceCount} device{deviceCount === 1 ? '' : 's'} detected</strong>
        <span>Validator device readiness is checked below before a run can start.</span>
      </div>
      <details className="technicalDetails">
        <summary>Technical details</summary>
        <pre>{JSON.stringify(adb?.devices ?? [], null, 2)}</pre>
      </details>
    </article>
  );
}
