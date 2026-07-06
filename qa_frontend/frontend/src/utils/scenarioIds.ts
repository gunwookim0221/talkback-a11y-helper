export const NAVIGATION_SCENARIO_IDS = [
  'home_main',
  'devices_main',
  'life_main',
  'routines_main',
  'menu_main',
  'global_nav_main',
] as const;

export const NAVIGATION_SCENARIO_ID_SET = new Set<string>(NAVIGATION_SCENARIO_IDS);
