import { isFullValidationSelection } from './selection';

export type RunProfileId = 'full-validation' | 'quick-smoke' | 'custom-debug';

export type RunProfileSettings = {
  launchMode: 'warm' | 'clean';
  plannedMode: 'smoke' | 'full';
  enableCoverageProbe: boolean;
  shadowValidation: boolean;
  evidenceLedger: boolean;
  identityShadowV2: boolean;
  traversalIdentityV2: boolean;
  traversalProfiler: boolean;
};

export const RUN_PROFILES: Record<Exclude<RunProfileId, 'custom-debug'>, RunProfileSettings> = {
  'full-validation': {
    launchMode: 'clean',
    plannedMode: 'full',
    enableCoverageProbe: true,
    shadowValidation: false,
    evidenceLedger: true,
    identityShadowV2: true,
    traversalIdentityV2: true,
    traversalProfiler: true,
  },
  'quick-smoke': {
    launchMode: 'clean',
    plannedMode: 'smoke',
    enableCoverageProbe: false,
    shadowValidation: false,
    evidenceLedger: true,
    identityShadowV2: true,
    traversalIdentityV2: true,
    traversalProfiler: true,
  },
};

export function resolveRunProfile(
  profile: RunProfileId,
  current: RunProfileSettings,
): RunProfileSettings {
  return profile === 'custom-debug' ? current : RUN_PROFILES[profile];
}

export type ValidationReadinessInput = RunProfileSettings & {
  selectedScenarioCount: number;
  fullValidationScenarioCount: number;
};

export type ValidationReadiness = {
  ready: boolean;
  reasons: string[];
};

export function getValidationReadiness(input: ValidationReadinessInput): ValidationReadiness {
  const reasons: string[] = [];
  if (input.plannedMode !== 'full') reasons.push('Mode is Smoke');
  if (
    input.fullValidationScenarioCount === 0 ||
    input.selectedScenarioCount !== input.fullValidationScenarioCount
  ) {
    reasons.push('Full scenario set not selected');
  }
  if (!input.enableCoverageProbe) reasons.push('Coverage disabled');
  if (!input.evidenceLedger) reasons.push('Evidence Ledger disabled');
  if (!input.traversalProfiler) reasons.push('Runtime Profiler disabled');
  if (!input.identityShadowV2) reasons.push('Identity disabled');
  if (!input.traversalIdentityV2) reasons.push('Traversal Engine disabled');
  return { ready: reasons.length === 0, reasons };
}

export type ScenarioRunKind = 'full-validation' | 'custom';

export type RunSafetyInput = {
  selectedScenarioIds: ReadonlySet<string>;
  fullValidationScenarioIds: readonly string[];
  selectedDeviceCount: number;
  selectedReadyDeviceCount: number;
  controlsLocked: boolean;
  helperReady: boolean | null;
  talkbackEnabled: boolean | null;
};

export type RunSafety = {
  ready: boolean;
  runKind: ScenarioRunKind;
  reasons: string[];
};

export function getRunSafety(input: RunSafetyInput): RunSafety {
  const reasons: string[] = [];
  const runKind = isFullValidationSelection(input.selectedScenarioIds, input.fullValidationScenarioIds)
    ? 'full-validation'
    : 'custom';

  if (input.selectedScenarioIds.size === 0) reasons.push('Select at least one scenario');
  if (input.selectedDeviceCount === 0) {
    reasons.push('Select at least one ready device');
  } else if (input.selectedReadyDeviceCount !== input.selectedDeviceCount) {
    reasons.push('Selected device is not ready');
  }
  if (input.helperReady === false) reasons.push('Helper is not ready');
  if (input.talkbackEnabled === false) reasons.push('TalkBack is not enabled');
  if (input.controlsLocked) reasons.push('A run is already active');

  return { ready: reasons.length === 0, runKind, reasons };
}

export function currentLanguageLabel(deviceLocale: string | null | undefined): string {
  const locale = String(deviceLocale ?? '').trim();
  return locale && locale !== '-' ? `Current (${locale})` : 'Current';
}
