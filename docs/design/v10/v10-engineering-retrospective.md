# V10 Engineering Retrospective

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 |
| Owner | TalkBack Automation |
| Last Updated | 2026-07-05 |
| Depends On | [V10 Phase Closure](v10-phase-closure.md) |
| Related Documents | [V10 Overview](v10-overview.md), [V10 Device Inventory Design](v10-device-inventory-design.md), [V10 Quick Plugin Identify Design](v10-quick-plugin-identify-design.md), [V10 Policy Mapping Design](v10-policy-mapping-design.md), [V10 Shadow Validation Design](v10-shadow-validation-design.md), [V10 Implementation Roadmap](v10-implementation-roadmap.md), [QA Frontend Guide](../../qa-frontend-guide.md), [Runner Flow](../../runner_flow.md) |

## 1. Executive Summary

V10의 목표는 Device plugin 진입을 display name exact match에서 분리하고, capability
기반 판단을 별도 shadow layer로 검증할 수 있는 경로를 만드는 것이었다. 핵심은
traversal engine을 다시 쓰는 것이 아니라, "무슨 card인가"를 판단하는 계층을
독립시키는 것이었다.

최종 결과는 다음과 같다.

```text
Runtime Inventory
-> Quick Identify
-> Policy Registry
-> Shadow Compare
-> Promotion Readiness
-> QA Frontend Reporting
```

V10은 이 shadow architecture를 완성했고, Legacy routing/traversal은 끝까지
authoritative baseline으로 유지했다.

최종 판단:

- Shadow Validation: `PASS`
- Promotion Readiness: `HOLD`
- Controlled Routing: V11로 연기

실기기 최종 검증에서 inventory `15`, `MATCH 6`, `UNKNOWN 9`, `MISMATCH 0`,
`FAILED 0`을 확인했다. Promotion은 fail-closed 기준을 유지했고, final closure에서는
overall `HOLD`, READY candidate `5`로 정리했다.

## 2. Original Motivation

V10을 시작한 이유는 단순했다. Device plugin routing에서 display name이 사실상
identity처럼 쓰이고 있었고, 이 구조는 계정, locale, room naming, 사용자 rename에
지나치게 취약했다.

구현 전 구조는 아래에 가까웠다.

```text
Display Name
-> Scenario
-> Traversal
```

이 구조는 다음 문제를 만들었다.

- Motion, Door, Leak 같은 generic plugin이 이름 표준화에 과도하게 의존했다.
- Home UI가 바뀌거나 card naming이 흔들리면 진입 안정성이 같이 흔들렸다.
- "카드를 찾는 문제"와 "어떤 policy를 적용할지 결정하는 문제"가 분리되어 있지 않았다.
- 미래의 capability-based routing 실험을 할 수 있는 관측 경로가 없었다.

V10은 display name을 제거하는 프로젝트가 아니라, display name을 locator evidence로
강등시키고 semantic identity를 capability evidence 쪽으로 옮기기 위한 준비
프로젝트였다.

## 3. Major Architecture Decisions

### 3.1 Layer를 강제로 분리한 이유

V10에서 가장 중요한 결정은 Inventory, Identify, Policy, Shadow, Promotion을 하나의
기능이 아니라 서로 다른 failure domain으로 분리한 것이다.

```text
Inventory
-> 현재 Devices surface에서 무엇이 보이는가

Quick Identify
-> 이 card가 어떤 plugin family처럼 보이는가

Policy Registry
-> 그 family에 어떤 legacy scenario policy를 연결할 수 있는가

Shadow Compare
-> Legacy와 V10이 같은 runtime card에서 같은 결론을 내렸는가

Promotion Readiness
-> 지금 당장 production routing으로 승격해도 되는가
```

이 분리는 구현 중 매우 유용했다.

- inventory bug와 classifier bug를 분리해서 디버깅할 수 있었다.
- mapping bug가 traversal regression처럼 보이지 않도록 차단할 수 있었다.
- Shadow mismatch가 즉시 production behavior를 바꾸지 않게 할 수 있었다.
- feature flag를 계층별로 끄고 마지막 검증된 boundary까지 쉽게 되돌릴 수 있었다.

### 3.2 Legacy authoritative를 끝까지 유지한 이유

V10은 capability routing을 "구현"했지만 "활성화"하지는 않았다. 이는 보수적이라서가
아니라, Inventory와 Identify가 아직 운영 truth가 아니었기 때문이다.

중요한 원칙은 다음 세 가지였다.

- fail-closed
- feature flag 기본 OFF
- legacy result preserved

결과적으로 V10 shadow pass가 실패해도 Legacy XLSX, report, batch result는 그대로
살아남았고, 이 덕분에 shadow layer를 실제 장비에서 공격적으로 실험할 수 있었다.

## 4. Important Implementation Decisions

### 4.1 Runtime Inventory를 따로 만들었다

Discover Plugins의 visible-only discovery를 그대로 확장하는 대신 별도 runtime
inventory를 만들었다. 이유는 shadow comparison에서 "무슨 card를 비교하는가"를
session-scoped identity로 고정해야 했기 때문이다.

핵심 결정:

- `runtime_card_id`는 inventory session 내부에서만 유효한 opaque id다.
- `display_label`과 `stable_label`은 locator evidence이지 identity가 아니다.
- bounds, resource id, class, observation order, viewport evidence를 함께 본다.
- label-only dedupe는 금지했다.

### 4.2 Display Name을 classifier score에 넣지 않았다

이 결정은 구현 과정에서 여러 번 유혹이 있었지만 끝까지 유지했다.

- display name은 locator에는 유용하다.
- 그러나 classifier score에 들어가면 V10이 legacy naming bias를 다시 학습하게 된다.
- 그렇게 되면 MATCH가 높아져도 "display name에 다시 의존한 MATCH"가 될 수 있다.

그래서 display/legacy hint는 shadow comparison과 tie-break 참고 자료로만 남기고,
Quick Identify의 primary evidence는 capability resource-id, XML structure,
header/title, talkback/helper evidence로 제한했다.

### 4.3 Policy Registry를 별도 버전 레이어로 뒀다

Identify 결과를 곧바로 scenario로 바꾸지 않고, versioned registry를 통과시키도록
했다. 이 설계는 나중에 매우 중요해졌다.

- capability family와 scenario granularity가 항상 1:1이 아니었다.
- confidence band, disabled entry, unsupported family를 명시적으로 모델링할 수 있었다.
- routing eligibility와 identification success를 분리할 수 있었다.
- V11에서 family allowlist pilot을 시작할 기반이 생겼다.

### 4.4 Shadow Compare와 Promotion을 분리했다

`MATCH == promote`로 가지 않은 것은 옳았다.

- MATCH는 agreement일 뿐 correctness proof가 아니다.
- UNKNOWN이 많은 family는 MATCH 몇 건이 있어도 production promotion 근거가 부족하다.
- Shadow compare와 promotion gate를 섞으면 운영 pressure 때문에 premature rollout이
  발생한다.

그래서 V10은 shadow artifact와 readiness artifact를 별도로 만들었다.

## 5. Major Bugs Encountered

이 섹션은 V10에서 실제로 비용이 컸던 버그들만 남긴다.

### 5.1 Inventory viewport origin mismatch

원인:

- inventory item의 bounds/viewport interpretation과 identify/restore 단계의 재탐색
  기준이 완전히 같은 origin을 공유하지 않는 순간이 있었다.
- 결과적으로 같은 card를 보고도 이후 단계에서 같은 대상을 못 찾거나, 인접 card를
  같은 것으로 잘못 취급할 위험이 생겼다.

해결:

- inventory에서 viewport index, observation order, bounds, structure evidence를 함께
  보존했다.
- quick identify와 shadow compare는 항상 `inventory_id + runtime_card_id`를 기준으로
  연결하고, display label만으로 재연결하지 않도록 고정했다.

Lessons Learned:

- scrollable UI에서 "현재 보이는 card"는 이름보다 좌표와 관찰 맥락이 더 중요하다.
- identity contract를 먼저 고정하지 않으면 이후 layer의 정확도는 의미가 없다.

### 5.2 `runtime_card_viewport_repeated`

원인:

- bounded scroll 중 같은 viewport가 반복 관찰되는 경우가 있었고, 초기 구현은 이를
  scroll 진행으로 오해할 수 있었다.
- repeated viewport가 새 card discovery처럼 보이면 inventory count가 부풀고,
  downstream comparison도 오염된다.

해결:

- viewport signature와 observation fingerprint를 도입했다.
- repeated viewport는 termination/diagnostic signal로 취급하고, 반복 관찰만으로 새
  runtime card를 만들지 않도록 했다.

Lessons Learned:

- inventory scanner는 "새로운 화면을 봤다"와 "같은 화면을 다시 봤다"를 명확히 구분해야
  한다.
- scan termination은 max scroll count보다 evidence-driven repeated viewport detection이
  더 중요하다.

### 5.3 Inventory boundary duplicate

원인:

- viewport 경계에서 같은 physical card가 두 번 수집됐다.
- 특히 card가 경계에 걸쳐 있거나 lazy layout으로 bounds가 미세하게 달라질 때
  duplicate merge가 어려웠다.

해결:

- Sprint 4.7에서 conservative boundary duplicate merge를 별도 수정으로 넣었다.
- label-only, bounds-only, resource-id-only merge를 금지했다.
- 인접 viewport, clipping, structure similarity, bounds proximity, observation order가
  함께 맞을 때만 merge했다.
- merge reason과 identity diagnostics를 artifact에 남겼다.

Lessons Learned:

- aggressive dedupe는 다른 기기를 합쳐 버리고, weak dedupe는 같은 기기를 둘로
  쪼갠다.
- inventory dedupe는 recall보다 correctness를 우선해야 한다.

### 5.4 Door Lock duplicate MATCH

원인:

- duplicate inventory item이 남아 있으면 shadow comparison이 같은 physical card에 대해
  두 번 MATCH를 계산할 수 있었다.
- 이 문제는 "좋아 보이는 결과"를 만들기 때문에 더 위험했다. mismatch보다 찾기
  어려웠다.

해결:

- comparison unit을 `inventory_id + runtime_card_id`로 다시 엄격히 정의했다.
- duplicate inventory 원인을 upstream에서 줄이고, downstream에서는 identity mismatch를
  `FAILED`로 분리해 metric inflation을 막았다.

Lessons Learned:

- false positive MATCH는 MISMATCH보다 더 해롭다.
- promotion gating을 만들기 전에 denominator integrity를 먼저 지켜야 한다.

### 5.5 Devices surface 복귀 실패

원인:

- quick identify는 card를 잠깐 열고 helper/XML/capability evidence를 수집한 뒤 다시
  Devices surface로 복귀해야 한다.
- 실제 장비에서는 back 후 원래 inventory context가 바로 복구되지 않거나, 대상 card가
  viewport 밖으로 밀리거나, location/filter state가 흔들리는 경우가 있었다.

해결:

- quick identify 결과에 `restore_success`와 restore diagnostics를 넣었다.
- 복귀 검증이 실패하면 classifier score가 아무리 좋아도 `failed`로 강등했다.
- bounded rescan을 허용하되, 복귀 불확실 상태에서 traversal을 시작하지 않았다.

Lessons Learned:

- post-open identify의 난점은 분류가 아니라 lifecycle 복구다.
- card를 여는 것보다 "같은 Devices surface로 안전하게 돌아왔는가"를 검증하는 것이
  더 중요하다.

### 5.6 Shadow pipeline 예외 전파와 `shadow_error` artifact

원인:

- shadow pass는 Legacy Full Run 뒤에 추가로 실행되므로, 여기서 예외가 나면 잘못하면
  Legacy 결과까지 실패처럼 보일 수 있었다.

해결:

- shadow pipeline failure를 `shadow_error.json`과 warning log로 격리했다.
- `legacy_result_preserved=true`를 명시적으로 기록했다.
- UI와 API도 shadow artifact가 없거나 실패한 경우를 별도 상태로 다루도록 만들었다.

Lessons Learned:

- comparison-only 계층은 production path를 절대 오염시키면 안 된다.
- "실패해도 안전한 shadow pass"를 먼저 만들지 않으면 실기기 검증을 빠르게 돌릴 수
  없다.

## 6. Shadow-only Runner

V10 개발 중 가장 생산성이 컸던 도구는 shadow-only runner였다.

초기에는 V10 문제 하나를 보기 위해 Legacy Full Run 전체를 다시 돌려야 했고, 이 비용은
대략 `3500s` 수준까지 올라갔다. Shadow-only runner를 추가한 뒤에는 기존 run
artifact를 재사용해 shadow pass만 다시 실행할 수 있게 되었고, 실질적인 반복 시간이
대략 `420s` 수준으로 내려갔다.

왜 중요했는가:

- inventory/identify/policy/shadow 버그를 traversal noise 없이 재검증할 수 있었다.
- QA Frontend 전체를 거치지 않고 artifact replay가 가능했다.
- duplicate merge, readiness gate, UI summary 같은 후반 작업의 iteration 속도가
  크게 개선됐다.

이 도구는 단순한 편의 기능이 아니라, V10이 "shadow architecture를 운영 가능한 속도로
검증하는 체계"로 바뀌는 전환점이었다.

## 7. Engineering Lessons

### 7.1 Display Name은 identity가 될 수 없다

display name은 locator로는 충분히 쓸 수 있지만, semantic identity로 사용하면
사용자 rename과 locale drift를 routing bug로 바꾸게 된다.

### 7.2 Fail-closed가 맞았다

V10은 unknown, ambiguous, restore failure를 모두 production route 불가로 다뤘다.
이 때문에 READY count가 천천히 늘었지만, 반대로 "부분적으로 맞아 보이는 V10 route"가
운영 path에 섞이는 일은 막을 수 있었다.

### 7.3 Layer 분리는 디버깅을 위한 설계이기도 하다

Inventory, Identify, Registry, Shadow, Promotion을 나눈 이유는 추상화 취향이 아니라
문제 분리를 위해서였다. 실제로 boundary duplicate, restore failure, registry hold,
QA reporting 이슈를 서로 다른 layer에서 독립적으로 수정할 수 있었다.

### 7.4 Shadow를 먼저 만든 이유는 옳았다

Controlled Routing을 먼저 시도했다면, inventory bug와 identify bug가 전부 traversal
regression처럼 보였을 것이다. Shadow compare를 먼저 완성했기 때문에 MATCH,
UNKNOWN, FAILED를 실기기에서 안전하게 누적할 수 있었다.

### 7.5 Feature Flag 기본 OFF는 단순 보수주의가 아니다

run-local flag만 켜고 source runtime config는 바꾸지 않는 원칙 덕분에, QA Frontend
실험과 mainline 운영 구성이 충돌하지 않았다. Shadow Validation이 experimental이어도
기존 Full Run 운영 절차를 깨지 않았다.

### 7.6 Legacy authoritative 유지가 속도를 올렸다

처음 보기에는 병행 운영이 느려 보이지만, 실제로는 그렇지 않았다. Legacy 결과를 기준
축으로 유지했기 때문에 V10 layer는 자유롭게 깨보고 고칠 수 있었고, 회귀 판단도 더
명확해졌다.

## 8. Validation History

### 8.1 Sprint timeline

```text
Sprint 0
-> preparation scaffolding / version / flags / fixture boundary

Sprint 1
-> runtime device inventory

Sprint 2
-> quick plugin identify

Sprint 3
-> policy registry

Sprint 4
-> shadow validation pipeline

Sprint 4.6
-> shadow-only runner

Sprint 4.7
-> conservative inventory boundary duplicate fix

Sprint 5
-> QA Frontend shadow reporting

Sprint 6
-> promotion readiness reporting

Documentation / Closure
-> phase closure, architecture refresh, operational docs
```

### 8.2 실기기 검증에서 확인한 것

- Inventory path가 bounded scan으로 실제 visible device card를 수집한다.
- Quick Identify가 display name이 아니라 capability/XML evidence로 family를 분류한다.
- Shadow compare가 Legacy와 V10을 같은 runtime card 기준으로 비교한다.
- mismatch와 failed가 없을 때도 UNKNOWN family가 promotion blocker로 남을 수 있다.
- QA Frontend가 shadow compare와 promotion readiness를 별도 card로 보여 준다.

### 8.3 최종 상태

최종 검증 요약:

- Inventory: `15`
- MATCH: `6`
- UNKNOWN: `9`
- MISMATCH: `0`
- FAILED: `0`
- Shadow Validation: `PASS`
- Promotion Readiness: `HOLD`
- READY candidate: `5`

이 결과는 "V10 shadow architecture가 안전하게 동작한다"는 의미이지, "V10 route가
production truth가 되었다"는 뜻은 아니다.

## 9. Known Limitations

V10 종료 시점에도 다음 한계는 의도적으로 남겨 두었다.

- UNKNOWN family가 여전히 크다.
- Camera, Audio, Humidity 등은 capability evidence 또는 cohort가 아직 약하다.
- MATCH가 있어도 표본이 작으면 promotion은 계속 `HOLD`다.
- Controlled Routing은 구현하지 않았다.
- Legacy display-name locator 의존성은 runtime traversal entry에서 여전히 남아 있다.
- multi-run corpus 축적과 drift monitoring이 부족하다.

즉 V10은 "routing replacement"가 아니라 "routing replacement를 평가할 수 있는
measurement system"까지 완성한 상태다.

## 10. Future Work (V11)

V11에서 가장 직접적으로 이어질 일은 Controlled Routing pilot이다. 다만 V10의
교훈대로, 모든 family를 한 번에 전환하면 안 된다.

우선순위:

- family allowlist 기반 Controlled Routing pilot
- capability-first traversal entry 실험
- Promotion HOLD family의 evidence 보강
- UNKNOWN family reduction
- readiness cohort 누적과 drift tracking
- rollback / kill switch 운영 검증

V11은 "V10이 충분히 맞았는가"보다 "어떤 family를 어떤 cohort에서 제한적으로 켤 수
있는가"를 묻는 단계가 되어야 한다.

## 11. Lessons for Future Projects

가장 성공적이었던 점:

- production path를 건드리지 않고 shadow architecture를 완성한 것
- runtime identity contract를 별도로 만든 것
- shadow-only runner로 iteration cost를 줄인 것
- UI reporting까지 연결해 engineering-only artifact로 끝나지 않게 한 것

아쉬웠던 점:

- duplicate/boundary 문제를 Sprint 1에서 더 빨리 공격했어야 했다.
- final validation numbers와 sample payload 문서 사이의 용어 차이를 더 일찍
  정리했어야 했다.
- UNKNOWN family를 줄이기 위한 corpus 전략이 구현 후반까지 뒤로 밀렸다.

다시 한다면:

- inventory identity diagnostics를 처음부터 더 풍부하게 남긴다.
- real-device restore failure replay fixture를 더 일찍 만든다.
- promotion gate와 reporting schema를 설계 초기에 더 강하게 고정한다.
- shadow-only replay 도구를 Sprint 4보다 더 앞당긴다.

## 12. What V11 Should Remember

V11에 가장 큰 영향을 줄 한 문장은 이것이다.

```text
V10의 핵심 산출물은 새로운 routing이 아니라,
새로운 routing을 안전하게 평가할 수 있는 운영 가능한 shadow system이다.
```

따라서 V11은 기능 확장보다도 다음 원칙을 유지해야 한다.

- legacy baseline 유지
- family/cohort 제한 pilot
- fail-closed 유지
- shadow evidence와 promotion evidence 분리
- agreement와 correctness를 혼동하지 않기

이 원칙을 깨면 V10이 어렵게 만든 안전한 관측 계층이 다시 사라진다.
