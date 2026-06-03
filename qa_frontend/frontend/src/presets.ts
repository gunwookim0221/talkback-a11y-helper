import type { Scenario } from './api';

export type ScenarioPresetId =
  | 'global'
  | 'life'
  | 'device'
  | 'all_plugins'
  | 'select_all'
  | 'clear_all';

type ScenarioPreset = {
  id: ScenarioPresetId;
  label: string;
  description: string;
  scenarioIds: string[];
};

export const PRESETS: ScenarioPreset[] = [
  {
    id: 'global',
    label: 'Navigation',
    description: 'select all navigation scenarios',
    scenarioIds: [],
  },
  {
    id: 'life',
    label: 'Life Plugins',
    description: 'select all life plugin scenarios',
    scenarioIds: [],
  },
  {
    id: 'device',
    label: 'Device Plugins',
    description: 'select all device plugin scenarios',
    scenarioIds: [],
  },
  {
    id: 'all_plugins',
    label: 'All Plugins',
    description: 'select device and life plugin scenarios only',
    scenarioIds: [],
  },
  {
    id: 'select_all',
    label: 'All Scenarios',
    description: 'select navigation, main, and plugin scenarios',
    scenarioIds: [],
  },
  {
    id: 'clear_all',
    label: 'Clear All',
    description: 'clear every scenario checkbox',
    scenarioIds: [],
  },
];

export function applyPresetSelection(presetId: ScenarioPresetId, scenarios: Scenario[], currentSelected: Set<string>): Set<string> {
  if (presetId === 'clear_all') {
    return new Set();
  }
  if (presetId === 'select_all') {
    return new Set(scenarios.map((scenario) => scenario.id));
  }
  if (presetId === 'all_plugins') {
    return new Set(
      scenarios
        .filter((scenario) => {
          const id = scenario.id;
          return id.startsWith('device_') || (id.startsWith('life_') && id.endsWith('_plugin'));
        })
        .map((scenario) => scenario.id)
    );
  }

  const newSelection = new Set<string>();

  if (presetId === 'global') {
    for (const scenario of scenarios) {
      if (
        scenario.id.startsWith('global_') || 
        scenario.id.startsWith('settings_') ||
        scenario.id.startsWith('home_') ||
        scenario.id.startsWith('devices_')
      ) {
        newSelection.add(scenario.id);
      }
    }
    return newSelection;
  }
  
  if (presetId === 'life') {
    for (const scenario of scenarios) {
      if (scenario.id.startsWith('life_')) {
        newSelection.add(scenario.id);
      }
    }
    return newSelection;
  }
  
  if (presetId === 'device') {
    for (const scenario of scenarios) {
      if (scenario.id.startsWith('device_')) {
        newSelection.add(scenario.id);
      }
    }
    return newSelection;
  }

  const available = new Set(scenarios.map((scenario) => scenario.id));
  const preset = PRESETS.find((item) => item.id === presetId);
  if (!preset) {
    return new Set(currentSelected);
  }
  return new Set(preset.scenarioIds.filter((scenarioId) => available.has(scenarioId)));
}
