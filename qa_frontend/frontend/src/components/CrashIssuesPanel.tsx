import React, { useEffect, useState } from 'react';
import { api, CrashDetail, CrashItem, CrashSummary } from '../api';

type CrashIssuesPanelProps = {
  runId: string;
  deviceId: string;
};

function recoveryClass(result: string | null | undefined) {
  if (result === 'CRASH_RECOVERED') {
    return 'healthOk';
  }
  if (result === 'CRASH_REPEATED') {
    return 'healthBad';
  }
  return 'healthWarn';
}

function crashTypeClass(crashType: string | null | undefined) {
  if (crashType === 'CONFIRMED_CRASH') {
    return 'healthBad';
  }
  if (crashType === 'APP_TERMINATED' || crashType === 'POSSIBLE_CRASH') {
    return 'healthWarn';
  }
  return 'healthNeutral';
}

function formatCrashTime(timestamp: string | null) {
  if (!timestamp) {
    return '-';
  }
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return date.toLocaleString();
}

function ArtifactBadge({ label, exists }: { label: string; exists: boolean }) {
  return (
    <span className={`crashArtifactBadge ${exists ? 'available' : 'missing'}`}>
      {label}
    </span>
  );
}

type ArtifactModal =
  | { type: 'repro'; title: string; body: string | null; loading: boolean; error: string | null }
  | { type: 'screenshot'; title: string; imageUrl: string | null; error: string | null };

function CrashIssueCard({
  crash,
  onViewRepro,
  onViewScreenshot,
  onDownload,
}: {
  crash: CrashItem;
  onViewRepro: (crash: CrashItem) => void;
  onViewScreenshot: (crash: CrashItem) => void;
  onDownload: (crash: CrashItem) => void;
}) {
  return (
    <div className="crashIssueCard">
      <div className="crashIssueHeader">
        <strong>{crash.crash_event_id}</strong>
        <div className="crashIssueBadges">
          <span className={`statusBadge ${crashTypeClass(crash.crash_type)}`}>{crash.crash_type || 'UNKNOWN'}</span>
          <span className={`statusBadge ${recoveryClass(crash.recovery_result)}`}>
            {crash.recovery_result || 'unknown'}
          </span>
        </div>
      </div>
      <dl className="crashIssueMeta">
        <dt>Scenario</dt>
        <dd>{crash.scenario || '-'}</dd>
        <dt>Timestamp</dt>
        <dd>{formatCrashTime(crash.timestamp)}</dd>
      </dl>
      <div className="crashArtifactList" aria-label="Crash artifact availability">
        <ArtifactBadge label="Repro Guide" exists={crash.repro_guide_exists} />
        <ArtifactBadge label="Screenshot" exists={crash.screenshot_exists} />
        <ArtifactBadge label="Helper Dump" exists={crash.helper_dump_exists} />
        <ArtifactBadge label="Window Dump" exists={crash.window_dump_exists} />
      </div>
      <div className="crashArtifactActions">
        <button type="button" onClick={() => onViewRepro(crash)} disabled={!crash.repro_guide_exists}>
          View Repro Guide
        </button>
        <button type="button" onClick={() => onViewScreenshot(crash)} disabled={!crash.screenshot_exists}>
          View Screenshot
        </button>
        <button type="button" onClick={() => onDownload(crash)}>
          Download Artifacts
        </button>
      </div>
    </div>
  );
}

export function CrashIssuesPanel({ runId, deviceId }: CrashIssuesPanelProps) {
  const [summary, setSummary] = useState<CrashSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ArtifactModal | null>(null);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError(null);
    setSummary(null);

    api.getRunDeviceCrashes(runId, deviceId)
      .then(data => {
        if (!ignore) {
          setSummary(data);
        }
      })
      .catch(() => {
        if (!ignore) {
          setError('Crash summary unavailable');
        }
      })
      .finally(() => {
        if (!ignore) {
          setLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [runId, deviceId]);

  const loadCrashDetail = (crash: CrashItem) => {
    setModal({
      type: 'repro',
      title: `${crash.crash_event_id} Repro Guide`,
      body: null,
      loading: true,
      error: null,
    });
    api.getRunDeviceCrash(runId, deviceId, crash.crash_event_id)
      .then((detail: CrashDetail) => {
        setModal({
          type: 'repro',
          title: `${detail.crash_event_id} Repro Guide`,
          body: detail.repro_guide,
          loading: false,
          error: detail.repro_guide ? null : 'Repro guide unavailable',
        });
      })
      .catch(() => {
        setModal({
          type: 'repro',
          title: `${crash.crash_event_id} Repro Guide`,
          body: null,
          loading: false,
          error: 'Unable to load artifact',
        });
      });
  };

  const openScreenshot = (crash: CrashItem) => {
    setModal({
      type: 'screenshot',
      title: `${crash.crash_event_id} Screenshot`,
      imageUrl: api.getRunDeviceCrashScreenshotUrl(runId, deviceId, crash.crash_event_id),
      error: null,
    });
  };

  const downloadArtifacts = (crash: CrashItem) => {
    const link = document.createElement('a');
    link.href = api.getRunDeviceCrashDownloadUrl(runId, deviceId, crash.crash_event_id);
    link.download = `${crash.crash_event_id}_artifacts.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const crashCount = summary?.crash_count ?? 0;
  return (
    <details open className="crashIssuesPanel" style={{ marginTop: '16px' }}>
      <summary style={{ fontSize: '14px', fontWeight: 'bold' }}>
        Crash Issues{summary ? ` (${crashCount})` : ''}
      </summary>
      <div className="crashIssuesBody">
        {loading ? (
          <small>Loading crash summary...</small>
        ) : error ? (
          <small>{error}</small>
        ) : crashCount === 0 ? (
          <small>No crash issues detected.</small>
        ) : (
          <div className="crashIssueList">
            {summary?.crashes.map(crash => (
              <CrashIssueCard
                key={crash.crash_event_id}
                crash={crash}
                onViewRepro={loadCrashDetail}
                onViewScreenshot={openScreenshot}
                onDownload={downloadArtifacts}
              />
            ))}
          </div>
        )}
      </div>
      {modal && (
        <div className="artifactModalBackdrop" role="presentation" onClick={() => setModal(null)}>
          <div className="artifactModal" role="dialog" aria-modal="true" aria-label={modal.title} onClick={event => event.stopPropagation()}>
            <div className="artifactModalHeader">
              <strong>{modal.title}</strong>
              <button type="button" onClick={() => setModal(null)} aria-label="Close artifact viewer">
                Close
              </button>
            </div>
            {modal.type === 'repro' ? (
              modal.loading ? (
                <small>Loading artifact...</small>
              ) : modal.error ? (
                <div className="artifactModalError">{modal.error}</div>
              ) : (
                <pre className="artifactReproText">{modal.body}</pre>
              )
            ) : modal.error ? (
              <div className="artifactModalError">{modal.error}</div>
            ) : (
              <div className="artifactScreenshotFrame">
                <img
                  src={modal.imageUrl || ''}
                  alt="Crash screenshot"
                  onError={() => {
                    setModal(prev => (prev && prev.type === 'screenshot'
                      ? { ...prev, imageUrl: null, error: 'Screenshot unavailable' }
                      : prev));
                  }}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </details>
  );
}
