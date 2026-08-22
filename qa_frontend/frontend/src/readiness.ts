import type { DeviceInfo } from './api';

export type TalkBackReadinessState = 'enabled' | 'disabled' | 'unknown';

export type TalkBackReadinessProjectionInput = {
  selectedDevices: readonly Pick<DeviceInfo, 'talkback_enabled'>[];
  deviceReadinessLoaded: boolean;
  runScopedState?: string | null;
};

/**
 * Project the user-facing TalkBack state from the validator's selected devices.
 * Device readiness is authoritative once the device list has loaded. The
 * run-scoped value is only an initial fallback while that list is unavailable.
 */
export function projectTalkBackReadiness({
  selectedDevices,
  deviceReadinessLoaded,
  runScopedState,
}: TalkBackReadinessProjectionInput): TalkBackReadinessState {
  if (deviceReadinessLoaded) {
    if (selectedDevices.length === 0) return 'unknown';
    if (selectedDevices.some((device) => device.talkback_enabled === false)) return 'disabled';
    if (selectedDevices.some((device) => device.talkback_enabled !== true)) return 'unknown';
    return 'enabled';
  }

  if (runScopedState === 'enabled' || runScopedState === 'disabled') {
    return runScopedState;
  }
  return 'unknown';
}
