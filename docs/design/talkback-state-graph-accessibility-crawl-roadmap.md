# State-Graph 기반 자동 Accessibility Crawl 로드맵

> **미래 architectural direction**
>
> 이 문서는 현재 production traversal이 State-Graph crawl로 바뀌었다는 뜻이 아니다.
> 현재 authoritative behavior는 [운영 Runbook](../operations/talkback-operational-runbook.md),
> [시스템 개요](../system-overview.md), [아키텍처](../architecture.md)와 current source가
> 정의한다. 아래 내용은 현재 Audit, Traversal Identity, SMART_NEXT, Evidence,
> Reconciliation 자산을 바탕으로 향후 검토할 방향이다.

## 1. 목적과 범위

현재 시스템은 scenario-driven traversal을 중심으로 화면 진입과 accessibility 수집을
수행한다. 장기적으로는 의미 있는 화면/state에 도달한 뒤 현재 accessibility 상태를
동적으로 발견하고, 실제 TalkBack focus가 방문한 결과와 expected candidate를
reconcile하는 **State-Graph-driven accessibility crawl**을 검토한다.

이 문서는 설계 방향과 문제 정의를 기록한다. 구현이 시작되었거나 확정된 알고리즘,
정확한 phase 경계, 일정, 절감률을 주장하지 않는다. 구현 feasibility와 phase boundary는
별도의 current-code gap analysis와 code-level design을 거쳐야 한다.

## 2. 유지보수가 필요한 현재 문제

앱 version, plugin UI 구조, resource ID, anchor, navigation path, dynamic content와
내부 object hierarchy가 바뀌면 현재 automation은 다음을 다시 조정해야 할 수 있다.

```text
resource-id / anchor / known target
  -> predefined object 찾기
  -> scenario 규칙에 따라 traversal
  -> 변경된 UI에 맞춰 target/path/scroll 예외 수정
```

목표는 maintenance를 없애는 것이 아니다. 개별 accessibility object 정의를 매번
유지하는 부담을 줄이고, 유지보수의 중심을 다음으로 옮기는 것이다.

```text
individual object definitions
  -> screen entry + exceptional navigation/policy rules
```

화면까지 가는 navigation이 바뀌거나 destructive action 정책이 바뀌는 경우에는 여전히
명시적인 유지보수가 필요하다.

## 3. 목표 discovery model

향후 logical flow는 다음과 같다.

```text
1. 화면/state 도달
2. Accessibility Tree / XML 수집
3. 검증 대상 candidate 자동 생성
4. 실제 TalkBack traversal 수행
5. 실제 focus와 candidate identity 매칭
6. expected accessibility information 구성
7. 실제 TalkBack speech 수집 및 비교
8. expected candidate인데 방문되지 않음 -> MISSED
9. TalkBack이 방문했지만 candidate에 없음 -> UNEXPECTED
10. 상태 변경 후 tree를 다시 수집하고 반복
```

Candidate는 XML node 하나와 일대일로 고정하지 않는다. 다음과 같은 signal을 조합할 수
있다.

- `focusable`, `clickable`
- text, `contentDescription`
- role, selected state
- accessibility metadata와 parent/child 관계
- 현재 화면/state, bounds와 temporal observation

가능한 conceptual result는 다음과 같다.

```text
17 expected accessibility candidates
16 actually visited
1 MISSED
```

또는 실제 TalkBack이 candidate inventory에 없는 대상을 방문한 경우:

```text
16 expected candidates
17 TalkBack visits
1 UNEXPECTED
```

이는 현재 `Coverage`/`Reconciliation`의 역할을 확장해 표현한 목표 모델이며, 위 숫자는
새 acceptance 결과가 아니다.

## 4. 어려운 accessibility 표현

동적 discovery가 단순 XML node 수집으로 끝나지 않도록 다음을 exceptional/fallback
영역으로 명시한다.

- WebView와 Compose semantics
- custom View
- merged parent/child accessibility node
- lazy-loaded content와 scroll로 생성되는 object
- dynamic state와 일시적으로 나타나는 content
- duplicated label과 서로 다른 identity
- popup/overlay

정상적인 object를 모두 hardcode하는 대신, 이런 표현에서는 identity confidence,
parent/child evidence, temporal stability, state change와 recovery policy를 함께 판단해야
한다. 이것은 아직 확정된 구현 알고리즘이 아니며 후속 contract가 필요한 부분이다.

## 5. 기존 Audit과 SMART_NEXT를 잇는 계보

기존 Audit은 제거 대상이 아니다. 향후 역할은 다음처럼 연결된다.

```text
Audit / Candidate Discovery
  -> potential expected candidates 정의

Smart Traversal
  -> TalkBack이 실제로 방문한 대상을 관찰

Speech / Evidence
  -> 실제로 노출된 speech, focus, visible information 기록

Reconciliation
  -> expected candidate와 actual traversal 비교
```

초기 Smart Move의 직관은 다음과 같았다.

```text
current focus -> next object -> scroll if needed -> continue
```

현재 구현은 이 개념을 넘어 Accessibility Tree 분석, focus identity, candidate 평가,
duplicate/header/bottom-navigation 처리, scroll 후 rediscovery, focus verification,
recovery/reconciliation을 갖춘 경로로 발전해 왔다. Helper에는 `SMART_NEXT`와 관련
action contract가 있지만, 모든 현재 move가 SMART_NEXT를 사용하는 것은 아니다.
강한 deterministic target method가 필요한 경로와 SMART_NEXT/fallback 경로의 구분은
보존한다.

향후에는 동적 traversal capability를 더 중심에 둘 수 있다.

```text
Screen reached
  -> automatic candidate discovery
  -> SMART_NEXT / production traversal
  -> scroll-inclusive full traversal
  -> speech/evidence capture
  -> candidate reconciliation
```

위 흐름은 목표 architecture이며 현재 모든 scenario의 실행 경로를 설명하는 문장이
아니다.

## 6. Navigation과 Accessibility Audit의 분리

### Navigation layer

목적은 의미 있는 screen/state에 도달하는 것이다.

```text
Home -> Devices -> specific plugin -> device detail
```

이 계층에서는 anchors, stable semantic labels, screen identity, explicit routes와
bounded fallback logic을 계속 사용할 수 있다. 화면 진입이 실패하면 audit을 시작할
수 없기 때문이다.

### Accessibility Audit layer

target screen에 도달한 뒤에는 다음 흐름을 우선한다.

```text
current state
  -> discover current objects
  -> dynamically traverse TalkBack focus
  -> collect speech/evidence
  -> compare and reconcile
```

핵심 목표는 **UI 변경이 screen으로 가는 path를 깨뜨릴 수는 있어도, 그 screen 내부의
모든 object를 다시 등록하게 만들지는 않는 것**이다. Navigation은 사라지지 않고,
화면 내부 검증이 Discovery/Traversal 중심으로 이동한다.

## 7. Safe Navigation Candidate model

일부 accessibility state는 interaction 뒤에 더 많은 content를 노출한다. bottom tab,
More, expandable section, accordion, sub-page와 informational menu entry가 그 예다.
따라서 발견된 interactive object를 개념적으로 다음 세 종류로 나눈다.

### Traversal Object

읽고 검증하지만 generic crawler가 activate하지 않는 object다. text, label,
informational control처럼 activation이 필요하지 않은 대상이 여기에 해당할 수 있다.

### Safe Navigation Object

다른 accessibility state를 보여 주기 위해 자동 activation을 검토할 수 있는 object다.
tab, More, Expand, non-destructive information page, safe submenu가 예다. 자동 실행
전에는 safety policy와 state-change verification이 필요하다.

### Action Object

generic crawl이 자동 activation하지 않아야 하는 object다.

- ON/OFF, delete, reset, save
- payment, purchase, factory reset
- 기타 destructive 또는 state-changing control

Action Object는 미래의 명시적인 safety policy가 허용하지 않는 한 scenario/policy의
명시적 제어 아래 둔다. clickable이라는 사실만으로 Safe Navigation Object가 되지 않는다.

## 8. State-Graph model

향후 화면/state exploration은 다음과 같은 bounded graph로 표현할 수 있다.

```text
Device Detail
 ├─ Main tab
 │   └─ accessibility objects automatically audited
 ├─ Energy tab
 │   └─ accessibility objects automatically audited
 └─ More
     ├─ Information
     │   └─ accessibility objects automatically audited
     └─ Settings
         └─ accessibility objects automatically audited
```

가능한 logical loop는 다음과 같다.

```text
current state
  -> discover unvisited Safe Navigation Candidate
  -> activate
  -> detect screen/state fingerprint change
  -> register new state
  -> run Audit + Traversal again
  -> continue bounded graph exploration
```

정확한 state fingerprint, loop prevention, depth/exploration budget, action safety,
recovery와 rollback 정책은 후속 design/gap-analysis에서 결정해야 한다. 이 문서는 특정
그래프 탐색 알고리즘을 최종 확정하지 않는다.

## 9. 목표 architecture와 기대 효과

```text
Explicit Navigation
        ↓
Target Screen / State
        ↓
Audit Candidate Discovery
        ↓
Dynamic TalkBack Traversal
        ↓
Scroll / Rediscovery
        ↓
Speech + Focus + Visible Evidence
        ↓
Coverage / Reconciliation
        ↓
Safe Navigation Discovery
        ↓
Next State
        ↺
```

기본 원칙은 다음과 같다.

```text
automatic discovery first
  -> semantic matching
  -> actual TalkBack traversal
  -> exceptional cases only use anchor/resource-id/special policy
```

이는 기존 architecture를 처음부터 다시 쓰는 계획이 아니라 Audit, Traversal Identity,
SMART_NEXT, Evidence, Reconciliation을 통합·확장하는 방향이다.

현재 app update는 individual target, resource ID, internal object path, scroll rule,
scenario-specific traversal 수정을 요구할 수 있다. 장기적으로는 top-level screen
navigation, screen identity, exceptional component, Safe Navigation classification,
destructive-action policy에 maintenance를 집중하고, ordinary object는 재발견하는 것을
기대한다. savings는 측정 전까지 수치화하지 않는다.

## 10. 성숙도와 다음 검토

### 현재 기반

현재 source와 operational contract에서 확인되는 재사용 가능한 기반이다.

- Accessibility Tree/XML observation
- Audit candidate/coverage와 bounded probe
- Traversal Identity와 Production Traversal
- SMART_NEXT-related helper/traversal capability
- scrolling, recovery, focus verification
- speech/evidence collection
- reconciliation과 QA review projection

이 항목들이 State-Graph crawl을 이미 구현했다는 뜻은 아니다.

### 다음 검토

- current-screen accessibility candidate contract
- candidate identity와 expected accessibility information
- candidate ↔ actual-focus reconciliation 및 `MISSED`/`UNEXPECTED` semantics
- generic Safe Navigation classification
- state fingerprint contract
- bounded state-graph traversal과 exploration budget
- WebView/Compose/merged-node/lazy-content fallback gap analysis

### 중장기 방향

- broader automatic accessibility crawl
- plugin/version resilience
- multi-device/locale adaptation
- scenario-specific object maintenance 감소
- evidence-driven state-graph coverage
- sufficiently validated automatic traversal의 controlled promotion

정확한 phase number와 delivery date는 후속 gap analysis 이후에 정한다.

## 11. Source boundary

현재 구현과 운영 절차는 [운영 Runbook](../operations/talkback-operational-runbook.md),
[QA validation contract](../../qa_frontend/VALIDATION.md),
[V8 coverage design](v8-coverage-driven-traversal.md),
[Production Traversal Migration](talkback-production-traversal-migration.md),
[system overview](../system-overview.md), [architecture](../architecture.md)를 참조한다.
Phase acceptance 수치는 이 future roadmap의 구현 증거로 재사용하지 않는다.
