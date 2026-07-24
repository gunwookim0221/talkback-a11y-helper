import { useEffect, useState } from 'react';
import { api, ComparatorBaseline, ComparatorCandidate, ComparatorEnvironment, ComparisonHistoryEntry } from '../api';

const sections = [
  ['limitation_binding_deltas', 'Known Limitation'], ['new_failure_items', 'New Failure'],
  ['resolved_failure_items', 'Resolved Failure'], ['review_items', 'Review Item'],
] as const;
const dimensions = [
  ['environment_delta', 'Environment'], ['app_version_delta', 'Version'], ['compatibility_grade', 'Compatibility'],
  ['coverage_aggregate_delta', 'Coverage'], ['identity_aggregate_delta', 'Identity'], ['traversal_aggregate_delta', 'Traversal'],
  ['recovery_aggregate_delta', 'Recovery'], ['profiler_aggregate_delta', 'Profiler'],
] as const;

function valueAt(result: Record<string, unknown>, name: string): unknown {
  return result[name] ?? (result.summary as Record<string, unknown> | undefined)?.[name];
}

function normalizeVerdict(value: unknown): string {
  if (typeof value === 'string' && value.trim()) {
    return value.trim();
  }
  if (value && typeof value === 'object') {
    const overall = (value as Record<string, unknown>).overall;
    if (typeof overall === 'string' && overall.trim()) {
      return overall.trim();
    }
  }
  return 'UNKNOWN';
}

function VerdictBadge({ verdict }: { verdict: unknown }) {
  const label = normalizeVerdict(verdict);
  const css = `compareVerdict compareVerdict-${label.toLowerCase().replaceAll('_', '-')}`;
  return <span className={css}>{label.replaceAll('_', ' ')}</span>;
}

function displayValue(value: unknown): string {
  if (value && typeof value === 'object') {
    const item = value as Record<string, unknown>;
    return String(item.status ?? item.relation ?? item.overall ?? '-');
  }
  return String(value ?? '-');
}

function reasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    DIRTY: 'DIRTY', full_scenario_set: 'TARGETED', working_tree_clean: 'DIRTY',
    required_artifacts: 'MISSING ARTIFACT', environment_fingerprint_complete: 'INCOMPLETE ENVIRONMENT',
  };
  return labels[reason] ?? reason.replaceAll('_', ' ').toUpperCase();
}

function structuredReason(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object') {
    const item = value as Record<string, unknown>;
    const code = typeof item.code === 'string' ? item.code : typeof item.reason === 'string' ? item.reason : '';
    const detail = item.details ?? item.message ?? item.locales;
    if (code && detail !== undefined) return `${code}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`;
    if (code) return code;
    return JSON.stringify(value);
  }
  return String(value ?? 'UNKNOWN');
}

function reasonField(value: unknown, field: string): unknown {
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)[field]
    : undefined;
}

function unknownValue(value: string | number | null | undefined): string {
  return value === null || value === undefined || String(value).trim() === '' ? 'Unknown' : String(value);
}

function majorValue(value: string | number | null | undefined): string {
  const text = unknownValue(value);
  return text === 'Unknown' ? text : text.split('.')[0];
}

function androidToken(value: string | number | null | undefined): string {
  const major = majorValue(value);
  return major === 'Unknown' ? 'Unknown Android' : `A${major}`;
}

function shortDeviceFamily(item: ComparatorCandidate | ComparatorBaseline): string {
  const family = item.device_family?.toLowerCase();
  const labels: Record<string, string> = {
    'galaxy-z-flip6': 'Flip6',
    'galaxy-z-fold8': 'Fold8',
  };
  return labels[family ?? ''] ?? (item.device_model ? item.device_model : 'Unknown device');
}

function formFactorLabel(value: string | null): string {
  if (!value) return 'Unknown';
  return value.replaceAll('_', ' ');
}

function talkBackLabel(packageName: string | null): string {
  if (!packageName) return 'Unknown';
  if (packageName === 'com.google.android.marvin.talkback') return 'Google TalkBack';
  if (packageName === 'com.samsung.android.accessibility.talkback') return 'Samsung TalkBack';
  return packageName;
}

function candidateLabel(item: ComparatorCandidate): string {
  const batch = item.run.startsWith('batch_') ? item.run.slice('batch_'.length) : item.run;
  return `${unknownValue(item.locale)} · ${shortDeviceFamily(item)} · ${androidToken(item.android_major)} · ${unknownValue(item.app_version)} · ${batch} · ${unknownValue(item.source_status_label)}`;
}

function baselineLabel(item: ComparatorBaseline): string {
  return `${unknownValue(item.locale)} · ${shortDeviceFamily(item)} · ${androidToken(item.android_major)} · ${unknownValue(item.app_version)} · r${unknownValue(item.revision)}`;
}

function deviceSummary(item: ComparatorCandidate | ComparatorBaseline): string {
  const family = shortDeviceFamily(item);
  return item.device_model && item.device_model !== family ? `${family} · ${item.device_model}` : family;
}

function talkBackSummary(item: ComparatorCandidate | ComparatorBaseline): string {
  const provider = talkBackLabel(item.talkback_package);
  const major = majorValue(item.talkback_major);
  return provider === 'Unknown' && major === 'Unknown' ? 'Unknown TalkBack' : `${provider} ${major}`;
}

function environmentDifferences(candidate: ComparatorCandidate, baseline: ComparatorBaseline): string[] {
  const fields: Array<[keyof ComparatorEnvironment, string]> = [
    ['locale', 'Locale'], ['device_family', 'Device'], ['form_factor', 'Form factor'],
    ['android_major', 'Android'], ['one_ui_major', 'One UI'], ['talkback_package', 'TalkBack package'],
    ['talkback_major', 'TalkBack major'], ['app_version', 'App version'],
  ];
  return fields.filter(([field]) => String(candidate[field] ?? '') !== String(baseline[field] ?? '')).map(([, label]) => label);
}

function EnvironmentCard({ label, item }: { label: string; item: ComparatorCandidate | ComparatorBaseline }) {
  return <article className="environmentCard">
    <h4>{label}</h4>
    <div className="environmentCardSummary">
      <p title={deviceSummary(item)}>{deviceSummary(item)}</p>
      <p title={`Android ${majorValue(item.android_major)} · One UI ${majorValue(item.one_ui_major)}`}>{`Android ${majorValue(item.android_major)} · One UI ${majorValue(item.one_ui_major)}`}</p>
      <p title={talkBackSummary(item)}>{talkBackSummary(item)}</p>
      <p title={`Fingerprint ${unknownValue(item.fingerprint_status)}`}>{`Fingerprint ${unknownValue(item.fingerprint_status)}`}</p>
    </div>
    <div className="environmentCardMeta">Locale {unknownValue(item.locale)} · App {unknownValue(item.app_version)} · {formFactorLabel(item.form_factor)}</div>
  </article>;
}

export function ComparePanel() {
  const [baselines, setBaselines] = useState<ComparatorBaseline[]>([]);
  const [candidates, setCandidates] = useState<ComparatorCandidate[]>([]);
  const [baselineId, setBaselineId] = useState('');
  const [candidateId, setCandidateId] = useState('');
  const [history, setHistory] = useState<ComparisonHistoryEntry[]>([]);
  const [selected, setSelected] = useState<ComparisonHistoryEntry | null>(null);
  const [markdown, setMarkdown] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function refresh() {
    setError('');
    try {
      const [baselineResponse, candidateResponse, historyResponse] = await Promise.all([
        api.comparatorBaselines(), api.comparatorCandidates(), api.comparisonHistory(),
      ]);
      setBaselines(baselineResponse.baselines); setCandidates(candidateResponse.candidates); setHistory(historyResponse.comparisons);
      setBaselineId((current) => current || baselineResponse.baselines[0]?.baseline_id || '');
      setCandidateId((current) => current || candidateResponse.candidates[0]?.candidate_id || '');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Comparator catalog could not be loaded.'); }
  }
  useEffect(() => { refresh(); }, []);

  async function open(entry: ComparisonHistoryEntry) {
    setBusy(true); setError('');
    try {
      const [detail, report] = await Promise.all([api.comparisonResult(entry.comparison_id), api.comparisonMarkdown(entry.comparison_id)]);
      setSelected(detail); setMarkdown(report);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Comparison report could not be opened.'); }
    finally { setBusy(false); }
  }
  async function compare() {
    if (!baselineId || !candidateId) return;
    setBusy(true); setError('');
    try {
      const result = await api.compare(baselineId, candidateId);
      setHistory(await api.comparisonHistory().then((response) => response.comparisons));
      await open(result);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Comparison failed.'); }
    finally { setBusy(false); }
  }
  const result = selected?.result ?? {};
  const verdict = result.verdict ?? selected?.verdict;
  const verdictObject = result.verdict && typeof result.verdict === 'object' ? result.verdict as Record<string, unknown> : {};
  const verdictLabel = normalizeVerdict(verdict);
  const recommendation = verdictObject.recommendation ?? '-';
  const verdictReasons = Array.isArray(verdictObject.reasons) ? verdictObject.reasons : [];
  const compatibilityReasons = Array.isArray(result.compatibility_reasons) ? result.compatibility_reasons : [];
  const reviewItems = Array.isArray(result.review_items) ? result.review_items : [];
  const sourceCandidate = candidates.find((item) => item.candidate_id === selected?.candidate_id);
  const sourceWarnings = sourceCandidate && sourceCandidate.source_status !== 'APPROVED_SOURCE' && sourceCandidate.source_status_label
    ? [sourceCandidate.source_status_label, ...(sourceCandidate.blocking_reasons ?? []).map(reasonLabel)] : [];
  const blockingReasons = verdictLabel === 'INCOMPARABLE'
    ? [
      ...compatibilityReasons,
      ...verdictReasons.filter((reason) => ['input', 'selection'].includes(String(reasonField(reason, 'dimension') ?? ''))),
    ]
    : [];
  const reasonSections = verdictLabel === 'INCOMPARABLE' || verdictLabel === 'REVIEW_REQUIRED' || verdictLabel === 'FAIL'
    ? [
      ['Blocking reasons', blockingReasons],
      ['Review reasons', [...verdictReasons, ...reviewItems]],
      ['Source warnings', sourceWarnings],
    ] as const : [];
  const selectedCandidate = candidates.find((item) => item.candidate_id === candidateId) ?? null;
  const selectedBaseline = baselines.find((item) => item.baseline_id === baselineId) ?? null;
  const environmentDifferenceLabels = selectedCandidate && selectedBaseline
    ? environmentDifferences(selectedCandidate, selectedBaseline)
    : [];

  return <section className="panel comparePanel">
    <div className="compareHeader"><div><h2>Baseline Comparator</h2><p>Read-only comparison. Approval remains a manual workflow.</p></div><button onClick={refresh} disabled={busy}>Refresh inputs</button></div>
    {error && <div className="error">{error}</div>}
    <div className="compareSelectors">
      <label htmlFor="comparator-candidate">Available run / candidate<select id="comparator-candidate" title={selectedCandidate ? candidateLabel(selectedCandidate) : undefined} aria-describedby="comparator-input-hint" value={candidateId} disabled={busy || !candidates.length} onChange={(event) => setCandidateId(event.target.value)}>{candidates.map((item) => <option key={`${item.candidate_id}-${item.source}`} title={candidateLabel(item)} value={item.candidate_id}>{candidateLabel(item)}</option>)}</select></label>
      <label htmlFor="comparator-baseline">Approved baseline<select id="comparator-baseline" title={selectedBaseline ? baselineLabel(selectedBaseline) : undefined} aria-describedby="comparator-input-hint" value={baselineId} disabled={busy || !baselines.length} onChange={(event) => setBaselineId(event.target.value)}>{baselines.map((item) => <option key={item.baseline_id} title={baselineLabel(item)} value={item.baseline_id}>{baselineLabel(item)}</option>)}</select></label>
      <button className="compareAction" onClick={compare} disabled={busy || !baselineId || !candidateId}>{busy ? 'Comparing…' : 'Compare'}</button>
    </div>
    <p id="comparator-input-hint" className="compareInputHint">Runs are local comparison inputs. Approved baselines are managed separately. Full environment values are available below each selection.</p>
    {selectedCandidate && (() => { const reasons = selectedCandidate.blocking_reasons?.map(reasonLabel) ?? []; return <div className="compareCandidateDetail"><strong>{selectedCandidate.source_status_label ?? 'UNKNOWN'}</strong>{selectedCandidate.approved_baseline_id && <span> · {selectedCandidate.approved_baseline_id}</span>}{reasons.length > 0 && <span> · Reason: {reasons.join(', ')}</span>}</div>; })()}
    {selectedCandidate && selectedBaseline && <>
      <div className="environmentCards" aria-live="polite">
        <EnvironmentCard label="Candidate environment" item={selectedCandidate} />
        <EnvironmentCard label="Baseline environment" item={selectedBaseline} />
      </div>
      <div className={`environmentNotice ${environmentDifferenceLabels.length ? 'environmentNoticeWarn' : 'environmentNoticeCompatible'}`} role="status">
        <strong>{environmentDifferenceLabels.length ? 'Environment differs' : 'Environment appears compatible'}</strong>
        <span>{environmentDifferenceLabels.length ? `Compared fields: ${environmentDifferenceLabels.join(', ')}. This is guidance only; Comparator Core still determines compatibility and verdict.` : 'No configured environment fields differ. Fingerprint status alone is not used as an equality decision.'}</span>
      </div>
    </>}
    {!baselines.length && !error && <div className="notice">No approved baseline is available.</div>}
    {!candidates.length && !error && <div className="notice">No candidate run is available.</div>}
    {selected && <div className="compareResult">
      <div className="compareResultHeader"><div><h3>Comparison result</h3><small>{selected.comparison_id}</small></div><VerdictBadge verdict={verdict} /></div>
      {reasonSections.filter(([, items]) => items.length > 0).map(([label, items]) => <details className="verdictReasons" key={label} open><summary>{label}</summary><ul>{items.map((item, index) => <li key={`${label}-${index}`}>{structuredReason(item)}</li>)}</ul></details>)}
      <div className="compareMetrics">{dimensions.map(([key, label]) => <div key={key}><small>{label}</small><strong>{displayValue(valueAt(result, key))}</strong></div>)}</div>
      <div className="compareReview">{sections.map(([key, label]) => { const items = valueAt(result, key); const nested = items && typeof items === 'object' ? (items as Record<string, unknown>).bindings : undefined; const rows = Array.isArray(items) ? items : Array.isArray(nested) ? nested : []; return <details key={key}><summary>{label} <span>{rows.length}</span></summary><pre>{rows.length ? JSON.stringify(rows, null, 2) : 'None'}</pre></details>; })}</div>
      <div className="compareRecommendation"><strong>Recommendation</strong><p>{String(recommendation)}</p></div>
      <details className="markdownViewer" open><summary>Markdown report</summary><pre>{markdown || 'Loading report…'}</pre></details>
      <div className="downloadActions"><a className="downloadButton" href={api.comparisonJsonDownloadUrl(selected.comparison_id)}>Download JSON</a><a className="downloadButton" href={api.comparisonMarkdownDownloadUrl(selected.comparison_id)}>Download Markdown</a></div>
    </div>}
    <div className="compareHistory"><h3>Recent comparisons</h3>{history.length ? history.map((item) => <button key={`${item.comparison_id}-${item.compared_at}`} onClick={() => open(item)} disabled={busy}><VerdictBadge verdict={item.verdict} /><span>{item.candidate_id} → {item.baseline_id}</span><small>{item.compared_at}</small></button>) : <small>No comparison in this server session.</small>}</div>
  </section>;
}
