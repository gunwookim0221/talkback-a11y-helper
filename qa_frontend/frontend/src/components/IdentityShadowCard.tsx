import React, { useEffect, useMemo, useState } from 'react';
import { api, IdentityShadowReport } from '../api';

const VERDICT_ORDER = ['MOVE_CONFIRMED', 'STATIC_FOCUS', 'MOVE_TO_OTHER_NODE', 'SNAP_BACK', 'INDETERMINATE'] as const;

function DistributionSummary({
  title,
  counts,
  percentages,
  order,
}: {
  title: string;
  counts?: Record<string, number>;
  percentages?: Record<string, number>;
  order?: readonly string[];
}) {
  const values = counts || {};
  const keys = order ? [...order] : Object.keys(values).sort();
  const total = keys.reduce((sum, key) => sum + (values[key] || 0), 0);
  return <div className="scenarioDetailList" style={{ marginTop: '8px' }}>
    <strong style={{ fontSize: '12px' }}>{title}</strong>
    {keys.length === 0 ? <small>Unavailable</small> : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: '6px' }}>
      {keys.map(key => {
        const count = values[key] || 0;
        const percentage = percentages?.[key] ?? (total > 0 ? Math.round(count * 1000 / total) / 10 : 0);
        return <div className="scenarioDetailRow" key={key}><small>{key}</small><strong>{count} · {percentage.toFixed(1)}%</strong></div>;
      })}
    </div>}
  </div>;
}

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
      <DistributionSummary title="Verdict distribution" counts={report.summary.v2_verdicts} percentages={report.summary.v2_verdict_percentages} order={VERDICT_ORDER} />
      <DistributionSummary title="Confidence summary" counts={report.summary.confidence_counts} percentages={report.summary.confidence_percentages} />
      <DistributionSummary title="Relation summary" counts={report.summary.relation_counts || report.summary.target_relations} percentages={report.summary.relation_percentages} />
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        <label><input aria-label="Show disagreements only" type="checkbox" checked={onlyChanged} onChange={e => setOnlyChanged(e.target.checked)} /> Differences only</label>
        <label><input aria-label="Show static focus only" type="checkbox" checked={onlyStatic} onChange={e => setOnlyStatic(e.target.checked)} /> Static only</label>
        <label><input aria-label="Show incomplete evidence only" type="checkbox" checked={onlyIncomplete} onChange={e => setOnlyIncomplete(e.target.checked)} /> Incomplete only</label>
      </div>
      <div style={{ overflowX: 'auto' }}><table aria-label="Canonical Identity Shadow transactions"><thead><tr><th>Step</th><th>Action</th><th>Legacy</th><th>V2</th><th>Target relation</th><th>Stability</th><th>Confidence</th></tr></thead><tbody>{rows.map(row => <tr key={row.transaction_id}><td>{row.step_index ?? '-'}</td><td>{row.action_type ?? '-'}</td><td>{row.legacy_verdict ?? '-'}</td><td>{row.v2_verdict ?? '-'}</td><td>{row.target_relation ?? '-'}</td><td>{row.temporal_relation ?? '-'}</td><td>{row.confidence ?? '-'}</td></tr>)}</tbody></table></div>
    </div>}
  </details>;
}
