import { useEffect, useState } from 'react';
import type { MismatchSummary, QualityIssue, RecentBatch, RecentRun } from '../api';
import { api } from '../api';
import {
  evidenceText,
  getBatchReviewProjection,
  getReviewProjection,
  reviewReason,
  reviewScenarioName,
  reviewStatus,
} from '../reviewPresentation';

export type ReviewRequiredPanelProps = {
  readonly run: RecentRun | null;
  readonly batchId?: string | null;
};

function ReviewEvidence({ item }: { item: QualityIssue }) {
  const [imageUnavailable, setImageUnavailable] = useState(false);
  const imageUrl = item.crop_path
    ? `/api/batch/file?path=${encodeURIComponent(item.crop_path)}`
    : null;

  return (
    <div className="reviewEvidence">
      <div className="reviewEvidenceFields">
        <div>
          <dt>Visible text</dt>
          <dd>{evidenceText(item.visible_label, 'visible')}</dd>
        </div>
        <div>
          <dt>TalkBack speech</dt>
          <dd>{evidenceText(item.merged_announcement, 'speech')}</dd>
        </div>
      </div>
      {imageUrl && !imageUnavailable ? (
        <a className="reviewScreenshot" href={imageUrl} target="_blank" rel="noreferrer">
          <img
            src={imageUrl}
            alt={`${reviewScenarioName(item)} screenshot evidence`}
            loading="lazy"
            onError={() => setImageUnavailable(true)}
          />
        </a>
      ) : (
        <div className="reviewScreenshotMissing" role="status">스크린샷 없음</div>
      )}
    </div>
  );
}

function ReviewCard({ item, index, total }: { item: QualityIssue; index: number; total: number; key?: string }) {
  return (
    <article className="reviewRequiredCard" aria-labelledby={`review-item-${index}`}>
      <header className="reviewRequiredCardHeader">
        <div>
          <h3 id={`review-item-${index}`}>{reviewScenarioName(item)}</h3>
          <p>Step {item.step || '-'}</p>
        </div>
        <span className="reviewItemCounter" aria-label={`Review item ${index + 1} of ${total}`}>
          {index + 1} / {total}
        </span>
      </header>

      <ReviewEvidence item={item} />

      <dl className="reviewRequiredSummary">
        <dt>Reason</dt>
        <dd>{reviewReason(item)}</dd>
        <dt>Status</dt>
        <dd>{reviewStatus(item)}</dd>
      </dl>

      <button
        type="button"
        className="reviewActionButton"
        disabled
        title="Reviewer decision persistence is not available in the current contract."
      >
        검토하기 (읽기 전용)
      </button>

      <details className="reviewTechnicalDetails">
        <summary>Technical evidence</summary>
        <dl>
          <dt>Scenario ID</dt>
          <dd>{item.scenario_id || '-'}</dd>
          <dt>Raw final result</dt>
          <dd>{item.raw_final_result || item.final_result || '-'}</dd>
          <dt>Mismatch type</dt>
          <dd>{item.mismatch_type || '-'}</dd>
          <dt>Shadow verdict</dt>
          <dd>{item.shadow_verdict || '-'}</dd>
          <dt>Evidence path</dt>
          <dd>{item.crop_path || '스크린샷 없음'}</dd>
        </dl>
      </details>
    </article>
  );
}

export function ReviewRequiredPanel({ run, batchId = null }: ReviewRequiredPanelProps) {
  const [payload, setPayload] = useState<MismatchSummary | null>(null);
  const [batch, setBatch] = useState<RecentBatch | null>(null);
  const [loading, setLoading] = useState(false);
  const [requestError, setRequestError] = useState(false);

  useEffect(() => {
    let ignore = false;
    if (batchId) {
      setPayload(null);
      setBatch(null);
      setLoading(true);
      setRequestError(false);
      api.recentBatches()
        .then((batches) => {
          if (!ignore) setBatch(batches.find((candidate) => candidate.batch_id === batchId) ?? null);
        })
        .catch(() => {
          if (!ignore) {
            setBatch(null);
            setRequestError(true);
          }
        })
        .finally(() => {
          if (!ignore) setLoading(false);
        });
      return () => {
        ignore = true;
      };
    }

    if (!run?.run_id || !run.xlsx_exists) {
      setPayload(null);
      setBatch(null);
      setLoading(false);
      setRequestError(false);
      return () => {
        ignore = true;
      };
    }

    setLoading(true);
    setRequestError(false);
    api.runMismatch(run.run_id)
      .then((nextPayload) => {
        if (!ignore) setPayload(nextPayload);
      })
      .catch(() => {
        if (!ignore) {
          setPayload(null);
          setRequestError(true);
        }
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [batchId, run?.run_id, run?.xlsx_exists]);

  const projection = batchId ? getBatchReviewProjection(batch) : getReviewProjection(payload);
  const items = projection.items;
  const title = projection.qaReviewCount > 0 ? `검토 필요 ${projection.qaReviewCount}건` : '검토 필요';

  return (
    <section className="panel reviewRequiredPanel" aria-labelledby="review-required-title">
      <header className="reviewRequiredHeader">
        <div>
          <h2 id="review-required-title">{title}</h2>
          <p>발화 또는 화면 정보 확인이 필요한 항목입니다.</p>
        </div>
        {run && <small>Latest completed run: {run.run_id}</small>}
        {batchId && <small>Selected batch: {batchId}</small>}
      </header>

      {!run && !batchId ? (
        <p className="reviewEmptyState">완료된 실행이 없어 검토 항목을 표시할 수 없습니다.</p>
      ) : loading ? (
        <p className="reviewEmptyState" role="status">검토 항목을 불러오는 중입니다…</p>
      ) : requestError || !projection.available ? (
        <div className="reviewUnavailable" role="status">
          <strong>검토 상태 확인 불가</strong>
          <p>{requestError ? '이 실행의 QA Review projection을 불러오지 못했습니다.' : projection.reason}</p>
          <small>기술 원본은 Run History의 Technical details에서 확인할 수 있습니다.</small>
        </div>
      ) : items.length === 0 && projection.qaReviewCount === 0 ? (
        <p className="reviewEmptyState">검토할 항목이 없습니다.</p>
      ) : items.length === 0 ? (
        <div className="reviewUnavailable" role="status">
          <strong>검토 항목 상세를 확인할 수 없습니다.</strong>
          <p>QA Review {projection.qaReviewCount}건이 기록되었지만 상세 evidence가 제공되지 않았습니다.</p>
        </div>
      ) : (
        <>
          <p className="reviewCountExplanation">QA Review {projection.qaReviewCount}건 · Automation Diagnostics는 이 수에 포함하지 않습니다.</p>
          <div className="reviewRequiredList">
            {items.map((item, index) => (
              <ReviewCard key={`${item.scenario_id}-${item.step}-${item.crop_path || index}`} item={item} index={index} total={items.length} />
            ))}
          </div>
        </>
      )}

    </section>
  );
}
