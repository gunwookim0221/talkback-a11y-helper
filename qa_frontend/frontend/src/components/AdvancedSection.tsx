import type { ReactNode } from 'react';

export function AdvancedSection({ children }: { children: ReactNode }) {
  return (
    <details className="panel advancedSection" aria-labelledby="advanced-title">
      <summary className="advancedSummary">
        <span>
          <h2 id="advanced-title">고급 기능</h2>
          <small>Plugin, 비교, 진단, 증거, 환경 및 개발자 도구</small>
        </span>
        <span className="advancedSummaryHint">필요할 때 열기</span>
      </summary>
      <div className="advancedContent">{children}</div>
    </details>
  );
}
