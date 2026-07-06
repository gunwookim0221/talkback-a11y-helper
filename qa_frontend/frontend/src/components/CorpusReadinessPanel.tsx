import { useEffect, useState } from 'react';
import { api, CorpusDashboard, CorpusFamilySummary } from '../api';

function formatTimestamp(value: string) {
  return value ? new Date(value).toLocaleString() : '-';
}

function readinessClass(value: string) {
  return `readiness-${value.toLowerCase()}`;
}

function CorpusFamilyRow({ family }: { family: CorpusFamilySummary }) {
  return (
    <tr>
      <th scope="row">{family.family}</th>
      <td>{family.total_observations}</td>
      <td className="corpusMatch">{family.match_count}</td>
      <td>{family.unknown_count}</td>
      <td className={family.mismatch_count ? 'corpusRisk' : ''}>{family.mismatch_count}</td>
      <td className={family.failed_count ? 'corpusRisk' : ''}>{family.failed_count}</td>
      <td>{family.unique_device_label_count}</td>
      <td>{family.unique_device_serial_count}</td>
      <td>{family.unique_locale_count}</td>
      <td>{formatTimestamp(family.last_seen_at)}</td>
      <td>
        <span className={`readinessBadge ${readinessClass(family.readiness)}`}>
          {family.readiness.replaceAll('_', ' ')}
        </span>
      </td>
      <td>{family.candidate_for_v11_pilot ? 'YES' : 'NO'}</td>
    </tr>
  );
}

export function CorpusReadinessPanel() {
  const [dashboard, setDashboard] = useState<CorpusDashboard | null>(null);
  const [error, setError] = useState('');
  const [opening, setOpening] = useState('');

  async function refresh() {
    try {
      setDashboard(await api.getV10CorpusSummary());
      setError('');
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function openTarget(target: 'folder' | 'index' | 'family-summary' | 'readiness-summary') {
    setOpening(target);
    try {
      await api.openV10CorpusTarget(target);
      setError('');
    } catch (err) {
      setError(String(err));
    } finally {
      setOpening('');
    }
  }

  return (
    <article className="panel corpusReadinessPanel">
      <div className="corpusHeader">
        <div>
          <span className="corpusEyebrow">Accumulated history</span>
          <h2>V10 Corpus Readiness</h2>
          <p>Cross-run shadow evidence for V11 pilot review. Controlled Routing remains disabled.</p>
        </div>
        <button type="button" onClick={refresh}>Refresh</button>
      </div>

      {error && <div className="shadowValidationError">{error}</div>}
      {!dashboard && !error && <p>Loading corpus data...</p>}
      {dashboard && !dashboard.available && <div className="corpusEmpty">No corpus data</div>}

      {dashboard?.available && (
        <>
          <div className="corpusMetrics">
            <div><small>Total Corpus Entries</small><strong>{dashboard.entry_count}</strong></div>
            <div><small>Last Updated</small><strong className="corpusDate">{formatTimestamp(dashboard.last_updated)}</strong></div>
            <div><small>Overall</small><strong className={readinessClass(dashboard.overall_readiness)}>{dashboard.overall_readiness}</strong></div>
            <div><small>V11 Candidates</small><strong>{dashboard.candidate_count}</strong></div>
            <div><small>BLOCKED Families</small><strong className="readiness-blocked">{dashboard.family_readiness_counts.BLOCKED}</strong></div>
            <div><small>INSUFFICIENT DATA</small><strong>{dashboard.family_readiness_counts.INSUFFICIENT_DATA}</strong></div>
          </div>

          <div className="corpusEvidence">
            <span>MATCH <strong>{dashboard.totals.MATCH}</strong></span>
            <span>UNKNOWN <strong>{dashboard.totals.UNKNOWN}</strong></span>
            <span>MISMATCH <strong>{dashboard.totals.MISMATCH}</strong></span>
            <span>FAILED <strong>{dashboard.totals.FAILED}</strong></span>
            <span>Unique models <strong>{dashboard.diversity_metrics.unique_device_models}</strong></span>
            <span>Locales <strong>{dashboard.diversity_metrics.unique_locales}</strong></span>
          </div>

          <div className="corpusTableWrap">
            <table className="corpusTable">
              <thead>
                <tr>
                  <th>Family</th>
                  <th>Observations</th>
                  <th>MATCH</th>
                  <th>UNKNOWN</th>
                  <th>MISMATCH</th>
                  <th>FAILED</th>
                  <th>Unique Labels</th>
                  <th>Unique Devices</th>
                  <th>Locale Count</th>
                  <th>Last Seen</th>
                  <th>Readiness</th>
                  <th>V11 Candidate</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.families.map((family) => (
                  <CorpusFamilyRow key={family.family} family={family} />
                ))}
              </tbody>
            </table>
          </div>

          <div className="corpusFooter">
            <div>
              <small>Blocking families</small>
              <strong>{dashboard.blocking_families.join(', ') || 'None'}</strong>
            </div>
            <div>
              <small>Unknown-only families</small>
              <strong>{dashboard.unknown_only_families.join(', ') || 'None'}</strong>
            </div>
            <div className="corpusActions">
              {[
                ['folder', 'Open Corpus Folder'],
                ['index', 'Open Corpus Index'],
                ['family-summary', 'Open Family Summary'],
                ['readiness-summary', 'Open Readiness Summary'],
              ].map(([target, label]) => (
                <button
                  type="button"
                  key={target}
                  disabled={Boolean(opening)}
                  onClick={() => openTarget(target as 'folder' | 'index' | 'family-summary' | 'readiness-summary')}
                >
                  {opening === target ? 'Opening...' : label}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </article>
  );
}
