import { useState, useRef, useEffect, useCallback } from 'react';
import { api, BatchStatus, RunStatus, RuntimeDashboard } from '../api';

export interface UseRunPollingProps {
  onOutputsChanged: () => void;
  onRunFinished: () => void;
}

export function useRunPolling({ onOutputsChanged, onRunFinished }: UseRunPollingProps) {
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [dashboard, setDashboard] = useState<RuntimeDashboard | null>(null);
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);
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
    
    let snapshot: any = null;
    let currentLog = '';
    let batchStatusRef: any = null;
    try {
      snapshot = await api.runSnapshot();
      currentLog = snapshot.log_tail.text;
    } catch (e) {
      // ignore
    }

    try {
      const batchStatus = await api.getBatchStatus();
      batchStatusRef = batchStatus;
      setBatchStatus(batchStatus);
      if (batchStatus && batchStatus.state === 'running' && batchStatus.devices) {
        const runningDevice = batchStatus.devices.find((d: any) => d.state === 'running' || d.state === 'pending');
        if (runningDevice) {
           const basePath = runningDevice.output_dir?.replace(/\\/g, '/') || '';
           const targetPath = (runningDevice as any).runner_log_path?.replace(/\\/g, '/') || `${basePath}/runner.log`;
           const batchLog = await api.getBatchLogTail(targetPath);
           if (batchLog && batchLog.text) {
             currentLog = batchLog.text;
           } else {
             currentLog = "Waiting for batch log...";
           }
        }
      }
    } catch (e) {
      // ignore
    }

    if (snapshot) {
      let finalStatus = snapshot.status;
      let finalDashboard = snapshot.dashboard;
      let currentStateForEffect = snapshot.state;

      if (batchStatusRef && batchStatusRef.state && batchStatusRef.state !== 'idle') {
        const unifiedState = batchStatusRef.state === 'running' ? 'running' 
          : batchStatusRef.state === 'error' ? 'error' 
          : 'finished';
          
        finalStatus = {
          ...snapshot.status,
          state: unifiedState,
        };
        currentStateForEffect = unifiedState;
        
        if (unifiedState === 'running') {
          const currentDev = batchStatusRef.devices?.find((d: any) => d.state === 'running' || d.state === 'pending');
          finalDashboard = snapshot.dashboard;
        }
      }

      setStatus(finalStatus);
      setDashboard(finalDashboard);
      setLog(prev => {
        if (!currentLog && prev && prev !== "Waiting for batch log...") {
          return prev;
        }
        return currentLog;
      });

      if (snapshot.outputs_changed) {
        onOutputsChangedRef.current();
      }

      const previousState = lastStateRef.current;
      lastStateRef.current = currentStateForEffect;

      if (
        previousState === 'running' &&
        (currentStateForEffect === 'finished' || currentStateForEffect === 'stopped' || currentStateForEffect === 'error')
      ) {
        onRunFinishedRef.current();
      }
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

  const clearError = useCallback(() => {
    setError('');
  }, []);

  const reportError = useCallback((err: unknown) => {
    setError(String(err));
  }, []);

  return {
    status,
    dashboard,
    batchStatus,
    log,
    pollingLatencyMs,
    error,
    clearError,
    reportError,
    refreshRun,
  };
}
