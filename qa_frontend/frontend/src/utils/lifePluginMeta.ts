export function getLifePluginName(scenarioId: string): string | null {
  const mapping: Record<string, string> = {
    'life_main': 'Life Main',
    'life_food_plugin': 'Food',
    'life_air_care_plugin': 'Air Care',
    'life_home_care_plugin': 'Home Care',
    'life_energy_plugin': 'Energy',
    'life_pet_care_plugin': 'Pet Care',
    'life_family_care_plugin': 'Family Care',
    'life_plant_care_plugin': 'Plant Care',
    'life_clothing_care_plugin': 'Clothing Care',
    'life_find_plugin': 'Find',
    'life_video_plugin': 'Video',
    'life_home_monitor_plugin': 'Home Monitor',
    'life_music_sync_plugin': 'Music Sync',
  };

  return mapping[scenarioId] || null;
}
