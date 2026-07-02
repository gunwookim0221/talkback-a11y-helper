# Device Plugin Guide

이 문서는 Devices 탭 기반 plugin 검증의 현재 운영 기준을 설명한다.

Updated for V10: 2026-07-03

## 대상 scenario

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

## 제외 / 보류

- 냉장고
- 에어컨

`device_audio_plugin`은 초기에는 inventory 미노출로 보류됐지만, Devices card
search를 ADB swipe 기반으로 바꾼 뒤 정상 추가됐다.

## 진입 흐름

Devices plugin은 `enter_device_card_plugin` pre-navigation으로 통일한다.

1. Devices tab 선택
2. `All devices / 모든 기기` selected 보장
3. 현재 visible inventory 먼저 수집
4. target이 보이면 room expand 생략
5. target이 없으면 high-confidence collapsed room section만 expand
6. helper dump 기준 `device_card` / `device_card_camera` 수집
7. stable label normalize
8. ancestor card promotion
9. safe tap
10. 여전히 없으면 **ADB swipe 기반 bounded search**

## 왜 helper scroll 대신 ADB swipe를 쓰는가

Devices 탭에서는 helper scroll이 filter를 `All devices`에서
`No room assigned / 지정된 방 없음`으로 drift시키는 사례가 있었다.

검증 결과:

- helper scroll: filter drift 가능
- ADB swipe: `All devices` 유지 확인

적용 범위는 Devices card search에만 제한한다. 일반 traversal scroll 정책은
바꾸지 않는다.

## All devices guarantee

`All devices`가 화면에 보인다는 이유만으로 selected로 간주하지 않는다.

판정 신호:

- explicit `selected`
- `checked`
- state description
- chip 구조에서 non-clickable selected chip

주의:

- `No room assigned / 지정된 방 없음` subset을 `All devices`로 오판하면 안 된다.

## Room / section 처리

- collapsed room section은 high-confidence일 때만 펼친다
- target이 현재 visible이면 expand보다 target match가 우선이다

## Safe tap

card center가 `move_devices_button / 방 지정하기` CTA와 겹치면 card 내부의
안전 좌표를 선택한다.

즉:

- 기본: center tap
- overlap 발생 시: upper inset 등 card 내부 safe point 선택

## Resource id 역할

- `com.samsung.android.oneconnect:id/device_card`
- `com.samsung.android.oneconnect:id/device_card_camera`

위 resource id는 card container 판별 기준이다.

- Legacy production 진입: `target_stable_labels`와 normalized stable display label을
  locator로 사용한다.
- V10 Shadow Inventory: display/stable label, resource/class, bounds, viewport,
  observation 정보를 runtime locator evidence로 저장한다.
- V10 Quick Identify: card 진입 후 capability resource-id, XML 구조, capability
  header와 representative label을 조합해 plugin family candidate를 판정한다.

따라서 display name은 V10 semantic identity가 아니지만, Controlled Routing이
미구현인 현재 production traversal의 card 진입은 여전히 Legacy stable-label
locator에 의존한다.

## ko / en normalize

상태 suffix는 normalize에서 제거한다.

예:

- `연기 Clear -> 연기`
- `누수 Dry -> 누수`
- `Audio Pause -> Audio`
- `Camera Connected -> Camera`
- `온습도 센서 Vibration detected -> 온습도 센서`
- `홈카메라 360 Offline -> 홈카메라 360`

실제 target은 observed stable base label 중심으로 잡고, 동적 상태 문구는
target/verify에 넣지 않는다.

## V10 Shadow Device Plugin 흐름

V10은 Legacy 진입을 즉시 대체하지 않고 아래 경로를 별도 실행한다.

```text
Device Card Inventory
-> card open / screen stabilize
-> helper + XML snapshot
-> capability evidence 기반 Quick Identify
-> versioned Policy Registry candidate
-> Legacy scenario와 Shadow Compare
-> family별 Promotion Readiness
```

- `runtime_card_id`는 inventory session 내부에서만 유효한 opaque id다.
- bounded scroll은 repeated viewport/signature/max scroll로 종료한다.
- label-only, bounds-only, resource-id-only dedupe는 금지한다.
- 인접 viewport 경계에서 같은 physical card라는 복합 근거가 있을 때만 merge하며
  동일 이름의 실제 다른 기기는 보존한다.
- identify의 `unknown`, `ambiguous`, `failed`는 fail-closed다.
- card open 후 inventory 복귀가 확인되지 않으면 policy candidate를 eligible로
  승격하지 않는다.

## 검증 결과

- ko representative smoke: `12/12` pass
- English UI representative smoke: `12/12` pass
- full long-run: Device `12/12` 실질 pass

### 대표 검증 포인트

- smoke / water leak: top visible inventory 우선 매칭
- temperature-humidity: safe tap + `All devices` 보장
- audio: ADB swipe deep search 후 정상 탐색
- camera / home camera: special UI에서도 entry/open 확인
