import type { Scenario } from './api';

export type ScenarioPresetId =
  | 'global_nav_smoke'
  | 'life_smoke'
  | 'device_smoke'
  | 'full_regression_selected'
  | 'clear_all';

type ScenarioPreset = {
  id: ScenarioPresetId;
  label: string;
  description: string;
  scenarioIds: string[];
  recommendedMode: 'smoke' | 'full';
};

export const PRESETS: ScenarioPreset[] = [
  {
    id: 'global_nav_smoke',
    label: 'Global Nav Smoke',
    description: 'global_nav_main quick sanity check',
    scenarioIds: ['global_nav_main'],
    recommendedMode: 'smoke',
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
    recommendedMode: 'smoke',
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
    recommendedMode: 'smoke',
  },
  {
    id: 'full_regression_selected',
    label: 'Full Regression Selected',
    description: 'keep current selection and recommend full mode',
    scenarioIds: [],
    recommendedMode: 'full',
  },
  {
    id: 'clear_all',
    label: 'Clear All',
    description: 'clear every scenario checkbox',
    scenarioIds: [],
    recommendedMode: 'smoke',
  },
];

export function applyPresetSelection(presetId: ScenarioPresetId, scenarios: Scenario[], currentSelected: Set<string>): Set<string> {
  if (presetId === 'full_regression_selected') {
    return new Set(currentSelected);
  }
  if (presetId === 'clear_all') {
    return new Set();
  }

  const available = new Set(scenarios.map((scenario) => scenario.id));
  const preset = PRESETS.find((item) => item.id === presetId);
  if (!preset) {
    return new Set(currentSelected);
  }
  return new Set(preset.scenarioIds.filter((scenarioId) => available.has(scenarioId)));
}
