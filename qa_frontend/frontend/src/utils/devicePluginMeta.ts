export function getDevicePluginName(scenarioId: string): string | null {
  const mapping: Record<string, string> = {
    'device_tv_plugin': 'TV',
    'device_washer_plugin': 'Washer',
    'device_door_lock_plugin': 'Door Lock',
    'device_air_purifier_plugin': 'Air Purifier',
    'device_camera_plugin': 'Camera',
    'device_home_camera_plugin': 'Home Camera',
    'device_audio_plugin': 'Audio',
    'device_motion_sensor_plugin': 'Motion Sensor',
    'device_water_leak_sensor_plugin': 'Water Leak Sensor',
    'device_smoke_sensor_plugin': 'Smoke Sensor',
    'device_humidity_sensor_plugin': 'Humidity Sensor',
    'device_temperature_humidity_sensor_plugin': 'Temperature/Humidity Sensor',
  };

  return mapping[scenarioId] || null;
}
