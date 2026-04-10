# Scenario Config 가이드

## 문서 성격

이 문서는 **정책/운영 가이드**입니다.

- 실제 지원 키/동작의 최종 기준: `tb_runner/runtime_config.py`, `tb_runner/scenario_config.py`, `tb_runner/collection_flow.py`, `tb_runner/anchor_logic.py`
- 본 문서는 구현을 과장하지 않고, 현재 동작을 읽기 쉽게 정리하는 목적입니다.

---

## 1) 현재 프로젝트 단계 관점

현재 scenario 설계는 DFS/full-depth 확장보다, **linear collector 안정화**를 위한 실행 정책 분리에 초점이 있습니다.

- deterministic step 수집
- scenario별 진입 안정화(tab/anchor/context)
- stop 정책/데이터 정제
- LLM/VLM 기반 판단은 collector 내부보다 후처리 analyzer 단계 분리가 권장

---

## 2) Scenario 실행 골격

시나리오 1개는 보통 아래 순서를 따릅니다.

1. tab stabilize
2. (optional) pre_navigation
3. anchor stabilize
4. main step loop (`SMART_NEXT` 기반)
5. overlay 분기(필요 시)
6. stop 평가 + 저장

---

## 3) 주요 필드(현재 구현 기준)

- `scenario_id`: override/로그/리포트 기준 식별자
- `enabled`: (base 정의값) 실행 여부 기본값. 최종 실행 제어는 runtime(`config/runtime_config.json`)에서 결정
- `max_steps`: main step 상한
- `scenario_type`: `content | global_nav`
- `tab`: tab 선택 후보 규칙(resource/text/announcement/tie_breaker)
- `pre_navigation`: anchor 전에 수행할 bounded 이동(select/touch/scrollTouch). `scrollTouch`는 기본적으로 실행 직전에 `scroll_to_top`으로 best-effort 초기화한 뒤 검색을 시작하며, `new_screen` plugin 진입 시나리오에서는 한 step 내부에서 누적 downward 탐색을 수행합니다(초기 1회만 top reset).
  - `life_energy_plugin`에서는 진입 성공 판정을 좁게 적용합니다. `anchor_match`/화면 전환 흔들림(덤프/윈도우 포커스 변경) 같은 약한 신호만으로는 pre-navigation 성공으로 확정하지 않고, Energy 시그니처가 확인되지 않으면 실패/재시도로 처리합니다. 단, `focus_shift`/`verified_without_select` 같은 약한 성공 사유 직후에는 guard 단계에서 1회 추가 dump 재확인을 허용해 실제 Energy 화면 진입(true positive)을 회복합니다.
- `anchor`: 안정화 대상 규칙(resource/text/announcement/class/bounds/tie_breaker)
- `context_verify`: 문맥 검증 규칙
- `screen_context_mode`: `bottom_tab | new_screen`
- `stabilization_mode`: `anchor_then_context | anchor_only | tab_context`
- `stop_policy`: 종료 정책
- `global_nav`: 전역 내비게이션 판별 힌트
- `overlay_policy`: overlay entry allow/block 후보

---

## 4) `screen_context_mode` / `stabilization_mode` 해석

두 키는 “정책 엔진 전체”가 아니라, **stabilize 단계의 판정 강도 조절**에 사용됩니다.

### `screen_context_mode`
- `bottom_tab`: 하단 탭 문맥 기반 시나리오
- `new_screen`: 탭 진입 후 별도 화면으로 보는 시나리오(특히 pre_navigation 이후)

### `stabilization_mode`
- `anchor_then_context` (기본): anchor 안정 + context OK
- `anchor_only`: context 검증 생략, anchor 안정 위주
- `tab_context`: context 위주

anchor 안정 자체는 공통적으로 2회 연속 검증(짧은 settle 포함)을 사용합니다.

추가로 anchor 미지정이거나 explicit anchor 매칭이 실패하면, runner는 dump 기준 `content` 영역 후보에서 상단 행의 대표 fallback anchor를 자동 선택합니다. 우선순위는 `top-left → top-center → top-right`이며, 상/하단 chrome 후보(toolbar/bottom nav/system UI)는 제외하려고 시도합니다.

`screen_context_mode=new_screen` 시나리오에서는 `scenario_start` anchor stabilization이 실패해도, 아래 신호가 동시에 충분하면 abort 대신 low-confidence fallback start로 main traversal을 진행합니다.
- pre_navigation 성공
- fallback candidate 존재(상단 content 후보)
- fallback label/resource + get_focus/top-level payload 중 의미 있는 진입 신호 확인

이 경우 anchor row에는 `scenario_start_mode=low_confidence_fallback`, `anchor_stable=false`, `review_note`가 함께 기록됩니다.

---

## 5) `context_verify` 타입 (현재 코드에 있는 범위)

`context_verifier.py` 기준:

- `none` / 미설정: 문맥 검증 생략
- `selected_bottom_tab`:
  - step의 `dump_tree_nodes` 기반 검증
  - dump가 비어 있으면 lazy dump 1회 수행
  - selected 후보 + tab 유사 후보를 조합해 regex 판정
- `screen_text`: `visible_label` regex
- `screen_announcement`: `merged_announcement` regex
- `focused_anchor`: `visible/announcement/view_id` 조합

---

## 6) `scenario_type`: content vs global_nav

- `content`
  - 본문 수집 중심
  - 필요 시 `stop_on_global_nav_entry`로 본문→전역 nav 경계에서 종료
- `global_nav`
  - 하단 탭/좌측 rail 같은 전역 nav 수집 중심
  - `global_nav_main`(또는 `scenario_type=global_nav` + `screen_context_mode=bottom_tab`)은
    scenario open 직후 실제 focused node의 `view_id`가 `global_nav.resource_ids`에 포함될 때만
    step loop를 시작합니다. 1차 실패 시 tab 재정렬을 1회 시도하고, 재확인 실패 시 수집을 중단합니다.
  - 필요 시 `stop_on_global_nav_exit` 또는 `global_nav_end` 해석 사용

global nav 판별 신호:
- resource id
- label/announcement
- selected pattern/state
- region hint

실무 권장:
- content/global_nav를 분리 시나리오로 운영하는 편이 stop 해석 충돌을 줄이기 쉽습니다.

---

## 7) `stop_policy` 지원 범위

현재 지원 키:
- `stop_on_global_nav_entry`
- `stop_on_global_nav_exit`
- `stop_on_terminal`
- `stop_on_repeat_no_progress`

주의:
- 이 정책은 StopEvaluator의 기존 strong/weak 신호(terminal/repeat/no_progress/move failure 등) 위에 추가 적용됩니다.
- overlay realign 직후 반복은 content 시나리오에서 보수적으로 강화됩니다.

---

## 8) overlay_policy

- `allow_candidates`: overlay entry 후보
- `block_candidates`: 차단 목록(allow보다 우선)
- 기본 정책은 **default deny**입니다.
  - 시나리오에 `overlay_policy`가 없으면 overlay 확장을 시도하지 않습니다.
  - `overlay_policy`가 있어도 `allow_candidates`가 비어 있으면 overlay 확장을 시도하지 않습니다.
- 후보 매칭 필드:
  - `resource_id` (exact)
  - `label` (`normalized_visible_label` 기준 exact)
  - `class_name` 또는 `className` (exact)
  - 여러 필드를 함께 지정하면 AND 조건으로 모두 일치해야 매칭됩니다.

entry click 후에는 post-click probe로 `overlay/navigation/unchanged`를 분류하며,
`overlay`일 때만 overlay 수집 + 복귀 realign을 수행합니다.

---

## 9) runtime override와의 관계

- baseline: `tb_runner/scenario_config.py`
- 실행 제어: `config/runtime_config.json`
- merge 우선순위/지원 키 상세: `docs/runtime-config.md`

핵심:
- 시나리오 구조/의도는 baseline에서 관리
- 운영 중 on/off, 상한, wait/retry 미세 조정은 runtime에서 관리
- `enabled`는 정책 A로 운영: `runtime.scenarios.<id>.enabled`만 최종 제어로 사용
  - runtime에 bool 명시 시 해당 값 사용
  - 미명시 시 기본 `false` (비활성)

---

## 10) 실무 예시 (현재 구현 키만 사용)

> 아래 예시는 `tb_runner/scenario_config.py`/`tb_runner/runtime_config.py`에서 실제 해석되는 키만 사용합니다.

### Example A) 기본 content 수집 (bottom tab 유지 화면)

```json
{
  "scenario_id": "devices_main",
  "scenario_type": "content",
  "enabled": true,
  "max_steps": 30,
  "screen_context_mode": "bottom_tab",
  "stabilization_mode": "anchor_then_context",
  "tab": {
    "resource_id_regex": "com\\.samsung\\.android\\.oneconnect:id/menu_devices",
    "text_regex": "(?i).*devices.*",
    "announcement_regex": "(?i).*(selected|선택됨)?.*devices.*",
    "tie_breaker": "bottom_nav_left_to_right",
    "allow_resource_id_only": true
  },
  "anchor": {
    "text_regex": "(?i).*location.*qr.*code.*",
    "announcement_regex": "(?i).*qr.*code.*",
    "tie_breaker": "top_left"
  },
  "context_verify": {
    "type": "selected_bottom_tab",
    "announcement_regex": "(?i).*(selected|선택됨).*devices.*"
  },
  "stop_policy": {
    "stop_on_global_nav_entry": true
  }
}
```

사용 포인트:
- 본문 수집이 목적이면 `scenario_type=content`를 기본값으로 유지
- `selected_bottom_tab` 검증을 함께 쓰면 시작 문맥 흔들림을 줄이기 좋음

### Example B) global_nav 전용 수집 (하단 탭/좌측 rail 확인)

```json
{
  "scenario_id": "global_nav_main",
  "scenario_type": "global_nav",
  "enabled": true,
  "max_steps": 12,
  "screen_context_mode": "bottom_tab",
  "stabilization_mode": "tab_context",
  "context_verify": {
    "type": "screen_announcement",
    "announcement_regex": "(?i).*(selected|선택됨).*(home|devices|life|routines|menu).*"
  },
  "stop_policy": {
    "stop_on_global_nav_exit": true,
    "stop_on_repeat_no_progress": true
  },
  "global_nav": {
    "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
    "resource_ids": [
      "com.samsung.android.oneconnect:id/menu_favorites",
      "com.samsung.android.oneconnect:id/menu_devices",
      "com.samsung.android.oneconnect:id/menu_services",
      "com.samsung.android.oneconnect:id/menu_automations",
      "com.samsung.android.oneconnect:id/menu_more"
    ],
    "selected_pattern": "(?i).*(selected|선택됨).*",
    "region_hint": "bottom_tabs"
  }
}
```

사용 포인트:
- content 시나리오와 분리해 실행하면 stop reason 해석(`global_nav_exit`, `global_nav_end`)이 명확해짐
- `global_nav` 힌트는 resource_id/label/selected/region 신호를 함께 쓰는 것이 안정적

### Example C) new_screen + pre_navigation 진입형 시나리오

```json
{
  "scenario_id": "menu_settings",
  "scenario_type": "content",
  "enabled": true,
  "max_steps": 20,
  "screen_context_mode": "new_screen",
  "stabilization_mode": "anchor_only",
  "pre_navigation": [
    {
      "action": "select",
      "name": "(?i).*settings.*",
      "type": "a",
      "wait": 5
    }
  ],
  "anchor": {
    "text_regex": "(?i).*smartthings settings.*|.*settings.*",
    "announcement_regex": "(?i).*smartthings settings.*|.*settings.*",
    "tie_breaker": "top_left"
  }
}
```

사용 포인트:
- 탭 문맥보다 전환 화면 anchor가 중요한 경우 `new_screen + anchor_only` 조합이 실무적으로 유용
- pre_navigation은 짧고 bounded하게 유지하는 편이 디버깅이 쉬움

---

## 11) overlay/content/global_nav 운영 팁

- `overlay_policy.block_candidates`는 allow보다 우선하므로, 탭별로 열면 안 되는 entry를 명시적으로 차단하는 것이 안전합니다.
- `content`에서 본문 품질을 보고 싶다면 `stop_on_global_nav_entry=true`를 먼저 고려하세요.
- `global_nav` 전용 시나리오는 `max_steps`를 짧게 두고, 종료 reason(`global_nav_exit`, `global_nav_end`)을 함께 확인하는 방식이 운영에 유리합니다.
