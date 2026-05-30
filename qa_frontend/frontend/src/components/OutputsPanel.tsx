import React from 'react';
import { OutputFile, RecentRun } from '../api';

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString();
}

export interface OutputsPanelProps {
  outputs: OutputFile[];
  currentRunSummary: RecentRun | null;
  currentRunReadyForDownload: boolean;
}

export function OutputsPanel({ outputs, currentRunSummary, currentRunReadyForDownload }: OutputsPanelProps) {
  return (
    <article className="panel">
      <h2>Outputs</h2>
      <div className="downloadActions">
        <a
          className={`downloadButton ${!currentRunSummary?.xlsx_exists ? 'disabled' : ''}`}
          href={currentRunSummary?.xlsx_exists ? `/api/outputs/${encodeURIComponent(currentRunSummary.xlsx_filename ?? '')}` : undefined}
          aria-disabled={!currentRunSummary?.xlsx_exists}
        >
          Download XLSX
        </a>
        <a
          className={`downloadButton ${!currentRunReadyForDownload ? 'disabled' : ''}`}
          href={currentRunReadyForDownload ? '/api/run/log/download' : undefined}
          aria-disabled={!currentRunReadyForDownload}
        >
          Download Log
        </a>
      </div>
      {currentRunSummary && (
        <p className="scenarioHint">
          Current run downloads: {currentRunSummary.xlsx_filename ?? 'xlsx pending'} · {currentRunSummary.log_filename ?? 'log pending'}
        </p>
      )}
      <div className="outputList">
        {outputs.map((file) => (
          <a key={file.filename} href={`/api/outputs/${encodeURIComponent(file.filename)}`}>
            <span>{file.filename}</span>
            <small>{Math.round(file.size / 1024)} KB · {formatTime(file.modified)}</small>
          </a>
        ))}
      </div>
    </article>
  );
}
