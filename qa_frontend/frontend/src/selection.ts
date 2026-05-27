import type { Scenario } from './api';

export const DEFAULT_SCENARIO_ID = 'global_nav_main';

export function initialScenarioSelection(scenarios: Scenario[]): Set<string> {
  if (scenarios.some((scenario) => scenario.id === DEFAULT_SCENARIO_ID)) {
    return new Set([DEFAULT_SCENARIO_ID]);
  }
  return new Set();
}
