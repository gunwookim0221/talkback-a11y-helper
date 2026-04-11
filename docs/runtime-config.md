# Runtime Config 가이드

## 문서 목적

이 문서는 `config/runtime_config.json`이 현재 runner에서 실제로 지원하는 키와 merge 우선순위를 설명합니다.

기준 코드:
- `tb_runner/runtime_config.py`
- `tb_runner/scenario_config.py`
- `script_test.py`

---

## 1) 로딩/병합 구조

`load_runtime_bundle(base_tab_configs)`는 아래 순서로 병합합니다.

1. 코드 기본값(`_DEFAULTS`)
2. runtime `defaults`
3. 각 scenario base(`TAB_CONFIGS`)
4. `scenario_groups[scenarios.<id>.group]`
5. shared ref(`use_shared_navigation` / `anchor_ref` / `pre_navigation_ref`)
6. runtime `scenarios[scenario_id]` 직접 override

추가로 `global.checkpoint_save_every`를 전 시나리오 공통으로 주입합니다.

핵심 우선순위:
- 공통 정책: `_DEFAULTS` < `runtime.defaults`
- 시나리오 최종값: `base scenario` + 누락키 채움(defaults) + `group` + `shared ref` + `scenario 직접값`

---

## 2) runtime_config.json 루트 스키마(권장 구조)

```json
{
  "global": {
    "checkpoint_save_every": 3
  },
  "defaults": {
    "tab_select_retry_count": 2,
    "anchor_retry_count": 2,
    "main_step_wait_seconds": 1.2,
    "main_announcement_wait_seconds": 1.2,
    "main_announcement_idle_wait_seconds": 0.5,
    "main_announcement_max_extra_wait_seconds": 1.5,
    "overlay_step_wait_seconds": 0.8,
    "overlay_announcement_wait_seconds": 0.8,
    "overlay_announcement_idle_wait_seconds": 0.4,
    "overlay_announcement_max_extra_wait_seconds": 1.0,
    "back_recovery_wait_seconds": 0.8,
    "pre_navigation_retry_count": 2,
    "pre_navigation_wait_seconds": 1.2,
    "screen_context_mode": "bottom_tab",
    "stabilization_mode": "anchor_then_context",
    "scenario_type": "content",
    "stop_policy": {
      "stop_on_global_nav_entry": false,
      "stop_on_global_nav_exit": false,
      "stop_on_terminal": true,
      "stop_on_repeat_no_progress": true
    }
  },
  "shared_navigation": {},
  "shared_anchors": {},
  "shared_pre_navigation": {},
  "scenario_groups": {},
  "scenarios": {
    "devices_main": {
      "group": "main_tabs",
      "enabled": true
    }
  }
}
```

> 숫자는 예시이며, 실제 기본값은 `constants.py` 및 `runtime_config.py` 상수를 따릅니다.

---

## 3) 지원 키 상세

### 3.1 `global`

- `checkpoint_save_every` (positive int)
  - partial save 주기

### 3.2 `defaults`

#### wait/retry
- `tab_select_retry_count`
- `anchor_retry_count`
- `pre_navigation_retry_count`
- `main_step_wait_seconds`
- `main_announcement_wait_seconds`
- `main_announcement_idle_wait_seconds`
- `main_announcement_max_extra_wait_seconds`
- `overlay_step_wait_seconds`
- `overlay_announcement_wait_seconds`
- `overlay_announcement_idle_wait_seconds`
- `overlay_announcement_max_extra_wait_seconds`
- `back_recovery_wait_seconds`
- `pre_navigation_wait_seconds`

#### mode/type
- `screen_context_mode`: `bottom_tab | new_screen`
- `stabilization_mode`: `tab_context | anchor_only | anchor_then_context`
- `scenario_type`: `content | global_nav`

#### stop policy
- `stop_policy.stop_on_global_nav_entry`
- `stop_policy.stop_on_global_nav_exit`
- `stop_policy.stop_on_terminal`
- `stop_policy.stop_on_repeat_no_progress`

#### scenario 간 start state recovery
- `recovery.enabled` (bool): scenario 시작 전 recovery 실행 여부
- `recovery.target_type` (`bottom_tab | anchor | resource_id`)
- `recovery.target` (string regex): 라벨/announcement/text 매칭용
- `recovery.resource_id` (string): resource-id 매칭 및 select 우선 키
- `recovery.max_back_count` (positive int): BACK 최대 반복 횟수

### 3.3 `scenarios.<scenario_id>`

- `enabled` (bool)
- `max_steps` (positive int)
- `entry_type` (`card | direct_select`)
- `group` (string): `scenario_groups` 키 참조
- `anchor_ref` (string): `shared_anchors` 키 참조
- `pre_navigation_ref` (string): `shared_pre_navigation` 키 참조
- `use_shared_navigation` (string): `shared_navigation` 키 참조
- 위 `defaults`의 키 대부분을 scenario 단위로 override 가능
- 추가 nested override 지원:
  - `stop_policy.*`
  - `global_nav.*`
  - `scenario_type`

### 3.4 `shared_navigation`

- 재사용 가능한 `global_nav` 프리셋 모음
- 각 항목은 아래 키 지원
  - `labels` (string list)
  - `resource_ids` (string list)
  - `selected_pattern` (string regex)
  - `region_hint` (`bottom_tabs | left_rail | auto`)

### 3.5 `shared_anchors`

- 재사용 가능한 anchor 정의 모음
- 항목은 `anchor` dict 형태 또는 anchor 필드(`text_regex`, `announcement_regex`, `resource_id_regex`, ...) 직접 선언 둘 다 허용

### 3.6 `shared_pre_navigation`

- 재사용 가능한 `pre_navigation` 액션 리스트 모음

### 3.7 `scenario_groups`

- 유사 화면군 공통 설정 모음
- 일반적으로 `screen_context_mode`, `stabilization_mode`, `use_shared_navigation`를 배치

---

## 4) 타입 정규화/검증 규칙

- int/float는 양수만 허용(그 외 fallback)
- enum은 허용 집합 외 값이면 fallback
- `stop_policy`/`global_nav`는 dict만 반영
- `labels`, `resource_ids`는 문자열 리스트만 유지

---

## 5) enabled / max_steps / override 운영 포인트

- `script_test.py`는 merged 결과에서 `enabled=false`면 시나리오를 skip
- step loop 상한은 `max_steps`
- 시나리오별 임시 우회는 `runtime.scenarios[scenario_id]`에서 관리
- `enabled` 최종 제어는 **정책 A(runtime 단일 제어)** 입니다.
  - `runtime.scenarios.<id>.enabled`가 bool이면 그 값을 사용합니다(`source='runtime'`).
  - 해당 키가 없으면 기본값 `false`를 사용합니다(`source='default'`).
  - `tb_runner/scenario_config.py`의 `enabled`는 실행 제어 source로 사용하지 않습니다.
- 실행 시작 시 loader 로그에 아래 형식으로 출처를 출력합니다.
  - `[CONFIG] scenario enabled scenario='<id>' source='runtime|default' enabled=<bool> base_enabled=<bool>`

---

## 6) backward compatibility

- 새 구조(`shared_navigation`/`scenario_groups`/`*_ref`)를 우선 해석합니다.
- 하지만 기존 구조도 계속 지원합니다.
  - `defaults.global_nav` 사용 가능
  - `scenarios.<id>.global_nav` 직접 override 가능
  - `scenarios.<id>.pre_navigation` 직접 override 가능
  - `scenarios.<id>.anchor` 직접 override 가능

## 7) 자주 헷갈리는 점

- `runtime.defaults`는 base scenario를 “덮어쓰기”가 아니라 **누락 키 채움 + 공통 baseline 제공**에 가깝습니다.
- 최종 강제값은 `runtime.scenarios[scenario_id]`가 담당합니다.
- 지원하지 않는 키를 runtime에 넣어도 loader가 사용하지 않습니다.
- 새 시나리오를 `scenario_config.py`에 추가했다면, 실행하려면 `runtime_config.json > scenarios.<id>.enabled`를 **반드시 명시**해야 합니다.
- 현재 기본 `config/runtime_config.json`은 main tab 계열(`home/devices/life/routines/menu/resource_id_only`)을 `group=main_tabs`로 정리해
  `use_shared_navigation=bottom_tab_global_nav` 경로를 공통 적용합니다.
- base scenario(`tb_runner/scenario_config.py`)도 `BOTTOM_TAB_GLOBAL_NAV`/`DEFAULT_GLOBAL_NAV` 상수로 legacy `global_nav` 중복 정의를 제거해 fallback 동작을 유지합니다.

---

## 함께 보면 좋은 문서

- 실제 수집 실행 순서: `docs/testing-pipeline.md`
- 시나리오 필드 해석: `docs/scenario-config.md`
