export type TerminalNotificationInput = {
  previousState: string | null;
  currentState: string | null;
  previousIdentity: string | null;
  currentIdentity: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  mountedAtMs: number;
};

export function isTerminalRunState(state: string | null | undefined): boolean {
  return ['finished', 'stopped', 'error'].includes(String(state ?? '').toLowerCase());
}

function timestampAtOrAfter(value: string | null | undefined, thresholdMs: number): boolean {
  if (!value) return false;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp >= thresholdMs;
}

export function shouldNotifyTerminalRefresh(input: TerminalNotificationInput): boolean {
  if (!isTerminalRunState(input.currentState) || !input.currentIdentity) return false;

  if (input.previousState === 'running') {
    if (input.previousIdentity === input.currentIdentity) return true;
    if (input.previousIdentity) return false;
  }

  return timestampAtOrAfter(input.startedAt, input.mountedAtMs)
    || timestampAtOrAfter(input.finishedAt, input.mountedAtMs);
}

export type TerminalObservation = Omit<TerminalNotificationInput, 'mountedAtMs'>;

export class TerminalNotificationTracker {
  private readonly notifiedIdentities = new Set<string>();

  constructor(private readonly mountedAtMs = Date.now()) {}

  shouldNotify(input: TerminalObservation): boolean {
    if (!isTerminalRunState(input.currentState) || !input.currentIdentity || this.notifiedIdentities.has(input.currentIdentity)) return false;
    const shouldNotify = shouldNotifyTerminalRefresh({ ...input, mountedAtMs: this.mountedAtMs });
    this.notifiedIdentities.add(input.currentIdentity);
    if (this.notifiedIdentities.size > 32) {
      const oldest = this.notifiedIdentities.values().next().value;
      if (oldest) this.notifiedIdentities.delete(oldest);
    }
    return shouldNotify;
  }
}
