import React, { useEffect, useMemo, useState } from 'react';
import { api, IdentityShadowReport } from '../api';

export function IdentityShadowCard({ runId, deviceId }: { runId: string; deviceId: string }) {
  const [report, setReport] = useState<IdentityShadowReport | null>(null);
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [onlyStatic, setOnlyStatic] = useState(false);
  const [onlyIncomplete, setOnlyIncomplete] = useState(false);
  useEffect(() => { let active = true; api.getIdentityShadow(runId, deviceId).then(r => active && setReport(r)).catch(() => active && setReport(null)); return () => { active = false; }; }, [runId, deviceId]);
  const rows = useMemo(() => (report?.transactions || []).filter(row => (!onlyChanged || row.verdict_changed) && (!onlyStatic || row.v2_verdict === 'STATIC_FOCUS') && (!onlyIncomplete || !row.evidence_complete)), [report, onlyChanged, onlyStatic, onlyIncomplete]);
  return <details open style={{ marginTop: '16px' }}>
    <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>Identity Shadow V2 <span className="statusBadge" style={{ marginLeft: '8px', fontSize: '10px' }}>Experimental · read-only</span></summary>
    {!report ? <small>Identity shadow evidence was not loaded.</small> : !report.available ? <small>Not available: {report.availability}</small> : <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
      <small>Canonical Identity Shadow only. It does not change traversal, audit, coverage, or production results. State: {report.availability}.</small>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: '8px' }}>
        {[['Transactions', report.summary.transactions], ['Changed', report.summary.changed], ['Incomplete', report.summary.incomplete], ['Strong physical', report.summary.strong_physical], ['Insufficient', report.summary.insufficient]].map(([label, value]) => <div className="scenarioDetailRow" key={String(label)}><small>{label}</small><strong>{value}</strong></div>)}
      </div>
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        <label><input aria-label="Show disagreements only" type="checkbox" checked={onlyChanged} onChange={e => setOnlyChanged(e.target.checked)} /> Differences only</label>
        <label><input aria-label="Show static focus only" type="checkbox" checked={onlyStatic} onChange={e => setOnlyStatic(e.target.checked)} /> Static only</label>
        <label><input aria-label="Show incomplete evidence only" type="checkbox" checked={onlyIncomplete} onChange={e => setOnlyIncomplete(e.target.checked)} /> Incomplete only</label>
      </div>
      <div style={{ overflowX: 'auto' }}><table aria-label="Canonical Identity Shadow transactions"><thead><tr><th>Step</th><th>Action</th><th>Legacy</th><th>V2</th><th>Target relation</th><th>Stability</th><th>Confidence</th></tr></thead><tbody>{rows.map(row => <tr key={row.transaction_id}><td>{row.step_index ?? '-'}</td><td>{row.action_type ?? '-'}</td><td>{row.legacy_verdict ?? '-'}</td><td>{row.v2_verdict ?? '-'}</td><td>{row.target_relation ?? '-'}</td><td>{row.temporal_relation ?? '-'}</td><td>{row.confidence ?? '-'}</td></tr>)}</tbody></table></div>
    </div>}
  </details>;
}
