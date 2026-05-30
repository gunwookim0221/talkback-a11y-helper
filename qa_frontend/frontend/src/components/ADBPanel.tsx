import React from 'react';

export interface ADBPanelProps {
  adb: Record<string, unknown> | null;
}

export function ADBPanel({ adb }: ADBPanelProps) {
  return (
    <article className="panel">
      <h2>ADB</h2>
      <div className="metric">{String(adb?.status ?? 'unknown')}</div>
      <pre>{JSON.stringify(adb?.devices ?? [], null, 2)}</pre>
    </article>
  );
}
