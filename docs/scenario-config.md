# Scenario Config & Runner Policy

## 문서 목적

이 문서는 runner의 **scenario-level 실행/안정화 정책**을 설명합니다.

역할 분리를 위해 다음을 명확히 합니다.
- `docs/api-reference.md`: `A11yAdbClient` 퍼블릭 API 기준서
- 본 문서: scenario config가 runner의 문맥 해석/안정화/순회 정책을 어떻게 바꾸는지 설명

> 핵심: 이번 변화는 **helper API 변경이 아니라 runner 정책 변경**입니다.

---

## 왜 정책 분리가 필요한가

기존에는 많은 화면을 사실상 동일한 bottom-tab 문맥으로 해석했습니다.
이 방식은 다음 화면에서는 유효합니다.
- home / devices / life / routines / menu

하지만 전환 화면에서는 오검증이 발생할 수 있습니다.
- settings
- plugin detail
- sub page

실제 문제의 본질은 클릭 실패보다 **화면 타입 해석 실패**에 가깝습니다.
- ADB bounds center tap으로 진입 자체는 가능
- 진입 후 runner가 이전 bottom-tab 상태를 계속 기대하여 `context mismatch` 또는 `anchor stabilization failed` 유발

따라서 scenario config로 화면 문맥 처리 정책을 분기해야 합니다.

추가로 폰/태블릿 동시 대응을 위해, runner는 bottom tab 하드코딩 대신 **global navigation(전역 네비게이션)** 상위 개념을 지원합니다.
- 폰: 하단 탭바(bottom tabs)
- 태블릿: 좌측 navigation rail/sidebar

즉, `content` 시나리오는 본문 수집, `global_nav` 시나리오는 전역 네비게이션 수집으로 책임을 분리합니다.

---

## Scenario config가 제어하는 기본 실행 흐름

일반적인 시나리오 실행 단계:

1. **tab selection**
   - 필요한 경우 진입 기준 탭/문맥으로 이동
   - 탭 터치/선택 직후, 동일 탭 selector로 TalkBack focus 정렬(`focus align`)을 bounded retry로 시도
2. **context verification**
   - 현재 화면이 기대 문맥인지 확인
3. **pre_navigation**
   - anchor 판단 전에 수행할 선행 이동
4. **anchor stabilization**
   - anchor 신호 기반으로 화면 진입/안착 여부 판단
5. **traversal / `SMART_NEXT`**
   - 문맥이 안정화된 뒤 순회 실행

중요한 점은, 위 단계 자체는 같아도 각 단계의 **판정 기준**은 scenario config에 따라 달라질 수 있다는 것입니다.

### 실행 흐름 요약(실무 체크용)

1. **tab 선택**
   - `tab`/진입 규칙으로 시작 지점을 맞춤
2. **anchor 안정화**
   - `anchor` + (`context_verify` 조건)로 목표 화면 안착 여부 판단
3. **step loop**
   - `SMART_NEXT` 기반 순회/수집 반복
4. **stop 판단**
   - `stop_policy` + `max_steps` 기준으로 종료 결정

아래 두 축을 분리해서 이해하면 혼동을 줄일 수 있습니다.
- **First axis: screen context classification**
  - 이 화면이 어떤 문맥 타입인지(`screen_context_mode`)
- **Second axis: stabilization success policy**
  - 안정화 성공을 어떤 규칙으로 판정할지(`stabilization_mode`)

---

## TAB_CONFIGS의 역할과 runtime override 관계

`TAB_CONFIGS`는 각 시나리오의 **정적 정의(static baseline)** 입니다.

- 시나리오 식별자, 타입, 진입 탭, anchor, stop 정책 등 “기본 실행 의도”를 코드/기본 설정으로 표현
- 별도 override가 없으면 runner는 `TAB_CONFIGS` 기준으로 실행

실행 시점에는 `runtime_config.json`이 추가로 적용될 수 있습니다.

- 관계 요약: `TAB_CONFIGS`(기본 정의) + `runtime_config.json`(실행 시 override)
- 우선순위: runtime override가 동일 키를 덮어씀
- 상세 규칙/운영 팁은 `docs/runtime-config.md` 참고

---

## TAB_CONFIGS 주요 필드 빠른 참조

> 아래는 실무에서 자주 확인하는 핵심 필드 요약입니다. 세부 예시는 문서 하단 예시 JSON을 함께 참고하세요.

- `scenario_id`
  - 시나리오 고유 식별자. 로그/리포트/override 타겟 지정의 기준 키
- `scenario_type` (`content` | `global_nav`)
  - 수집/순회 대상 타입을 지정
- `tab`
  - 시작 문맥(탭/전역 네비게이션 엔트리) 선택 정보
- `anchor`
  - 목적 화면/섹션 도달 및 안정화 판정 신호
- `context_verify`
  - 현재 포커스/화면이 기대 문맥인지 확인하는 규칙
- `stop_policy`
  - step loop 종료 조건(terminal, 반복/no-progress, 시나리오 경계 등)
- `overlay_policy`
  - overlay/팝업 개입 시 정렬·복구 정책
- `global_nav`
  - 전역 네비게이션 판별 힌트(label/resource_id/selected/region)
- `enabled`
  - 시나리오 활성/비활성 토글
- `max_steps`
  - step loop 최대 반복 횟수 상한

---

## 화면 컨텍스트 타입

### 1) `bottom_tab`

하단 탭 문맥이 유지되는 화면에 사용합니다.

예시:
- home
- devices
- life
- routines
- menu

특징:
- 하단 탭이 존재하고 selected 상태가 의미 있음
- 기존 tab 기반 context 검증이 유효함

### 2) `new_screen`

전환 후 새로운 화면으로 보는 경우에 사용합니다.

예시:
- settings
- plugin detail
- sub page

특징:
- 하단 탭 의미가 약하거나 사실상 무의미
- 탭에서 진입했더라도, 이후 화면은 별도 전환 화면으로 간주
- 필요 시 탭 문맥 강제 검증을 완화/생략 가능

---

## 주요 설정값(의도 기준)

아래는 구현 의도를 설명하기 위한 정책 키입니다. 실제 최종 키 이름은 구현 단계에서 조정될 수 있습니다.

### `screen_context_mode`

시나리오의 문맥 처리 모드를 지정합니다.

대표 값:
- `bottom_tab`
- `new_screen`

동작:
- `bottom_tab`: 기존 selected tab/primary tab context 검증이 유효
- `new_screen`: 탭 선택 이후 전환 화면으로 취급하며, 탭 문맥 강제 검증을 완화하거나 생략 가능

### `stabilization_mode`

진입 후 “안정화 성공”을 어떤 규칙으로 판정할지 정의합니다.

대표 모드:
- `anchor_then_context`
  - 기존 기본 동작(보수적)
  - anchor + context를 함께 확인한 뒤 안정화 성공으로 판정
- `anchor_only`
  - anchor 매칭만으로 안정화 성공 가능
  - settings/detail/sub page 같은 전환 화면에 적합
- `tab_context`
  - context 일치만으로 안정화 성공 가능
  - 단, context regex가 느슨하면 오탐 가능성이 있으므로 주의 필요

해석 가이드(권장 조합):
- 탭 유지 화면: `screen_context_mode=bottom_tab` + `stabilization_mode=anchor_then_context` 또는 `tab_context`
- 전환 화면: `screen_context_mode=new_screen` + `stabilization_mode=anchor_only` 또는 `anchor_then_context`

### `scenario_type`

시나리오의 수집 대상 자체를 구분합니다.

- `content` (기본값): 본문 중심 수집
- `global_nav`: 앱 전역 네비게이션 영역 중심 수집

권장:
- 메인 화면/리스트/상세는 `content`
- 하단 탭/좌측 rail 검증 전용은 `global_nav`

#### `content` vs `global_nav` 차이 요약

- `content`
  - 본문 영역을 순회/수집하는 기본 시나리오
  - 필요 시 `stop_on_global_nav_entry`로 본문→전역 네비게이션 경계에서 종료
- `global_nav`
  - 하단 탭/좌측 rail 같은 전역 네비게이션 자체를 순회/검증
  - 필요 시 `stop_on_global_nav_exit`로 전역 네비게이션→본문 경계에서 종료

### `stop_policy` (확장)

기본 stop evaluator에 시나리오 경계 인식을 추가합니다.

- `stop_on_global_nav_entry`
  - `content` 시나리오에서 현재 row가 global nav로 판별되면 stop 후보
- `stop_on_global_nav_exit`
  - `global_nav` 시나리오에서 global nav를 벗어나 본문으로 진입하면 stop 후보
- `stop_on_terminal` (기본 `true`)
- `stop_on_repeat_no_progress` (기본 `true`)

stop reason 해석(collector 로그 기준):
- `global_nav_entry`: `content` 시나리오에서 본문→global nav 진입 경계 감지
- `global_nav_end`: `global_nav` 시나리오에서 nav 말단의 failed/repeat/no_progress 누적 종료
- `repeat_no_progress`: 일반 반복/no-progress 조합 종료(overlay realign 직후에는 반복이 실제 확인된 경우에만 보수적으로 활용)

### `global_nav` 블록 (optional)

global navigation 판별 힌트를 제공합니다.

- `labels`: 전역 네비게이션 label 목록
- `resource_ids`: 전역 네비게이션 resource id 목록
- `selected_pattern`: selected 발화/텍스트 패턴
- `region_hint`: `bottom_tabs` | `left_rail` | `auto`

판별 우선순위는 `resource_id → text/announcement → selected → region_hint`이며, region은 보조 신호로만 사용합니다.

### anchor 관련 설정

목표 화면/섹션 도달 여부를 판단하는 anchor 조건입니다.

일반 요소:
- text/regex
- resource id 패턴
- announcement 패턴
- tie-breaker 우선순위

권장:
- `stabilization_mode=anchor_only`일 때는 anchor 품질(구분력)을 충분히 강하게 설정

### pre_navigation 관련 설정

stabilization/traversal 이전에 수행할 선행 이동 절차를 정의합니다.

예시:
- menu -> settings
- menu -> plugin detail

권장:
- pre_navigation은 명시적이고 bounded하게 유지
- 전환 화면에서 불필요한 탭 상태 검증과 과결합하지 않기

### `tab_focus_align_retry_count`

탭 전환 직후 TalkBack focus를 동일 탭으로 맞추는 정렬 시도의 retry 횟수입니다.

- 기본값: `2`
- 의미:
  - 탭 touch/select 이후 `tab.resource_id_regex` / `tab.text_regex` / `tab.announcement_regex`를 재사용해 `select` 기반 정렬 시도
  - `new_screen + pre_navigation` 전환 시나리오에서는 fast path로 동작하며 최대 `2`회로 상한 적용(기본 1~2회의 짧은 bounded 시도)
  - 성공하면 다음 단계로 진행
  - 실패 시:
    - 메인 탭 시나리오(`home_main`, `devices_main`, `life_main`, `routines_main`)는 strict 실패로 간주 가능
    - transition 시나리오(`pre_navigation` + `new_screen` 또는 `anchor_only`)는 warning 후 계속 진행

### `tab_focus_align_settle_wait_seconds`

탭 touch 직후 fast focus align 시작 전에 두는 짧은 settle wait입니다.

- 기본값: `0.12`
- 적용 범위: `new_screen + pre_navigation` fast path
- 상한: `0.2`초
- 의도:
  - 화면 전환 직후 UI 상태 반영 시간을 아주 짧게 보장
  - focus align을 지연시키지 않으면서도 실패율을 줄이는 best-effort 균형값
  - fast path(`new_screen + pre_navigation + anchor_only`)에서는 tab align/pre_navigation/scenario_start 초기 단계에서
    announcement wait/get_focus wait를 짧게 사용하고, `get_focus` dump fallback·step dump는 필요 시점 전까지 생략해
    초기 진입 체감 지연을 줄입니다.

### `expected_bottom_tab` 등 기존 context 설정

기존 context 검증 필드가 있는 경우:
- `bottom_tab` 모드에서는 기존 의미를 유지
- `new_screen` 모드에서는 해당 값이 전환 화면에서 과도한 강제 실패 조건이 되지 않도록 해석

### `context_verify` 대표 타입(예시)

아래 타입은 시나리오 이해를 위한 대표 예시이며, 구현 전체 목록을 나열하는 목적은 아닙니다.

- `selected_bottom_tab`
  - 선택된 하단 탭(또는 primary tab) 일치 여부 확인
- `screen_text`
  - 화면 내 텍스트 패턴으로 문맥 확인
- `screen_announcement`
  - 접근성 announcement 패턴으로 문맥 확인
- `focused_anchor`
  - 현재 포커스/anchor 상태로 문맥 확인

---

## 모드별 동작 차이(축 분리 기준)

### Screen context axis (`screen_context_mode`)

#### `bottom_tab`

- `selected_bottom_tab` 계열 검증 수행
- anchor 검증도 사용 가능하지만 tab 문맥 검증이 기본적으로 유효

#### `new_screen`

- 탭 진입 이후 전환 화면으로 취급
- 시나리오 의도에 따라 탭 문맥 검증을 완화/생략 가능

### Stabilization axis (`stabilization_mode`)

#### `anchor_then_context`
- anchor + context를 함께 만족해야 안정화 성공(보수적 기본값)

#### `anchor_only`
- bottom-tab/primary-tab 검증 없이 anchor 중심으로 안정화 판정 가능

#### `tab_context`
- context 일치만으로 안정화 가능
- 단, regex가 느슨하면 오탐 가능성이 있어 context 조건 품질 관리 필요

---

## Backward compatibility 규칙

하위 호환은 필수입니다.

원칙:
- 새 필드는 opt-in이며, 새 설정이 없으면 기존 시나리오 동작 유지
- 기존 시나리오가 기본값만으로 계속 동작해야 함
- 기본값은 `bottom_tab + anchor_then_context` 조합으로 해석
- 기존 `selected_bottom_tab` 경로는 제거가 아니라 보존
- runtime merge 시 base scenario에 이미 있는 값은 유지하고, runtime defaults는 누락 키만 채운 뒤 scenario override를 마지막에 적용
- transition 시나리오(`pre_navigation` + `new_screen`/`anchor_only` 의도)에서 tab candidate 선택 성공 후 `selected_bottom_tab` 검증만 실패한 경우 warning 후 진행 가능(단, 메인 탭 시나리오는 strict 유지)

실무 해석:
- 신규 키 미지정 시 레거시 동작(기존 tab 중심 해석)을 기본 유지

---

## 실전 예시

### Example: bottom_tab (default behavior)

```json
{
  "scenario_id": "devices_main",
  "screen_context_mode": "bottom_tab",
  "stabilization_mode": "anchor_then_context",
  "context_verify": {
    "type": "selected_bottom_tab",
    "announcement_regex": "(?i).*(selected|선택됨).*devices.*"
  },
  "anchor": {
    "text_regex": "(?i).*location.*qr.*code.*"
  }
}
```

### Example: global navigation 분리

```json
{
  "scenario_id": "devices_main",
  "scenario_type": "content",
  "stop_policy": {
    "stop_on_global_nav_entry": true
  },
  "global_nav": {
    "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
    "resource_ids": [
      "com.samsung.android.oneconnect:id/menu_favorites",
      "com.samsung.android.oneconnect:id/menu_devices"
    ],
    "selected_pattern": "(?i).*(selected|선택됨).*",
    "region_hint": "bottom_tabs"
  }
}
```

```json
{
  "scenario_id": "global_nav_main",
  "scenario_type": "global_nav",
  "stop_policy": {
    "stop_on_global_nav_exit": true
  },
  "global_nav": {
    "labels": ["Home", "Devices", "Life", "Routines", "Menu"],
    "resource_ids": ["com.samsung.android.oneconnect:id/menu_devices"],
    "selected_pattern": "(?i).*(selected|선택됨).*",
    "region_hint": "auto"
  }
}
```

- 기본 탭 유지 화면에서 사용하는 가장 일반적인 패턴입니다.
- backward compatibility 기본값(`bottom_tab + anchor_then_context`)과 동일한 동작입니다.

### Example: new_screen (settings / detail screen)

```json
{
  "scenario_id": "settings_entry",
  "screen_context_mode": "new_screen",
  "stabilization_mode": "anchor_only",
  "pre_navigation": [
    {
      "action": "tap_bounds_center_adb",
      "target": "com.example:id/settings_button",
      "type": "r"
    }
  ],
  "anchor": {
    "text_regex": "(?i).*navigate up.*",
    "announcement_regex": "(?i).*navigate up.*"
  },
  "context_verify": {
    "type": "screen_text",
    "text_regex": "(?i).*settings.*"
  }
}
```

- 탭에서 설정/상세 화면으로 전환되는 경우에 사용하는 패턴입니다.
- bottom-tab 문맥을 강제하지 않고 anchor 중심으로 안정화합니다.

### 예시 A: `menu -> settings`

의도:
- 출발은 bottom-tab 화면(`menu`)
- 도착은 전환 화면(`settings`)

권장 정책:
- settings 단계는 `screen_context_mode: new_screen`
- `stabilization_mode: anchor_only` 또는 `anchor_then_context`
- pre_navigation: menu에서 settings까지 단계 명시
- 진입 후 selected bottom-tab 일치 여부를 강제 성공 조건으로 두지 않음

기대 효과:
- 이전 탭 상태 기대값 때문에 발생하는 `context mismatch` 감소

### 예시 B: `menu -> plugin detail`

의도:
- menu/list 문맥에서 plugin detail 진입

권장 정책:
- `screen_context_mode: new_screen`
- detail 화면을 식별할 강한 anchor(title/id/announcement) 사용
- `stabilization_mode: anchor_only` 또는 `anchor_then_context`
- pre_navigation 절차를 명시적으로 제한

기대 효과:
- bottom-tab 연속성 대신 detail anchor 안착으로 진입 성공 판정

---

## 디버깅 포인트

실패 시 아래 순서로 점검합니다.

1. **`context mismatch`**
   - 전환 화면인데 bottom-tab 검증이 여전히 강제되는지 확인
   - `screen_context_mode`가 `new_screen`으로 분기되어야 하는지 점검

2. **`anchor stabilization failed`**
   - `stabilization_mode`가 화면 성격에 맞는지(`anchor_then_context`/`anchor_only`/`tab_context`) 확인
   - anchor 조건이 약하거나 모호하지 않은지 확인
   - pre_navigation이 실제 목적 화면까지 도달한 뒤 stabilization이 시작되는지 확인

3. **wrong anchor selected**
   - 유사 anchor가 다수 존재하는지 점검
   - id/text/announcement/tie-breaker를 강화

4. **잘못된 문맥에서 traversal 시작**
   - destination 화면 타입과 context/stabilization 모드가 일치하는지 재확인

---

## 정리

- 이 문서는 특정 화면 하드코딩 가이드가 아니라, **확장 가능한 일반 정책 문서**입니다.
- 앱이 달라도 “탭 유지 화면”과 “전환 화면”이 혼재하면 같은 모델을 적용할 수 있습니다.
- 변화의 본질은 다음과 같습니다.
  - 기존: 단일 tab 문맥 검증 중심
  - 변경: scenario config 기반 문맥/안정화 정책 분기
