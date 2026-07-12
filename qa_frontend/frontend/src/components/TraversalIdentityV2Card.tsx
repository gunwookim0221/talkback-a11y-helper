import React, { useEffect, useState } from 'react';
import { api, IdentityFeatureFlags, TraversalIdentityV2Diagnostics } from '../api';

const METRICS: Array<[keyof TraversalIdentityV2Diagnostics, string]> = [
  ['false_progress_suppressed', 'False progress suppressed'],
  ['representative_only_progress_ignored', 'Representative-only ignored'],
  ['recovered_candidate_attempts', 'Recovered candidate attempts'],
  ['recovered_visits', 'Recovered visits'],
  ['premature_stop_prevented', 'Premature stop prevented'],
  ['fallback_to_legacy_count', 'Fallback to legacy'],
  ['indeterminate_count', 'Indeterminate'],
];

export function TraversalIdentityV2Card({
  runId,
  deviceId,
  featureFlags,
  initialDiagnostics,
}: {
  runId: string;
  deviceId: string;
  featureFlags?: IdentityFeatureFlags | null;
  initialDiagnostics?: TraversalIdentityV2Diagnostics | null;
}) {
  const [diagnostics, setDiagnostics] = useState<TraversalIdentityV2Diagnostics | null>(initialDiagnostics || null);

  useEffect(() => {
    let active = true;
    setDiagnostics(initialDiagnostics || null);
    api.getIdentityShadow(runId, deviceId)
      .then(report => {
        if (active && report.traversal_identity_v2_diagnostics) {
          setDiagnostics(report.traversal_identity_v2_diagnostics);
        }
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [runId, deviceId]);

  const metadataAvailable = featureFlags != null;
  const enabled = featureFlags?.traversal_identity_v2 === true;
  const diagnosticsAvailable = diagnostics?.available === true;

  return <details open style={{ marginTop: '16px' }}>
    <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>
      Traversal Identity V2
      <span className="statusBadge" style={{ marginLeft: '8px', fontSize: '10px' }}>Experimental · read-only diagnostics</span>
    </summary>
    <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
      {!metadataAvailable ? (
        <div className="scenarioDetailRow"><strong>Unavailable</strong><small>This run predates Traversal Identity V2 feature metadata.</small></div>
      ) : !enabled ? (
        <div className="scenarioDetailRow"><strong>Disabled</strong><small>Traversal Identity V2 was not enabled for this run.</small></div>
      ) : !diagnosticsAvailable ? (
        <div className="scenarioDetailRow"><strong>Diagnostics unavailable</strong><small>{diagnostics?.reason || 'No cumulative diagnostics event was recorded.'}</small></div>
      ) : (
        <>
          <small>Post-run diagnostic projection only. Existing production result cards remain authoritative.</small>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '8px' }}>
            {METRICS.map(([key, label]) => (
              <div className="scenarioDetailRow" key={String(key)}>
                <small>{label}</small>
                <strong>{Number(diagnostics?.[key] ?? 0)}</strong>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  </details>;
}
