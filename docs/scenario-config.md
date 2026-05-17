# Scenario Config Guide

이 문서는 `tb_runner/scenario_config.py`의 운영 관점 설명이다.

## 1) Scenario 실행 골격

1. tab stabilize
2. optional pre_navigation
3. anchor stabilize
4. main step loop
5. overlay branch
6. stop 평가 + 저장

## 2) 주요 필드

- `scenario_id`
- `enabled` (base default)
- `max_steps`
- `scenario_type`
- `entry_type`
- `entry_match`
- `verify_tokens`
- `pre_navigation`
- `anchor`
- `context_verify`
- `screen_context_mode`
- `stabilization_mode`
- `stop_policy`
- `overlay_policy`

## 3) Devices plugin namespace

현재 Devices plugin namespace:

- `device_smoke_sensor_plugin`
- `device_water_leak_sensor_plugin`
- `device_motion_sensor_plugin`
- `device_door_lock_plugin`
- `device_air_purifier_plugin`
- `device_humidity_sensor_plugin`
- `device_temperature_humidity_sensor_plugin`
- `device_tv_plugin`
- `device_washer_plugin`
- `device_audio_plugin`
- `device_camera_plugin`
- `device_home_camera_plugin`

## 4) `enter_device_card_plugin`

Devices plugin pre-navigation은 `enter_device_card_plugin`을 사용한다.

- Devices tab 선택
- `All devices` selected 보장
- visible inventory first
- room expand only if needed
- stable label normalize
- ancestor card promotion
- safe tap
- ADB swipe bounded search

## 5) Stable label policy

- target은 stable device identity 기준
- 동적 상태 문구는 target/verify에 넣지 않음
- 상태 suffix는 normalize에서 제거

예:

- `연기 Clear -> 연기`
- `누수 Dry -> 누수`
- `Audio Pause -> Audio`
- `Camera Connected -> Camera`
- `온습도 센서 Vibration detected -> 온습도 센서`

## 6) Life / Device 차이

- Life plugin은 plugin card entry와 local tab 흐름이 중심
- Device plugin은 Devices list normalization과 device card search가 중심
