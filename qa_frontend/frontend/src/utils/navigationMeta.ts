export function getNavigationName(scenarioId: string): string | null {
  const mapping: Record<string, string> = {
    'home_main': 'Home',
    'devices_main': 'Devices',
    'global_nav_main': 'Global Navigation',
    'settings_entry_example': 'Settings Entry',
  };

  return mapping[scenarioId] || null;
}
