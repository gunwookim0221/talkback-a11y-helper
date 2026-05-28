import type { Scenario } from './api';

export type ScenarioPresetId =
  | 'global_nav_smoke'
  | 'life_smoke'
  | 'device_smoke'
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
    id: 'global_nav_smoke',
    label: 'Global Nav Smoke',
    description: 'global_nav_main quick sanity check',
    scenarioIds: ['global_nav_main'],
  },
  {
    id: 'life_smoke',
    label: 'Life Smoke',
    description: 'life plugin smoke set',
    scenarioIds: [
      'life_air_care_plugin',
      'life_home_care_plugin',
      'life_family_care_plugin',
      'life_clothing_care_plugin',
    ],
  },
  {
    id: 'device_smoke',
    label: 'Device Smoke',
    description: 'device plugin smoke set',
    scenarioIds: [
      'device_smoke_sensor_plugin',
      'device_water_leak_sensor_plugin',
      'device_door_lock_plugin',
      'device_tv_plugin',
    ],
  },
  {
    id: 'select_all',
    label: 'Select All Scenarios',
    description: 'select every available scenario',
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

  const available = new Set(scenarios.map((scenario) => scenario.id));
  const preset = PRESETS.find((item) => item.id === presetId);
  if (!preset) {
    return new Set(currentSelected);
  }
  return new Set(preset.scenarioIds.filter((scenarioId) => available.has(scenarioId)));
}
