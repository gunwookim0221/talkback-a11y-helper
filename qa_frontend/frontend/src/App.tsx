import { useEffect, useMemo, useState } from 'react';
import { api, OutputFile, RunStatus, Scenario } from './api';

function formatTime(value: number) {
  return new Date(value * 1000).toLocaleString();
}

export default function App() {
  const [adb, setAdb] = useState<Record<string, unknown> | null>(null);
  const [helper, setHelper] = useState<Record<string, unknown> | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [log, setLog] = useState('');
  const [outputs, setOutputs] = useState<OutputFile[]>([]);
  const [error, setError] = useState('');

  const running = status?.state === 'running';
  const enabledCount = useMemo(() => scenarios.filter((scenario) => scenario.enabled).length, [scenarios]);

  async function refreshStatic() {
    const [adbStatus, helperStatus, scenarioResponse, outputResponse] = await Promise.all([
      api.adbStatus(),
      api.helperStatus(),
      api.scenarios(),
      api.outputs(),
    ]);
    setAdb(adbStatus);
    setHelper(helperStatus);
    setScenarios(scenarioResponse.scenarios);
    setSelected(new Set(scenarioResponse.scenarios.filter((scenario) => scenario.enabled).map((scenario) => scenario.id)));
    setOutputs(outputResponse.outputs);
  }

  async function refreshRun() {
    const [runStatus, runLog, outputResponse] = await Promise.all([api.runStatus(), api.runLog(), api.outputs()]);
    setStatus(runStatus);
    setLog(runLog.text);
    setOutputs(outputResponse.outputs);
  }

  useEffect(() => {
    refreshStatic().then(refreshRun).catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      refreshRun().catch((err) => setError(String(err)));
    }, 1500);
    return () => window.clearInterval(id);
  }, []);

  async function start(mode: 'smoke' | 'full') {
    setError('');
    try {
      setStatus(await api.startRun(mode, Array.from(selected)));
      await refreshRun();
    } catch (err) {
      setError(String(err));
    }
  }

  async function stop() {
    setError('');
    try {
      setStatus(await api.stopRun());
      await refreshRun();
    } catch (err) {
      setError(String(err));
    }
  }

  async function installHelper() {
    setError('');
    try {
      setHelper(await api.installHelper());
      setHelper(await api.helperStatus());
    } catch (err) {
      setError(String(err));
    }
  }

  function toggleScenario(id: string) {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>TalkBack QA Control Panel</h1>
          <p>Current Phase 1 runs use the existing runtime_config.json without rewriting it.</p>
        </div>
        <div className={`state state-${status?.state ?? 'idle'}`}>{status?.state ?? 'idle'}</div>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="grid">
        <article className="panel">
          <h2>ADB</h2>
          <div className="metric">{String(adb?.status ?? 'unknown')}</div>
          <pre>{JSON.stringify(adb?.devices ?? [], null, 2)}</pre>
        </article>

        <article className="panel">
          <h2>Helper</h2>
          <div className="metric">{helper?.enabled ? 'enabled' : String(helper?.status ?? 'unknown')}</div>
          <button onClick={installHelper} disabled={running}>Install APK</button>
        </article>

        <article className="panel controls">
          <h2>Run</h2>
          <div className="buttonRow">
            <button onClick={() => start('smoke')} disabled={running}>Smoke</button>
            <button onClick={() => start('full')} disabled={running}>Full</button>
            <button className="danger" onClick={stop} disabled={!running}>Stop</button>
          </div>
          <dl>
            <dt>Run ID</dt>
            <dd>{status?.run_id ?? '-'}</dd>
            <dt>Mode</dt>
            <dd>{status?.mode ?? '-'}</dd>
            <dt>Return</dt>
            <dd>{status?.returncode ?? '-'}</dd>
          </dl>
        </article>
      </section>

      <section className="split">
        <article className="panel scenarios">
          <h2>Scenarios</h2>
          <p>{enabledCount} enabled in runtime_config.json. Checkbox selection is sent to the backend but not applied in Phase 1.</p>
          <div className="scenarioList">
            {scenarios.map((scenario) => (
              <label key={scenario.id}>
                <input
                  type="checkbox"
                  checked={selected.has(scenario.id)}
                  onChange={() => toggleScenario(scenario.id)}
                  disabled={running}
                />
                <span>{scenario.id}</span>
                <small>{scenario.max_steps ? `${scenario.max_steps} steps` : 'steps n/a'}</small>
              </label>
            ))}
          </div>
        </article>

        <article className="panel">
          <h2>Outputs</h2>
          <div className="outputList">
            {outputs.map((file) => (
              <a key={file.filename} href={`/api/outputs/${encodeURIComponent(file.filename)}`}>
                <span>{file.filename}</span>
                <small>{Math.round(file.size / 1024)} KB · {formatTime(file.modified)}</small>
              </a>
            ))}
          </div>
        </article>
      </section>

      <section className="panel logPanel">
        <h2>Log Tail</h2>
        <pre>{log || 'No log yet.'}</pre>
      </section>
    </main>
  );
}
