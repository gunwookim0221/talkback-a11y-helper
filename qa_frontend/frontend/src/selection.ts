import type { Scenario } from './api';

export const DEFAULT_SCENARIO_ID = 'global_nav_main';

export function getFullValidationScenarioIds(scenarios: readonly Scenario[]): string[] {
  return scenarios.filter((scenario) => scenario.enabled).map((scenario) => scenario.id);
}

export function initialScenarioSelection(scenarios: readonly Scenario[]): Set<string> {
  return new Set(getFullValidationScenarioIds(scenarios));
}

export function isFullValidationSelection(
  selectedScenarioIds: ReadonlySet<string>,
  fullValidationScenarioIds: readonly string[],
): boolean {
  return (
    fullValidationScenarioIds.length > 0 &&
    selectedScenarioIds.size === fullValidationScenarioIds.length &&
    fullValidationScenarioIds.every((scenarioId) => selectedScenarioIds.has(scenarioId))
  );
}
