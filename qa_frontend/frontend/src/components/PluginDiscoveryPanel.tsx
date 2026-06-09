import { useEffect, useState } from 'react';
import {
  api,
  PluginDiscoveryCard,
  PluginDiscoveryResponse,
  PluginDraftApplyResponse,
  PluginDraftResponse,
  PluginDraftReviewResponse,
  PluginDraftSmokeResponse,
  PluginDraftSmokeStatusResponse,
  PluginOnboardingSession,
  PluginOnboardingRestoreResponse,
  PluginProbeResponse,
  PluginRollbackExecuteResponse,
  PluginRollbackPreviewResponse,
} from '../api';

type Target = 'life' | 'device';

export function PluginDiscoveryPanel({ running, reportError }: { running: boolean; reportError: (err: unknown) => void }) {
  const [targets, setTargets] = useState<Set<Target>>(new Set(['life', 'device']));
  const [discovering, setDiscovering] = useState(false);
  const [probingCardId, setProbingCardId] = useState<string | null>(null);
  const [result, setResult] = useState<PluginDiscoveryResponse | null>(null);
  const [probeResult, setProbeResult] = useState<PluginProbeResponse | null>(null);
  const [probeCard, setProbeCard] = useState<PluginDiscoveryCard | null>(null);
  const [draftGenerating, setDraftGenerating] = useState(false);
  const [draftResult, setDraftResult] = useState<PluginDraftResponse | null>(null);
  const [reviewingDraft, setReviewingDraft] = useState(false);
  const [reviewResult, setReviewResult] = useState<PluginDraftReviewResponse | null>(null);
  const [applyingDraft, setApplyingDraft] = useState(false);
  const [applyResult, setApplyResult] = useState<PluginDraftApplyResponse | null>(null);
  const [smokingDraft, setSmokingDraft] = useState(false);
  const [smokeResult, setSmokeResult] = useState<PluginDraftSmokeResponse | null>(null);
  const [refreshingSmoke, setRefreshingSmoke] = useState(false);
  const [smokeStatusResult, setSmokeStatusResult] = useState<PluginDraftSmokeStatusResponse | null>(null);
  const [sessionId, setSessionId] = useState<string>('');
  const [sessionSaving, setSessionSaving] = useState(false);
  const [sessionRestoring, setSessionRestoring] = useState(false);
  const [recentSessions, setRecentSessions] = useState<PluginOnboardingSession[]>([]);
  const [restoreResult, setRestoreResult] = useState<PluginOnboardingRestoreResponse | null>(null);
  const [rollbackPreviewing, setRollbackPreviewing] = useState(false);
  const [rollbackPreview, setRollbackPreview] = useState<PluginRollbackPreviewResponse | null>(null);
  const [rollbackExecuting, setRollbackExecuting] = useState(false);
  const [rollbackResult, setRollbackResult] = useState<PluginRollbackExecuteResponse | null>(null);
  const [removingAppliedDraft, setRemovingAppliedDraft] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  async function refreshSessions() {
    try {
      const response = await api.listPluginOnboardingSessions();
      setRecentSessions(response.sessions);
    } catch (err) {
      reportError(err);
    }
  }

  useEffect(() => {
    refreshSessions();
  }, []);

  useEffect(() => {
    let intervalId: number | undefined;
    const shouldPoll = smokeResult && !refreshingSmoke && (!smokeStatusResult || !['finished', 'error', 'stopped'].includes(smokeStatusResult.run_status));
    
    if (shouldPoll) {
      intervalId = window.setInterval(async () => {
        if (!smokeResult.run_id || !smokeResult.scenario_id) return;
        try {
          const response = await api.getPluginDraftSmokeStatus(smokeResult.run_id, smokeResult.scenario_id);
          setSmokeStatusResult(response);
          await saveSessionStep('smoke', response.smoke_status, response as unknown as Record<string, unknown>);
        } catch (err) {
          console.error(err);
        }
      }, 3000);
    }
    
    return () => {
      if (intervalId !== undefined) {
        window.clearInterval(intervalId);
      }
    };
  }, [smokeResult, smokeStatusResult?.run_status, refreshingSmoke]);

  function toggleTarget(target: Target) {
    setTargets((current) => {
      const next = new Set(current);
      if (next.has(target)) {
        next.delete(target);
      } else {
        next.add(target);
      }
      return next;
    });
  }

  async function discover() {
    setDiscovering(true);
    setResult(null);
    setProbeResult(null);
    setProbeCard(null);
    setDraftResult(null);
    setReviewResult(null);
    setApplyResult(null);
    setSmokeResult(null);
    setSmokeStatusResult(null);
    try {
      const response = await api.discoverPlugins({
        targets: Array.from(targets),
        include_xml: true,
        current_view_only: true,
      });
      setResult(response);
      if (sessionId) {
        await saveSessionStep('discovery', 'completed', response as unknown as Record<string, unknown>);
      }
    } catch (err) {
      reportError(err);
    } finally {
      setDiscovering(false);
    }
  }

  async function startSession(card: PluginDiscoveryCard) {
    setSessionSaving(true);
    try {
      const response = await api.createPluginOnboardingSession({
        card: {
          label: card.label,
          stable_label: card.stable_label,
          type: card.type,
          existing_scenario_id: card.existing_scenario_id,
        },
      });
      setSessionId(response.session_id);
      setProbeCard(card);
      await api.savePluginOnboardingStep(response.session_id, {
        step: 'discovery',
        status: 'completed',
        payload: { card },
      });
      await refreshSessions();
    } catch (err) {
      reportError(err);
    } finally {
      setSessionSaving(false);
    }
  }

  async function saveSessionStep(step: string, status: string, payload: Record<string, unknown>) {
    if (!sessionId) {
      return;
    }
    setSessionSaving(true);
    try {
      await api.savePluginOnboardingStep(sessionId, { step, status, payload });
      await refreshSessions();
    } catch (err) {
      reportError(err);
    } finally {
      setSessionSaving(false);
    }
  }

  function applyRestoredState(response: PluginOnboardingRestoreResponse) {
    const restored = response.restored_state;
    const selectedCard = restored.selected_card;
    setRestoreResult(response);
    setRollbackPreview(null);
    setRollbackResult(null);
    setSessionId(response.session.session_id);
    setProbeCard(selectedCard?.stable_label ? (selectedCard as PluginDiscoveryCard) : null);
    setProbeResult(restored.probe_result?.schema_version ? (restored.probe_result as PluginProbeResponse) : null);
    setDraftResult(restored.draft_result?.schema_version ? (restored.draft_result as PluginDraftResponse) : null);
    setReviewResult(restored.review_result?.schema_version ? (restored.review_result as PluginDraftReviewResponse) : null);
    setApplyResult(restored.apply_result?.schema_version ? (restored.apply_result as PluginDraftApplyResponse) : null);
    setSmokeResult(restored.smoke_start_result?.schema_version ? (restored.smoke_start_result as PluginDraftSmokeResponse) : null);
    setSmokeStatusResult(restored.smoke_status_result?.schema_version ? (restored.smoke_status_result as PluginDraftSmokeStatusResponse) : null);
  }

  async function restoreSession(targetSessionId = sessionId) {
    if (!targetSessionId) {
      return;
    }
    setSessionRestoring(true);
    try {
      const response = await api.restorePluginOnboardingSession(targetSessionId);
      applyRestoredState(response);
    } catch (err) {
      reportError(err);
    } finally {
      setSessionRestoring(false);
    }
  }

  async function previewRollback() {
    if (!sessionId) {
      return;
    }
    setRollbackPreviewing(true);
    setRollbackResult(null);
    try {
      const response = await api.previewPluginRollback(sessionId);
      setRollbackPreview(response);
    } catch (err) {
      reportError(err);
    } finally {
      setRollbackPreviewing(false);
    }
  }

  async function executeRollback() {
    if (!sessionId || !rollbackPreview?.can_rollback) {
      return;
    }
    const confirmed = window.confirm('Restore scenario_config.py and runtime_config.json from backup?');
    if (!confirmed) {
      return;
    }
    setRollbackExecuting(true);
    try {
      const response = await api.executePluginRollback(sessionId, { confirm: true });
      setRollbackResult(response);
      await refreshSessions();
      await restoreSession(sessionId);
    } catch (err) {
      reportError(err);
    } finally {
      setRollbackExecuting(false);
    }
  }

  async function probe(card: PluginDiscoveryCard) {
    setProbingCardId(card.id);
    setProbeResult(null);
    setDraftResult(null);
    setReviewResult(null);
    setApplyResult(null);
    setSmokeResult(null);
    setSmokeStatusResult(null);
    setProbeCard(card);
    try {
      const response = await api.startPluginProbe({
        card,
        max_probe_steps: 5,
        include_xml: true,
        include_helper_dump: true,
      });
      setProbeResult(response);
      await saveSessionStep('probe', 'completed', response as unknown as Record<string, unknown>);
    } catch (err) {
      reportError(err);
    } finally {
      setProbingCardId(null);
    }
  }

  async function generateDraft() {
    if (!probeCard || !probeResult) {
      return;
    }
    setDraftGenerating(true);
    setDraftResult(null);
    setReviewResult(null);
    setApplyResult(null);
    setSmokeResult(null);
    setSmokeStatusResult(null);
    try {
      const response = await api.generatePluginDraft({
        card: probeCard,
        probe: probeResult,
        options: {
          include_disabled_runtime_config: true,
        },
      });
      setDraftResult(response);
      await saveSessionStep('draft', 'completed', response as unknown as Record<string, unknown>);
    } catch (err) {
      reportError(err);
    } finally {
      setDraftGenerating(false);
    }
  }

  async function reviewDraft() {
    if (!draftResult) {
      return;
    }
    setReviewingDraft(true);
    setReviewResult(null);
    setApplyResult(null);
    setSmokeResult(null);
    setSmokeStatusResult(null);
    try {
      const response = await api.reviewPluginDraft({
        draft: draftResult.draft,
        options: {
          include_diff_preview: true,
          check_existing: true,
        },
      });
      setReviewResult(response);
      await saveSessionStep('review', response.review_status, response as unknown as Record<string, unknown>);
    } catch (err) {
      reportError(err);
    } finally {
      setReviewingDraft(false);
    }
  }

  async function applyDraft() {
    if (!draftResult || !reviewResult) {
      return;
    }
    setApplyingDraft(true);
    setApplyResult(null);
    setSmokeResult(null);
    try {
      const response = await api.applyPluginDraft({
        draft: draftResult.draft,
        review: reviewResult,
        options: {
          create_backup: true,
        },
      });
      setApplyResult(response);
      await saveSessionStep('apply', response.apply_status, response as unknown as Record<string, unknown>);
    } catch (err) {
      reportError(err);
    } finally {
      setApplyingDraft(false);
    }
  }

  async function smokeDraft() {
    const scenarioId = applyResult?.applied.scenario_id;
    if (!scenarioId) {
      return;
    }
    setSmokingDraft(true);
    setSmokeResult(null);
    setSmokeStatusResult(null);
    try {
      const response = await api.smokePluginDraft({
        scenario_id: scenarioId,
        max_steps: 5,
        mode: 'smoke',
        serial: null,
        options: {
          force_enabled_runtime_override: true,
          collect_summary: true,
        },
      });
      setSmokeResult(response);
      await saveSessionStep('smoke', response.smoke_status, response as unknown as Record<string, unknown>);
    } catch (err) {
      reportError(err);
    } finally {
      setSmokingDraft(false);
    }
  }


  async function removeAppliedDraft() {
    if (!sessionId || !applyResult?.applied.scenario_id) return;
    const confirmed = window.confirm('Remove applied draft from scenario_config.py and runtime_config.json?');
    if (!confirmed) return;
    
    setRemovingAppliedDraft(true);
    try {
      await api.removeAppliedDraft(sessionId, { confirm: true });
      setApplyResult(null);
      setSmokeResult(null);
      setSmokeStatusResult(null);
      await saveSessionStep('apply', 'removed', {});
    } catch (err) {
      // reportError(err);
      console.error(err);
    } finally {
      setRemovingAppliedDraft(false);
    }
  }

  async function deleteSession(id: string) {
    const confirmed = window.confirm(`Delete session ${id}?`);
    if (!confirmed) return;
    
    setDeletingSessionId(id);
    try {
      await api.deleteSession(id);
      if (id === sessionId) {
        setSessionId('');
        setRestoreResult(null);
        setRollbackPreview(null);
        setRollbackResult(null);
        setProbeCard(null);
        setProbeResult(null);
        setDraftResult(null);
        setReviewResult(null);
        setApplyResult(null);
        setSmokeResult(null);
        setSmokeStatusResult(null);
      }
      await refreshSessions();
    } catch (err) {
      console.error(err);
    } finally {
      setDeletingSessionId(null);
    }
  }
  async function refreshSmokeResult() {
    if (!smokeResult?.run_id || !smokeResult.scenario_id) {
      return;
    }
    setRefreshingSmoke(true);
    try {
      const response = await api.getPluginDraftSmokeStatus(smokeResult.run_id, smokeResult.scenario_id);
      setSmokeStatusResult(response);
      await saveSessionStep('smoke', response.smoke_status, response as unknown as Record<string, unknown>);
    } catch (err) {
      reportError(err);
    } finally {
      setRefreshingSmoke(false);
    }
  }

  const disabled = running || discovering || targets.size === 0;

  return (
    <article className="panel pluginDiscoveryPanel">
      <div className="panelHeader">
        <div>
          <h2>Plugin Discovery</h2>
          <p>Visible plugin candidates on the current SmartThings screen.</p>
        </div>
        <button onClick={discover} disabled={disabled}>
          {discovering ? 'Discovering...' : 'Discover Plugins'}
        </button>
      </div>

      <div className="pluginDiscoveryControls">
        <label>
          <input type="checkbox" checked={targets.has('life')} onChange={() => toggleTarget('life')} disabled={running || discovering} />
          Life
        </label>
        <label>
          <input type="checkbox" checked={targets.has('device')} onChange={() => toggleTarget('device')} disabled={running || discovering} />
          Device
        </label>
      </div>

      <div className="onboardingSessionPanel">
        <div>
          <span>Current Session ID</span>
          <strong>{sessionId || '-'}</strong>
        </div>
        <div>
          <span>Session Save</span>
          <strong>{sessionRestoring ? 'Restoring...' : sessionSaving ? 'Saving...' : 'Idle'}</strong>
        </div>
        <div className="onboardingRecentSessions">
          <span>Recent Onboarding Sessions</span>
          <div>
            {recentSessions.length === 0
              ? '-'
              : recentSessions.slice(0, 5).map((session) => (
                  <div key={session.session_id} style={{ display: 'flex', gap: '4px', marginBottom: '4px' }}>
                    <button type="button" onClick={() => restoreSession(session.session_id)}>
                      {session.plugin.stable_label || session.session_id} · {session.status}
                    </button>
                    <button type="button" onClick={() => deleteSession(session.session_id)} disabled={deletingSessionId === session.session_id}>
                      Delete
                    </button>
                  </div>
                ))}
          </div>
        </div>
        <div className="onboardingSessionActions">
          <button type="button" onClick={() => restoreSession()} disabled={!sessionId || sessionRestoring}>
            Restore Session
          </button>
        </div>
      </div>

      {restoreResult && (
        <div className={`onboardingRecommendation recommendation-${restoreResult.recommendation.severity}`}>
          <div>
            <span>Next Action</span>
            <strong>{restoreResult.recommendation.next_action}</strong>
          </div>
          <div>
            <span>Severity</span>
            <strong>{restoreResult.recommendation.severity}</strong>
          </div>
          <div>
            <span>Reasons</span>
            <p>{restoreResult.recommendation.reasons.join(', ') || '-'}</p>
          </div>
          <div>
            <span>Allowed Actions</span>
            <p>{restoreResult.recommendation.allowed_actions.join(', ') || '-'}</p>
          </div>
          <div>
            <span>Blocked Actions</span>
            <p>{restoreResult.recommendation.blocked_actions.join(', ') || '-'}</p>
          </div>
          {restoreResult.recommendation.next_action === 'apply_rollback_candidate' && (
            <div className="rollbackPreviewAction">
              <button type="button" onClick={previewRollback} disabled={rollbackPreviewing || !sessionId}>
                {rollbackPreviewing ? 'Previewing Rollback...' : 'Rollback Preview'}
              </button>
            </div>
          )}
        </div>
      )}

      {rollbackPreview && (
        <div className="rollbackPreviewPanel">
          <h3>Rollback Preview</h3>
          <div className="probeSummaryGrid">
            <div>
              <span>Can Rollback</span>
              <strong>{rollbackPreview.can_rollback ? 'Yes' : 'No'}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{rollbackPreview.rollback_status}</strong>
            </div>
            <div>
              <span>Backup Found</span>
              <strong>{rollbackPreview.backup.found ? 'Yes' : 'No'}</strong>
            </div>
            <div>
              <span>Scenario Removed</span>
              <strong>{rollbackPreview.preview.scenario_entry_will_be_removed ? 'Yes' : 'No'}</strong>
            </div>
            <div>
              <span>Runtime Removed</span>
              <strong>{rollbackPreview.preview.runtime_config_entry_will_be_removed ? 'Yes' : 'No'}</strong>
            </div>
          </div>
          <div className="probeSeedGrid">
            <div>
              <h4>Target Files</h4>
              <p>{rollbackPreview.target_files.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Backup Paths</h4>
              <p>{rollbackPreview.backup.paths.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Warnings</h4>
              <p>{rollbackPreview.diagnostics.warnings.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Errors</h4>
              <p>{rollbackPreview.diagnostics.errors.join(', ') || '-'}</p>
            </div>
          </div>
          <div className="draftPreviewGrid">
            <div className="draftPreviewFullWidth">
              <h4>Diff Preview</h4>
              <pre>{rollbackPreview.preview.diff_preview || '-'}</pre>
            </div>
          </div>
          <div className="probeDraftActions">
            <button type="button" onClick={executeRollback} disabled={running || rollbackExecuting || !rollbackPreview.can_rollback}>
              {rollbackExecuting ? 'Executing Rollback...' : 'Execute Rollback'}
            </button>
          </div>
        </div>
      )}

      {rollbackResult && (
        <div className="rollbackPreviewPanel">
          <h3>Rollback Result</h3>
          <div className="probeSummaryGrid">
            <div>
              <span>Rollback Status</span>
              <strong>{rollbackResult.rollback_status}</strong>
            </div>
            <div>
              <span>Session ID</span>
              <strong>{rollbackResult.session_id}</strong>
            </div>
          </div>
          <div className="probeSeedGrid">
            <div>
              <h4>Restored Files</h4>
              <p>{rollbackResult.restored_files.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Backup Paths</h4>
              <p>{rollbackResult.backup.paths.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Warnings</h4>
              <p>{rollbackResult.diagnostics.warnings.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Errors</h4>
              <p>{rollbackResult.diagnostics.errors.join(', ') || '-'}</p>
            </div>
          </div>
          <div className="probeSeedGrid">
            <div>
              <h4>Pre-Rollback Backup</h4>
              <p>{rollbackResult.pre_rollback_backup.join(', ') || '-'}</p>
            </div>
          </div>
        </div>
      )}

      {running && <p className="inlineWarning">Discovery is disabled while a run is in progress.</p>}

      {result?.diagnostics.warnings.length ? (
        <div className="pluginDiscoveryWarnings">
          {result.diagnostics.warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}

      {result && (
        <div className="tableWrap">
          <table className="pluginDiscoveryTable">
            <thead>
              <tr>
                <th>Type</th>
                <th>Label</th>
                <th>Stable Label</th>
                <th>Confidence</th>
                <th>Source</th>
                <th>Known</th>
                <th>Existing Scenario</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {result.cards.length === 0 ? (
                <tr>
                  <td colSpan={8}>No visible plugin candidates found.</td>
                </tr>
              ) : (
                result.cards.map((card) => (
                  <tr key={card.id}>
                    <td>{card.type}</td>
                    <td>{card.label}</td>
                    <td>{card.stable_label}</td>
                    <td>{card.confidence}</td>
                    <td>{card.source}</td>
                    <td>{card.known ? 'Yes' : 'No'}</td>
                    <td>{card.existing_scenario_id || '-'}</td>
                    <td>
                      <div className="pluginActionStack">
                        <button onClick={() => startSession(card)} disabled={running || discovering || sessionSaving}>
                          Start Onboarding Session
                        </button>
                        <button onClick={() => probe(card)} disabled={running || discovering || probingCardId === card.id}>
                          {probingCardId === card.id ? 'Probing...' : 'Probe'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {probeResult && probeCard && (
        <div className="probeResultPanel">
          <h3>Probe Result: {probeCard.stable_label}</h3>
          <div className="probeSummaryGrid">
            <div>
              <span>Status</span>
              <strong>{probeResult.probe_status}</strong>
            </div>
            <div>
              <span>Entry Method</span>
              <strong>{probeResult.entry.method || '-'}</strong>
            </div>
            <div>
              <span>Open Confirmed</span>
              <strong>{probeResult.entry.open_confirmed ? 'Yes' : 'No'}</strong>
            </div>
            <div>
              <span>Suggested Entry</span>
              <strong>{probeResult.summary.suggested_entry_method || '-'}</strong>
            </div>
          </div>

          <div className="probeDraftActions">
            <button onClick={generateDraft} disabled={running || draftGenerating}>
              {draftGenerating ? 'Generating Draft...' : 'Generate Draft'}
            </button>
          </div>

          <div className="probeSeedGrid">
            <div>
              <h4>Verify Tokens</h4>
              <p>{probeResult.seed.verify_tokens.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Headers</h4>
              <p>{probeResult.seed.headers.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Local Tabs</h4>
              <p>{probeResult.seed.local_tabs.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Representative Cards</h4>
              <p>{probeResult.seed.representative_cards.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Overlay Hints</h4>
              <p>{probeResult.seed.overlay_hints.join(', ') || '-'}</p>
            </div>
            <div>
              <h4>Warnings / Failure</h4>
              <p>{[...probeResult.diagnostics.warnings, probeResult.diagnostics.failure_reason].filter(Boolean).join(', ') || '-'}</p>
            </div>
          </div>

          {draftResult && (
            <div className="draftPreviewPanel">
              <h3>Draft Preview</h3>
              <div className="probeDraftActions">
                <button onClick={reviewDraft} disabled={running || reviewingDraft}>
                  {reviewingDraft ? 'Reviewing Draft...' : 'Review Draft'}
                </button>
              </div>
              <div className="draftPreviewGrid">
                <div>
                  <h4>Scenario Draft</h4>
                  <pre>{JSON.stringify(draftResult.draft.scenario, null, 2)}</pre>
                </div>
                <div>
                  <h4>Runtime Config Draft</h4>
                  <pre>{JSON.stringify(draftResult.draft.runtime_config, null, 2)}</pre>
                </div>
                <div>
                  <h4>Metadata</h4>
                  <pre>{JSON.stringify(draftResult.draft.metadata, null, 2)}</pre>
                </div>
                <div>
                  <h4>Warnings</h4>
                  <pre>{JSON.stringify({ warnings: draftResult.diagnostics.warnings, notes: draftResult.diagnostics.notes }, null, 2)}</pre>
                </div>
              </div>

              {reviewResult && (
                <div className="draftReviewPanel">
                  <h3>Draft Review</h3>
                  <div className="probeDraftActions">
                    <button onClick={applyDraft} disabled={running || applyingDraft || !reviewResult.checks.can_apply}>
                      {applyingDraft ? 'Applying Draft...' : 'Apply Draft'}
                    </button>
                  </div>
                  <div className="probeSummaryGrid">
                    <div>
                      <span>Review Status</span>
                      <strong>{reviewResult.review_status}</strong>
                    </div>
                    <div>
                      <span>Can Apply</span>
                      <strong>{reviewResult.checks.can_apply ? 'Yes' : 'No'}</strong>
                    </div>
                    <div>
                      <span>Scenario ID Exists</span>
                      <strong>{reviewResult.checks.scenario_id_exists ? 'Yes' : 'No'}</strong>
                    </div>
                    <div>
                      <span>Runtime Config Exists</span>
                      <strong>{reviewResult.checks.runtime_config_exists ? 'Yes' : 'No'}</strong>
                    </div>
                  </div>
                  <div className="probeSeedGrid">
                    <div>
                      <h4>Manual Review Required</h4>
                      <p>{reviewResult.checks.manual_review_required ? 'Yes' : 'No'}</p>
                    </div>
                    <div>
                      <h4>Warnings</h4>
                      <p>{reviewResult.diagnostics.warnings.join(', ') || '-'}</p>
                    </div>
                    <div>
                      <h4>Errors</h4>
                      <p>{reviewResult.diagnostics.errors.join(', ') || '-'}</p>
                    </div>
                    <div>
                      <h4>Insertion Hint</h4>
                      <p>{reviewResult.preview.scenario_config_insertion_hint || '-'}</p>
                    </div>
                  </div>
                  <div className="draftPreviewGrid">
                    <div className="draftPreviewFullWidth">
                      <h4>Diff Preview</h4>
                      <pre>{reviewResult.preview.diff_preview || '-'}</pre>
                    </div>
                  </div>

                  {applyResult && (
                    <div className="draftApplyPanel">
                      <h3>Apply Result</h3>
                      <div className="probeDraftActions">
                        <button onClick={smokeDraft} disabled={running || smokingDraft || applyResult.apply_status !== 'applied' || !applyResult.applied.scenario_id}>
                          {smokingDraft ? 'Starting Smoke...' : 'Smoke Draft'}
                        </button>
                        <button onClick={removeAppliedDraft} disabled={running || removingAppliedDraft || applyResult.apply_status !== 'applied' || !applyResult.applied.scenario_id}>
                          {removingAppliedDraft ? 'Removing...' : 'Remove Applied Draft'}
                        </button>
                      </div>
                      <div className="probeSummaryGrid">
                        <div>
                          <span>Apply Status</span>
                          <strong>{applyResult.apply_status}</strong>
                        </div>
                        <div>
                          <span>Scenario ID</span>
                          <strong>{applyResult.applied.scenario_id || '-'}</strong>
                        </div>
                        <div>
                          <span>Runtime Key</span>
                          <strong>{applyResult.applied.runtime_config_key || '-'}</strong>
                        </div>
                        <div>
                          <span>Backup Created</span>
                          <strong>{applyResult.backup.created ? 'Yes' : 'No'}</strong>
                        </div>
                      </div>
                      <div className="probeSeedGrid">
                        <div>
                          <h4>Changed Files</h4>
                          <p>{applyResult.changed_files.join(', ') || '-'}</p>
                        </div>
                        <div>
                          <h4>Backup Paths</h4>
                          <p>{applyResult.backup.paths.join(', ') || '-'}</p>
                        </div>
                        <div>
                          <h4>Warnings</h4>
                          <p>{applyResult.diagnostics.warnings.join(', ') || '-'}</p>
                        </div>
                        <div>
                          <h4>Errors</h4>
                          <p>{applyResult.diagnostics.errors.join(', ') || '-'}</p>
                        </div>
                      </div>

                      {smokeResult && (
                        <div className="draftSmokePanel">
                          <h3>Smoke Result</h3>
                          <div className="probeDraftActions">
                            <button onClick={refreshSmokeResult} disabled={running || refreshingSmoke || !smokeResult.run_id}>
                              {refreshingSmoke ? 'Refreshing Smoke...' : 'Refresh Smoke Result'}
                            </button>
                          </div>
                          <div className="probeSummaryGrid">
                            <div>
                              <span>Smoke Status</span>
                              <strong>{smokeStatusResult?.smoke_status ?? smokeResult.smoke_status}</strong>
                            </div>
                            <div>
                              <span>Run ID</span>
                              <strong>{smokeResult.run_id || '-'}</strong>
                            </div>
                            <div>
                              <span>Scenario ID</span>
                              <strong>{smokeResult.scenario_id || '-'}</strong>
                            </div>
                            <div>
                              <span>Max Steps</span>
                              <strong>{smokeResult.max_steps}</strong>
                            </div>
                          </div>
                          {smokeStatusResult && (
                            <div className="probeSummaryGrid">
                              <div>
                                <span>Run Status</span>
                                <strong>{smokeStatusResult.run_status}</strong>
                              </div>
                              <div>
                                <span>Result Status</span>
                                <strong>{smokeStatusResult.summary.result_status}</strong>
                              </div>
                              <div>
                                <span>Log Link</span>
                                <strong>
                                  {smokeStatusResult.artifacts.display_urls.log ? (
                                    <a href={smokeStatusResult.artifacts.display_urls.log}>Log</a>
                                  ) : (
                                    '-'
                                  )}
                                </strong>
                              </div>
                              <div>
                                <span>XLSX Link</span>
                                <strong>
                                  {smokeStatusResult.artifacts.display_urls.xlsx ? (
                                    <a href={smokeStatusResult.artifacts.display_urls.xlsx}>XLSX</a>
                                  ) : (
                                    '-'
                                  )}
                                </strong>
                              </div>
                            </div>
                          )}
                          <div className="probeSeedGrid">
                            <div>
                              <h4>Pre-navigation Success</h4>
                              <p>{(smokeStatusResult?.summary ?? smokeResult.summary).pre_navigation_success ? 'Yes' : 'No'}</p>
                            </div>
                            <div>
                              <h4>Plugin Open Verified</h4>
                              <p>{(smokeStatusResult?.summary ?? smokeResult.summary).plugin_open_verified ? 'Yes' : 'No'}</p>
                            </div>
                            <div>
                              <h4>Steps Collected</h4>
                              <p>{(smokeStatusResult?.summary ?? smokeResult.summary).steps_collected}</p>
                            </div>
                            <div>
                              <h4>Failure Reason</h4>
                              <p>{(smokeStatusResult?.summary ?? smokeResult.summary).failure_reason || '-'}</p>
                            </div>
                            <div>
                              <h4>Artifacts</h4>
                              <p>
                                {[
                                  smokeStatusResult?.artifacts.log_path ?? smokeResult.artifacts.log_path,
                                  smokeStatusResult?.artifacts.xlsx_path ?? smokeResult.artifacts.xlsx_path,
                                  smokeStatusResult?.artifacts.summary_json_path,
                                ]
                                  .filter(Boolean)
                                  .join(', ') || '-'}
                              </p>
                            </div>
                            <div>
                              <h4>Warnings / Errors</h4>
                              <p>
                                {[
                                  ...((smokeStatusResult?.diagnostics.warnings ?? smokeResult.diagnostics.warnings) || []),
                                  ...(smokeStatusResult?.diagnostics.errors ?? []),
                                ].join(', ') || '-'}
                              </p>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
