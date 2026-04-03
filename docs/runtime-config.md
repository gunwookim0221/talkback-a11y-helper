# Runtime Config 가이드

## 문서 목적

이 문서는 `runtime_config.json`이 시나리오 실행을 어떻게 제어하는지, 그리고 `TAB_CONFIGS`와 어떤 우선순위로 결합되는지 설명합니다.

---

## 1) `runtime_config.json`의 역할

`runtime_config.json`은 **실행 시점 제어 레이어**입니다.

- 배포된 기본 시나리오 정의(`TAB_CONFIGS`)를 코드 수정 없이 환경별로 조정
- 특정 시나리오의 활성/비활성, step 상한, 정책값을 운영 중에 빠르게 변경
- A/B 검증, 장애 우회, 임시 운영 정책 반영에 적합

즉, `TAB_CONFIGS`가 “기본 설계도”라면 `runtime_config.json`은 “실행 스위치”입니다.

---

## 2) `TAB_CONFIGS`와의 관계

- `TAB_CONFIGS`: 시나리오 기본 정의(정적 baseline)
- `runtime_config.json`: 실행 시 override(동적 제어)

운영 원칙:
- 기본값/공통 의도는 `TAB_CONFIGS`에 둠
- 실행 환경별 on/off 및 미세 조정은 `runtime_config.json`에서 처리

---

## 3) 우선순위

동일 키가 동시에 존재하면 다음 우선순위를 따릅니다.

1. `runtime_config.json`
2. `TAB_CONFIGS`

요약: **runtime_config > TAB_CONFIGS**

---

## 4) 충돌 예시

예를 들어, 같은 `scenario_id`에 대해 다음과 같이 값이 다르면 runtime 값이 최종 적용됩니다.

```json
// TAB_CONFIGS
{
  "scenario_id": "devices_main",
  "enabled": true
}
```

```json
// runtime_config.json
{
  "scenario_overrides": {
    "devices_main": {
      "enabled": false
    }
  }
}
```

실제 실행 결과:
- `devices_main.enabled = false` (비실행)

---

## 5) 로그에서 확인하는 방법

실행 로그의 `[CONFIG] scenario override applied`는 다음 의미입니다.

- 해당 `scenario_id`에 runtime override가 매칭됨
- override 항목이 기본 시나리오 정의 위에 적용됨
- 최종 실행값은 override 반영 후 값으로 판단해야 함

운영 시에는 이 로그가 보였는지 먼저 확인하면, “왜 기본값과 다르게 돌았는지”를 빠르게 좁힐 수 있습니다.

---

## 6) 디버깅 가이드 (예상과 다르게 실행/비실행될 때)

아래 순서로 확인하면 원인 추적이 빠릅니다.

1. `runtime_config.json` 확인
   - 해당 `scenario_id` override 존재 여부
   - `enabled`, `max_steps`, 정책 키 변경 여부
2. `TAB_CONFIGS` 기본값 확인
   - 원래 baseline이 무엇인지 확인
3. 실행 로그 확인
   - `[CONFIG] scenario override applied` 출력 여부
   - 최종 적용값으로 실행됐는지 확인

---

## 7) 실무 팁

- 기본값은 `TAB_CONFIGS`에 유지하세요.
  - 팀 공통 기준/문서화/리뷰가 쉬워집니다.
- 실행 제어는 `runtime_config.json`에서 하세요.
  - 코드 변경 없이 운영 대응이 가능합니다.
- 운영 이슈 시 “runtime 먼저, baseline 나중” 순서로 확인하세요.
  - 실제 동작과의 차이를 가장 빨리 발견할 수 있습니다.

---

## 함께 보면 좋은 문서

- scenario 정적 정의/실행 흐름: `docs/scenario-config.md`
