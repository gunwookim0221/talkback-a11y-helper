import { Scenario } from '../api';

export interface ScenarioGroup {
  title: string;
  scenarios: Scenario[];
}

export function groupScenarios(scenarios: Scenario[]): ScenarioGroup[] {
  const groups: Record<string, Scenario[]> = {
    Navigation: [],
    'Life Plugins': [],
    'Device Plugins': [],
  };

  for (const scenario of scenarios) {
    if (
      scenario.id.startsWith('global_') || 
      scenario.id.startsWith('settings_') || 
      scenario.id.startsWith('home_') || 
      scenario.id.startsWith('devices_')
    ) {
      groups['Navigation'].push(scenario);
    } else if (scenario.id.startsWith('life_')) {
      groups['Life Plugins'].push(scenario);
    } else if (scenario.id.startsWith('device_')) {
      groups['Device Plugins'].push(scenario);
    }
  }

  return [
    { title: 'Navigation', scenarios: groups['Navigation'] },
    { title: 'Life Plugins', scenarios: groups['Life Plugins'] },
    { title: 'Device Plugins', scenarios: groups['Device Plugins'] },
  ].filter((group) => group.scenarios.length > 0);
}
