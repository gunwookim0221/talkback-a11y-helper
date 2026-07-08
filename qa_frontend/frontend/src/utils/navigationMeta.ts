export function getNavigationName(scenarioId: string): string | null {
  const mapping: Record<string, string> = {
    'home_main': 'Home',
    'home_safe_plugin': 'Safe',
    'devices_main': 'Devices',
    'life_main': 'Life',
    'routines_main': 'Routines',
    'menu_main': 'Menu',
    'global_nav_main': 'Global Navigation',
    'settings_entry_example': 'Settings Entry',
  };

  return mapping[scenarioId] || null;
}

export function isOptionalNavigationScenario(scenarioId: string): boolean {
  return scenarioId === 'home_safe_plugin';
}
