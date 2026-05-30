import { useState, useRef, useEffect, useCallback } from 'react';
import { api, RunStatus, RuntimeDashboard } from '../api';

export interface UseRunPollingProps {
  onOutputsChanged: () => void;
  onRunFinished: () => void;
}

export function useRunPolling({ onOutputsChanged, onRunFinished }: UseRunPollingProps) {
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [dashboard, setDashboard] = useState<RuntimeDashboard | null>(null);
  const [log, setLog] = useState('');
  const [pollingLatencyMs, setPollingLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState('');

  const pollingRef = useRef(false);
  const lastStateRef = useRef<string | null>(null);

  const onOutputsChangedRef = useRef(onOutputsChanged);
  const onRunFinishedRef = useRef(onRunFinished);

  useEffect(() => {
    onOutputsChangedRef.current = onOutputsChanged;
  }, [onOutputsChanged]);

  useEffect(() => {
    onRunFinishedRef.current = onRunFinished;
  }, [onRunFinished]);

  const refreshRun = useCallback(async () => {
    const started = performance.now();
    
    const snapshot = await api.runSnapshot();

    setStatus(snapshot.status);
    setDashboard(snapshot.dashboard);
    setLog(snapshot.log_tail.text);

    if (snapshot.outputs_changed) {
      onOutputsChangedRef.current();
    }

    const previousState = lastStateRef.current;
    const currentState = snapshot.state;
    lastStateRef.current = currentState;

    if (
      previousState === 'running' &&
      (currentState === 'finished' || currentState === 'stopped' || currentState === 'error')
    ) {
      onRunFinishedRef.current();
    }

    setPollingLatencyMs(Math.round(performance.now() - started));
    setError('');
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (pollingRef.current) return;
      pollingRef.current = true;
      refreshRun()
        .catch((err) => setError(String(err)))
        .finally(() => {
          pollingRef.current = false;
        });
    }, 1500);
    return () => window.clearInterval(id);
  }, []);

  return {
    status,
    setStatus,
    dashboard,
    log,
    pollingLatencyMs,
    error,
    setError,
    refreshRun,
  };
}
