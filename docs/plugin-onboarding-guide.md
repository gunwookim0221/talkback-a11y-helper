# Plugin Onboarding Guide

이 문서는 새 Device plugin 또는 Life plugin을 추가할 때 필요한 실제 작업 절차를
정리한 onboarding 가이드다. 목표는 새 개발자가 혼자서 scenario 추가, smoke 실행,
long-run 검증, 결과 해석까지 끝낼 수 있게 하는 것이다.

## 1. 시스템 개요

핵심 파일은 네 가지다.

- `tb_runner/scenario_config.py`
  - scenario 정의
- `config/runtime_config.json`
  - 실행 제어
- Excel `result` sheet
  - 사람 검수용 요약
- Excel `raw` sheet
  - 디버그/원인 분석용 상세 데이터

result/raw semantics는 아래처럼 이해하면 된다.

- `visible_label`, `merged_announcement`, `focus_view_id`, `focus_bounds`
  - actual TalkBack focus 기준
- `representative_visible` 등 `representative_*`
  - traversal representative 기준

즉 검수자는 보통 `result`를 보고, runtime 원인 분석은 `raw`를 본다.

## 2. Device plugin 추가 절차

대표 예시는 `device_water_leak_sensor_plugin`, `device_audio_plugin`이다.

### scenario 정의

Devices plugin은 `enter_device_card_plugin`을 pre-navigation으로 사용한다.

예시:

```python
{
    "id": "device_water_leak_sensor_plugin",
    "tab": "devices",
    "target_stable_labels": ["누수", "Water leak sensor"],
    "pre_navigation": "enter_device_card_plugin",
    "entry_contract": "plugin_screen",
    "anchor_mode": "anchor_only",
}
```

Audio 예시:

```python
{
    "id": "device_audio_plugin",
    "tab": "devices",
    "target_stable_labels": ["Audio", "오디오"],
    "pre_navigation": "enter_device_card_plugin",
    "entry_contract": "plugin_screen",
    "anchor_mode": "anchor_only",
}
```

### Devices pre-navigation이 하는 일

`enter_device_card_plugin` 흐름은 아래 순서로 동작한다.

1. Devices tab 선택
2. `All devices / 모든 기기` selected 보장
3. 현재 visible inventory 먼저 수집
4. target이 현재 보이면 room expand 생략
5. target이 안 보일 때만 high-confidence collapsed room section expand
6. helper dump 기준 `device_card` / `device_card_camera` 수집
7. stable label normalize
8. ancestor card promotion
9. safe tap
10. 여전히 없으면 ADB swipe 기반 bounded search

### All devices guarantee

`All devices`가 보인다고 selected로 처리하면 안 된다. 실제 selected 판정은 아래
신호를 쓴다.

- explicit `selected`
- `checked`
- state description
- chip 구조에서 non-clickable selected chip

`No room assigned / 지정된 방 없음`은 subset이므로 `All devices`로 오판하면 안
된다.

### visible target first

top viewport에 target이 이미 보이면 room expand를 먼저 하지 않는다. Device card는
현재 visible inventory에서 먼저 매칭한다. 이 순서가 영어 UI `연기 Clear` 같은
초기 top-card 누락을 막는다.

### ADB swipe bounded search

Devices card search에만 helper scroll 대신 ADB swipe를 쓴다. 이유는 helper scroll이
`All devices` filter를 `지정된 방 없음`으로 drift시키는 사례가 있었기 때문이다.

적용 범위:

- Devices card search: ADB swipe 사용
- 일반 traversal scroll: 기존 정책 유지

### safe tap

Device card center가 `move_devices_button / 방 지정하기` CTA와 겹치면 card 내부
안전 좌표를 선택한다.

- 기본: center tap
- overlap 발생 시: upper inset 등 safe point 선택

## 3. Life plugin 추가 절차

대표 예시는 `life_air_care_plugin`, `life_pet_care_plugin`이다.

Life plugin은 Devices보다 pre-navigation이 다양할 수 있지만 기본 구조는 비슷하다.

- `verify_tokens`
  - plugin open 검증용 핵심 텍스트
- overlay 가능성
  - more options, modal, 안내성 overlay 처리 여부 확인
- local tab traversal
  - `Monitor`, `Save`, `Activity` 또는 `Activity`, `Care` 같은 strip 순회 여부 확인
- scrolltouch / history
  - history/long list plugin은 exhaustion과 repeat 양상을 확인
- `plugin_open_verified`
  - long-run 전 smoke 필수 체크

예시:

```python
{
    "id": "life_air_care_plugin",
    "tab": "life",
    "verify_tokens": ["Air Care"],
    "entry_contract": "plugin_screen",
}
```

```python
{
    "id": "life_pet_care_plugin",
    "tab": "life",
    "verify_tokens": ["Pet Care"],
    "entry_contract": "plugin_screen",
}
```

## 4. runtime_config 등록 방법

기본 등록 예시:

```json
{
  "device_audio_plugin": {
    "enabled": true,
    "max_steps": 40
  }
}
```

운영 기준:

- smoke: `5~10`
- representative: `20~40`
- long-run: `40~60`

Device plugin은 보통 기본 운영에서 `enabled=false`로 두고, 실행 시 override해서
돌린다.

## 5. label / stable name 수집 방법

stable label은 helper dump와 XML을 같이 보고 잡는다.

수집 소스:

- helper dump label
- XML `device_name`
- screenshot visible text

혼합 언어 사례를 항상 염두에 둔다.

- English UI여도 base label이 한국어일 수 있음
- 상태 suffix만 영어화될 수 있음

대표 예:

- `Audio Pause -> Audio`
- `연기 Clear -> 연기`
- `누수 Dry -> 누수`
- `온습도 센서 Vibration detected -> 온습도 센서`

## 6. normalize / alias 정책

원칙:

- 상태 suffix는 제거
- stable base label은 유지
- base label 내부 단어는 훼손하지 않음

제거 허용 예:

- `Connected`
- `Offline`
- `Pause`
- `Clear`
- `Dry`
- `Vibration detected`

주의:

- `Motion sensor`에서 `Motion` 제거 금지
- `Smoke sensor`에서 `Smoke` 제거 금지

alias는 stable identity 보조용으로만 쓰고, 동적 상태 문구는 target/verify에 넣지
않는다.

## 7. smoke 실행 절차

권장 단계:

1. `max_steps=5`
2. `plugin_open_verified` 확인
3. local tab 존재 여부 확인
4. overlay 여부 확인

예시:

```powershell
$env:PYTHONIOENCODING='utf-8'
python script_test.py
```

실행 전에는 보통 임시 runtime override를 사용한다.

smoke에서 확인할 최소 항목:

- `pre_navigation_success=True`
- `entry_contract success_verified`
- `plugin_open_verified`
- fatal / traceback 없음

## 8. long-run 실행 절차

long-run은 plugin이 실제 exhaustion 또는 stop policy까지 진행되는지 보는 단계다.

주요 종료 reason 해석:

- `repeat_no_progress`
  - 정상 exhaustion일 수 있음
- `safety_limit`
  - step budget 도달
- `smart_nav_terminal`
  - 자연 terminal 종료

해석 원칙:

- `plugin_open_verified` 실패가 더 위험
- `repeat_no_progress` 자체는 FAIL이 아님
- early harmful loop, overlay loop, foreground contamination이 더 위험

## 9. result sheet 읽는 법

result sheet는 사람 검수용이다.

- `visible_label`
  - actual TalkBack focus
- `representative_visible`
  - traversal representative

`REPRESENTATIVE_CONTEXT`는 이 둘이 다르지만 시스템 동작상 의도된 경우다.

예:

- actual focus: `More options`
- representative: `Increase`

판정 가이드:

- `EXACT_MATCH + repeat_no_progress`
  - `WARN` 가능
- `LABEL_MISMATCH`
  - `FAIL`
- `EMPTY_SPEECH`
  - `FAIL`

접근성 mismatch와 traversal 종료 reason을 구분해서 봐야 한다.

## 10. locale 검증

기본 검증 순서:

1. `ko-KR` primary run
2. English UI representative smoke
3. 필요 시 full regression

주의:

- `All devices / 모든 기기`
- `No room assigned / 지정된 방 없음`

이 둘은 locale만 바뀌는 것이 아니라 실제 filter/subset 의미가 다르다.

영어 UI에서도 mixed-language inventory가 가능하므로, 영어 alias만 추가해서
해결하려고 하면 잘못될 수 있다.

## 11. commit 전 체크리스트

- `git diff --check`
- 관련 `pytest`
- smoke 실행
- 필요 시 long-run 실행
- `plugin_open_verified` 확인
- staged files 확인
- `__pycache__` 제외
- `output` 제외
- xlsx/log 제외

최소 확인 항목:

- source 파일만 stage됐는가
- representative smoke가 통과하는가
- 필요한 경우 locale smoke가 통과하는가

## 12. Plugin Onboarding Wizard MVP

QA Frontend의 Plugin Discovery panel은 신규 plugin 추가 비용을 줄이기 위한
wizard형 workflow를 제공한다. 현재 MVP는 아래 순서를 지원한다.

```text
Discover Plugins
↓
Probe
↓
Generate Draft
↓
Review Draft
↓
Apply Draft
↓
Smoke Draft
↓
Refresh Smoke Result
↓
Session Restore / Recommendation
↓
Rollback Preview
```

### Discovery

현재 SmartThings 화면에 visible 상태로 보이는 Life / Device plugin 후보를 수집한다.

- Device: helper dump 기반 visible device card 수집
- Life: XML 기반 visible card-like node 수집
- run 실행 중에는 ADB/helper/TalkBack focus 충돌 방지를 위해 차단된다

Discovery는 bounded scroll이나 자동 tab 이동을 수행하지 않는다.

### Probe

선택한 card에 대해 plugin 진입을 짧게 시도하고 draft 생성을 위한 seed를 수집한다.
목표는 PASS/FAIL 판정이 아니라 다음 후보를 얻는 것이다.

- plugin open verified 후보
- verify token 후보
- local tab 후보
- header/title 후보
- representative card 후보
- overlay/modal hint

### Draft Generate / Review

Draft Generate는 `scenario_config.py`와 `runtime_config.json`에 들어갈 후보 JSON을
만든다. Review는 실제 파일 수정 전에 중복과 적용 가능성을 검사한다.

Review에서 확인하는 주요 항목:

- scenario id 중복
- runtime config key 중복
- manual review required
- fallback candidate id
- 적용 예정 diff preview

### Apply Draft

Apply는 review가 허용한 draft만 실제 파일에 반영한다.

수정 대상:

- `tb_runner/scenario_config.py`
- `config/runtime_config.json`

Apply 전 backup은 `output/plugin_draft_backups/<timestamp>/` 아래에 생성된다.

### Smoke Start / Result Refresh

Smoke는 apply된 scenario 하나만 실행한다.

- `scenario_id` 1개
- `max_steps <= 10`
- mode는 `smoke`
- 원본 runtime config를 직접 수정하지 않고 override로 실행

Smoke start 후 결과 summary는 수동 refresh로 조회한다. 자동 polling은 아직
구현하지 않았다.

### Onboarding Session

wizard 진행 상태는 session 단위로 저장된다.

저장 위치:

```text
output/plugin_onboarding_sessions/<session_id>.json
```

저장되는 단계:

- discovery
- probe
- draft
- review
- apply
- smoke

최근 session을 선택하면 저장된 payload를 기반으로 panel state를 best-effort로
복원한다.

### Recommendation

session restore 시 smoke 결과와 review/apply 상태를 기준으로 다음 action을 추천한다.

- `ready_for_manual_validation`
- `ready_with_warning`
- `needs_probe_revision`
- `apply_rollback_candidate`
- `review_blocked`
- `incomplete`

추천은 UI 안내만 제공한다. commit, retry, rollback 실행은 아직 자동 수행하지
않는다.

### Rollback Preview

Rollback Preview는 apply backup과 현재 파일을 비교해 실제 rollback 전에 영향 범위를
보여준다.

확인 항목:

- backup file 존재 여부
- 현재 파일 존재 여부
- scenario entry 제거 예상 여부
- runtime config entry 제거 예상 여부
- current vs backup diff preview

실제 rollback 복원은 아직 구현하지 않았다.

## 13. Plugin Onboarding Wizard known limitations

- discovery/probe는 현재 visible card 중심이다.
- bounded scroll discovery는 아직 없다.
- 자동 tab 이동은 아직 없다.
- Smoke result는 수동 refresh 방식이다.
- automatic polling은 아직 없다.
- Apply는 backup을 생성하지만 rollback 실행 UI/API는 아직 없다.
- Rollback은 preview only다.
- `serial`은 smoke request schema에 있지만 현재 runner 실행 경로에 직접 연결되지 않는다.
- 실기기 품질은 plugin별 smoke와 필요 시 long-run으로 확인해야 한다.

## 14. known high-risk plugin 유형

주의가 필요한 유형:

- Camera
- Home Camera
- Audio
- overlay-heavy plugin
- local-tab-heavy plugin

이유:

- Camera/Home Camera: video, fullscreen, controller/history 분기
- Audio: media controls 밀도 높음
- overlay-heavy plugin: modal/overlay loop 가능성
- local-tab-heavy plugin: wrap-around와 exhaustion 해석 필요

이 유형은 smoke 통과 후 long-run에서 실제 종료 패턴을 반드시 확인해야 한다.
