import { Scenario } from '../api';

export interface ScenarioGroup {
  title: string;
  scenarios: Scenario[];
}

export function groupScenarios(scenarios: Scenario[]): ScenarioGroup[] {
  const groups: Record<string, Scenario[]> = {
    Global: [],
    'Life Plugins': [],
    'Device Plugins': [],
    Other: [],
  };

  for (const scenario of scenarios) {
    if (scenario.id.startsWith('global_') || scenario.id.startsWith('settings_')) {
      groups['Global'].push(scenario);
    } else if (scenario.id.startsWith('life_')) {
      groups['Life Plugins'].push(scenario);
    } else if (scenario.id.startsWith('device_')) {
      groups['Device Plugins'].push(scenario);
    } else {
      groups['Other'].push(scenario);
    }
  }

  return [
    { title: 'Global', scenarios: groups['Global'] },
    { title: 'Life Plugins', scenarios: groups['Life Plugins'] },
    { title: 'Device Plugins', scenarios: groups['Device Plugins'] },
    { title: 'Other', scenarios: groups['Other'] },
  ].filter((group) => group.scenarios.length > 0);
}
