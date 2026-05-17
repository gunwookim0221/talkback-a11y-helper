# Locale Matching Guide

이 문서는 현재 locale matching 운영 기준을 정리한다. ko-KR migration은
완료됐고, English SmartThings UI도 검증됐다. Android helper / SMART_NEXT는
변경하지 않는다.

## 현재 검증 상태

- ko-KR representative smoke: pass
- English SmartThings UI representative smoke: pass
- Devices plugin representative smoke: 12/12 pass
- Global / Life / Device long-run regression: 완료

## 핵심 원칙

- target / verify는 stable identity 중심으로 유지한다
- dynamic state suffix는 target/verify에 넣지 않는다
- 상태 문구는 normalize에서 제거한다
- parser alias는 runner target/verify보다 넓을 수 있지만, runtime evidence 없이
  runner identity로 승격하지 않는다

## Mixed-locale device labels

English SmartThings UI에서도 device base label은 혼합 언어일 수 있다. 실제로는
chrome과 state suffix만 영어화되는 경우가 많다.

관찰 예:

- `연기 Clear -> 연기`
- `누수 Dry -> 누수`
- `Audio Pause -> Audio`
- `Camera Connected -> Camera`
- `온습도 센서 Vibration detected -> 온습도 센서`
- `홈카메라 360 Offline -> 홈카메라 360`

따라서 stable identity는 base label로 잡고, suffix는 제거 대상으로만 본다.

## Domain separation

- `bottom_tab`: global navigation
- `local_tab`: plugin-local tab strip
- overlay recognition: More options / Dismiss / Navigate up
- entry verify: scenario-scoped open verification
- parser: semantic expected-label groups

## 사용 금지 예

다음은 target/verify identity로 사용하지 않는다.

- `Clear`
- `Dry`
- `Pause`
- `Connected`
- `Offline`
- `Locked`
- `On`
- `Off`
- `Vibration detected`
- `Motion detected`
- `No smoke detected`
- `No leak detected`
- user-custom label
- generic CTA labels

## Devices plugin note

Devices card search는 helper scroll이 아니라 ADB swipe를 사용한다. helper
scroll은 `All devices` filter를 `No room assigned / 지정된 방 없음`으로
drift시킨 사례가 있었고, ADB swipe는 `All devices` 유지가 검증됐다.

## 운영 메모

- clean start는 여전히 기본 전제다
- English UI에서도 stable label은 observed base label 중심으로 유지한다
- locale mismatch보다 foreground contamination이 더 흔한 실패 원인이다

## Known issue

`life_music_sync_plugin`의 `repeat_no_progress`는 locale blocker가 아니라
별도 traversal-quality known issue로 본다.
