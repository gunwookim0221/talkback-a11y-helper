# V10 Policy Mapping Design

| Metadata | Value |
| --- | --- |
| Status | Completed |
| Phase | V10 Phase 3 |
| Owner | TalkBack Automation |
| Last Updated | 2026-06-30 |
| Depends On | [V10 Quick Plugin Identify Design](v10-quick-plugin-identify-design.md) |
| Related Documents | [V10 Overview](v10-overview.md), [V10 Phase Plan](v10-phase-plan.md), [V10 Device Inventory Design](v10-device-inventory-design.md), [V10 Shadow Validation Design](v10-shadow-validation-design.md) |
| Next | [V10 Shadow Validation Design](v10-shadow-validation-design.md) |

## 1. Purpose

Policy Mapping은 Quick Identify가 반환한 plugin candidate를 기존 Scenario Policy에
안전하게 연결하는 Architecture Contract다.

Legacy routing은 display name으로 card와 scenario를 동시에 결정한다.

```text
Display Name
-> Scenario Policy
-> Existing Traversal Engine
```

이 구조에서는 display name이 locator와 plugin identity 역할을 모두 담당한다.
사용자가 이름을 변경하면 올바른 Scenario Policy가 존재해도 선택하지 못할 수 있다.

V10은 card 관찰, plugin 식별, policy 선택을 분리한다.

```text
Device Inventory
-> Quick Plugin Identify
-> Policy Mapping
-> Existing Traversal Engine
```

Policy Mapping의 책임은 식별된 canonical plugin type/capability family를 현재
Repository의 Scenario Policy에 연결하고, traversal을 시작해도 되는지 결정하는
것이다. Traversal Engine과 Scenario Policy의 내부 동작은 변경하지 않는다.

Policy Mapping은 Quick Identify evidence를 재해석하는 classifier가 아니다. 입력
decision과 confidence를 검증하고, versioned registry에서 deterministic한 mapping을
선택하거나 legacy fallback/skip을 반환한다.

## 2. Input Contract

입력은 [V10 Quick Plugin Identify Design](v10-quick-plugin-identify-design.md)의
Quick Identify Result다.

| Field | Required | Purpose |
| --- | --- | --- |
| `schema_version` | Yes | Quick Identify contract 호환성 확인 |
| `identify_run_id` | Yes | selection 결과를 identify attempt와 연결 |
| `inventory_id` | Yes | 원본 Inventory 연결 |
| `runtime_card_id` | Yes | 대상 runtime card 연결 |
| `decision` | Yes | `identified`, `unknown`, `ambiguous`, `failed` |
| `plugin_type` | Yes | canonical plugin type 또는 `unknown` |
| `scenario_candidate` | No | Quick Identify의 advisory candidate |
| `confidence_score` | Yes | bounded evidence score |
| `confidence_band` | Yes | `definite`, `high`, `medium`, `low`, `unknown` |
| `candidates` | Yes | 후보별 score, quality gate, conflict 정보 |
| `evidence` | Yes | normalized evidence records |
| `contradictions` | Yes | strong/weak contradiction 목록 |
| `stabilization` | Yes | plugin 화면 안정화 결과 |
| `restoration` | Yes | Inventory context 복귀 결과 |
| `legacy_hint` | No | shadow 비교용 legacy scenario/label |
| `errors` | Yes | lifecycle 및 capture error |

### 2.1 Input Gates

Policy Mapping은 다음 조건을 먼저 검증한다.

- 입력 schema version을 지원한다.
- `identify_run_id`, `inventory_id`, `runtime_card_id`가 누락되지 않았다.
- restoration이 성공하여 traversal 시작 위치가 유효하다.
- `identified` 결과는 하나의 top candidate와 통과된 structural quality gate를 가진다.
- confidence band와 score가 서로 모순되지 않는다.
- `scenario_candidate`는 registry 결과를 강제하지 않는다.

`unknown`, `ambiguous`, `failed`는 정상적인 입력 상태다. 이를 임의의 plugin type으로
보정하지 않는다.

## 3. Output Contract

### 3.1 Traversal Policy Selection

| Field | Required | Description |
| --- | --- | --- |
| `schema_version` | Yes | Policy Selection result schema version |
| `selection_id` | Yes | 한 번의 mapping decision 식별자 |
| `identify_run_id` | Yes | 입력 Quick Identify Result 연결 |
| `inventory_id` | Yes | 원본 Inventory 연결 |
| `runtime_card_id` | Yes | 대상 card 연결 |
| `decision` | Yes | `v10_route`, `legacy_fallback`, `shadow_only`, `skip` |
| `scenario_id` | No | 선택된 기존 scenario; skip이면 empty |
| `policy_version` | No | 선택된 Scenario Policy의 behavior version |
| `registry_version` | Yes | registry schema/contract version |
| `mapping_revision` | Yes | mapping content revision |
| `routing_rule_version` | Yes | confidence/action rule version |
| `matched_registry_key` | No | 선택에 사용된 capability/plugin type key |
| `routing_reason` | Yes | V10 route, fallback, shadow, skip 사유 |
| `identify_decision` | Yes | 원본 identify decision |
| `identify_confidence` | Yes | 원본 score와 band |
| `mapping_confidence` | Yes | `definite`, `high`, `shadow`, `none` |
| `traversal_allowed` | Yes | 이 selection으로 traversal 시작 가능 여부 |
| `fallback_reason` | No | legacy fallback을 선택한 이유 |
| `legacy_locator` | No | fallback에 사용할 display-name locator evidence |
| `conflict_status` | Yes | `none`, `resolved`, `ambiguous`, `blocked` |
| `evidence_refs` | Yes | mapping 근거가 된 identify evidence IDs |
| `shadow_status` | No | legacy와 mapping 비교 결과 |
| `created_at` | Yes | selection 생성 시각 |
| `diagnostics` | Yes | registry miss, version mismatch 등 진단 |

### 3.2 Decision Semantics

- `v10_route`: registry와 confidence gate가 모두 통과되어 선택된 기존 scenario로
  traversal을 시작할 수 있다.
- `legacy_fallback`: V10 mapping은 확정하지 못했지만 strict legacy 조건을 만족해
  기존 display-name locator와 scenario를 사용할 수 있다.
- `shadow_only`: mapping 후보를 기록하지만 V10 결과로 traversal을 시작하지 않는다.
  운영 baseline인 legacy path가 별도로 유효하면 그대로 실행할 수 있다.
- `skip`: 어떤 scenario도 안전하게 선택하지 않으며 traversal을 시작하지 않는다.

`scenario_id`는 기존 Scenario Policy를 참조한다. Policy Mapping이 새로운 traversal
policy를 동적으로 생성하지 않는다.

## 4. Lifecycle

```text
Inventory
-> Quick Identify
-> Policy Mapping
   -> V10 Route -> Existing Traversal Start
   -> Legacy Fallback -> Existing Traversal Start
   -> Shadow Only -> Record Mapping, Keep Baseline Behavior
   -> Skip -> No Traversal
```

### Validate Input

Quick Identify contract version, lifecycle restoration, decision, confidence와 evidence
quality gate를 확인한다. 유효하지 않은 입력은 registry lookup 전에 skip한다.

### Resolve Registry

canonical `plugin_type`을 exact registry key로 조회한다. alias text나 display name으로
registry를 fuzzy search하지 않는다. 여러 mapping이 있으면 discriminator와 conflict
rule을 적용한다.

### Apply Routing Rule

identify confidence, registry의 confidence requirement, mapping status와 conflict를
결합하여 `v10_route`, `legacy_fallback`, `shadow_only`, `skip` 중 하나를 선택한다.

### Emit Selection

선택한 scenario와 모든 version, reason, evidence reference를 immutable selection
record로 남긴다. 이후 Existing Traversal Engine은 선택된 기존 scenario를 입력으로
받는다.

## 5. Policy Registry

Policy Registry는 Quick Identify의 canonical capability/plugin type과 기존 Scenario
Policy 사이의 versioned allowlist다.

Capability 이름은 V10 mapping key다. 현재 `scenario_config`의 필드나 Android platform
capability 명칭으로 간주하지 않는다. 실제 registry 승격 전에는 snapshot corpus에서
Quick Identify signature와 scenario compatibility를 검증해야 한다.

### 5.1 Policy Registry

| Capability | Scenario | Confidence Requirement | Notes |
| --- | --- | --- | --- |
| `SmokeDetectorCapability` | `device_smoke_sensor_plugin` | Definite or High | `SmokeSensorCapabilityCardView` 계열의 structural evidence 필요 |
| `LeakSensorCapability` | `device_water_leak_sensor_plugin` | Definite or High | `WaterSensorCapabilityCardView`와 leak/wet/dry discriminator 필요 |
| `MotionSensorCapability` | `device_motion_sensor_plugin` | Definite or High | `MotionSensorCapabilityCardView`를 primary signature로 사용 |
| `GenericLockCapability` | `device_door_lock_plugin` | Definite or High | `LockCapabilityCardView`와 lock state/control 구조 필요 |
| `AirPurifierCapabilitySet` | `device_air_purifier_plugin` | Definite or High | air quality만으로 부족하며 purifier control signature 필요 |
| `TVCapabilitySet` | `device_tv_plugin` | Definite or High | remote/channel/source/volume의 검증된 조합 필요 |
| `LaundryWasherCapability` | `device_washer_plugin` | Definite or High | washer-specific laundry/cycle/rinse/spin 구조 필요 |
| `HumiditySensorCapability` | `device_humidity_sensor_plugin` | Definite or High | humidity-only primary sensor임을 구분해야 함 |
| `TemperatureHumiditySensorCapabilitySet` | `device_temperature_humidity_sensor_plugin` | Definite or High | 동일 primary sensor의 temperature+humidity 구조가 필요 |
| `CameraCapabilitySet` | `device_camera_plugin` | Definite or High | generic camera stream/control signature; Home Camera와 discriminator 필요 |
| `HomeCamera360CapabilitySet` | `device_home_camera_plugin` | Definite | Home Camera 360 전용 signature가 검증된 경우만 허용 |
| `AudioCapabilitySet` | `device_audio_plugin` | Definite or High | media/audio control 구조가 필요; TV와 discriminator 필요 |

### 5.2 Registry Entry Contract

각 registry entry는 최소한 다음 값을 가진다.

| Field | Description |
| --- | --- |
| `registry_key` | canonical capability/plugin type |
| `scenario_id` | 기존 Scenario Policy ID |
| `status` | `shadow`, `eligible`, `disabled`, `deprecated` |
| `minimum_confidence` | `definite` 또는 `high` |
| `required_evidence_classes` | 반드시 포함할 structural evidence 종류 |
| `forbidden_conflicts` | route를 차단하는 contradiction |
| `discriminators` | 겹치는 mapping을 구분하는 조건 |
| `precedence` | multi-capability conflict에서 검증된 우선순위 |
| `policy_version` | 참조 Scenario Policy behavior version |
| `mapping_revision` | 해당 mapping이 검증된 revision |

Registry에 scenario가 존재한다는 사실만으로 routing을 허용하지 않는다. entry
`status=eligible`, confidence requirement 충족, conflict 없음이 모두 필요하다.

## 6. Routing Rules

### 6.1 Routing Decision Matrix

| Identify Result | Action | Traversal | Legacy | Notes |
| --- | --- | --- | --- | --- |
| `identified` + Definite + eligible exact mapping | `v10_route` | Start | Not used | 가장 강한 structural evidence와 registry 조건 충족 |
| `identified` + High + eligible mapping | `v10_route` | Start allowed | Not used | shadow validation을 통과하고 registry가 High를 허용한 family만 |
| `identified` + Medium | `shadow_only` | V10 start prohibited | Baseline may continue | 후보는 비교 기록만 수행 |
| `identified` + Low | `legacy_fallback` 또는 `skip` | V10 start prohibited | Strict fallback only | 약한 V10 결과를 routing 근거로 사용하지 않음 |
| `unknown` | `legacy_fallback` 또는 `skip` | V10 start prohibited | Strict fallback only | identify evidence 부족 |
| `ambiguous` | `legacy_fallback` 또는 `skip` | V10 start prohibited | Strict fallback only | legacy와 strong contradiction이 있으면 skip |
| `failed` | `skip` | Prohibited | Prohibited | lifecycle/context 신뢰 불가 |
| Any + registry miss/disabled | `shadow_only` 또는 `skip` | Prohibited | Strict fallback only | 임의 scenario 생성 금지 |
| Any + restoration failed | `skip` | Prohibited | Prohibited | Inventory/traversal 시작 context가 안전하지 않음 |

### 6.2 Rationale

- **Definite**: 독립된 강한 structural evidence가 일치하므로 eligible registry
  mapping을 production candidate로 사용할 수 있다.
- **High**: 충분한 구조 근거가 있으나 family별 shadow validation과 registry 승격이
  완료된 경우에만 traversal을 허용한다.
- **Medium**: plausible candidate지만 오탐 비용이 크므로 V10 route에 사용하지 않는다.
- **Unknown**: classifier가 정보를 제공하지 못했으므로 기존 routing을 안전 조건
  아래 유지할 수 있다.
- **Ambiguous**: 복수 후보를 임의 선택하지 않는다. legacy가 독립적으로 유효하고
  strong contradiction이 없을 때만 fallback한다.
- **Failed**: 화면 context나 lifecycle이 손상되었을 수 있으므로 legacy도 실행하지
  않고 skip한다.

High confidence는 전역적으로 자동 허용하지 않는다. registry entry가
`minimum_confidence=high`이고 해당 family의 shadow validation이 완료된 경우에만
`v10_route`가 가능하다.

## 7. Legacy Fallback

Display name은 plugin identity가 아니라 기존 card를 다시 찾기 위한 fallback
locator다.

Legacy fallback은 다음 조건을 모두 만족할 때만 허용한다.

- Quick Identify decision이 `unknown`, `ambiguous`, Low 또는 registry miss다.
- Quick Identify lifecycle과 Inventory restoration은 성공했다.
- 현재 account/location/filter context가 Inventory와 일치한다.
- 기존 `target_stable_labels`가 현재 화면에서 정확히 하나의 actionable card와
  exact normalized match한다.
- legacy scenario가 현재 Repository에 존재하고 enabled/available 조건을 만족한다.
- Quick Identify에 legacy scenario를 명시적으로 반박하는 strong negative evidence가
  없다.
- 동일 display name card가 여러 개이면 room/section 등의 검증된 locator로 하나를
  확정할 수 있다. 그렇지 않으면 fallback하지 않는다.

다음 경우 legacy fallback을 금지하고 skip한다.

- Quick Identify `failed` 또는 restoration 실패
- 같은 display name으로 둘 이상의 card가 남음
- stale Inventory 또는 location/filter 변경
- legacy scenario와 다른 family의 Very High evidence가 확인됨
- fallback target이 bounds-only이고 action 직전 재검증할 수 없음
- scenario가 없거나 disabled/deprecated 상태

Legacy fallback은 V10 mapping의 confidence를 높이지 않는다. fallback 결과와 V10
candidate는 Shadow Validation에서 독립적으로 비교한다.

## 8. Shadow Validation

Shadow Mode에서는 legacy가 선택한 scenario와 Policy Mapping이 선택하거나 제안한
scenario를 같은 runtime card 기준으로 비교한다.

| Legacy Routing | Policy Mapping | Shadow Status | Meaning |
| --- | --- | --- | --- |
| Scenario A | Scenario A | `match` | 동일 scenario 선택 |
| Scenario A | Scenario B | `mismatch` | 명시적 scenario 충돌 |
| Scenario A | no mapping / unknown | `mapping_unknown` | legacy만 선택 가능 |
| Scenario A | ambiguous candidates | `mapping_ambiguous` | mapping이 단일 scenario를 결정하지 못함 |
| Scenario A | failed/skip | `mapping_failed` | lifecycle 또는 mapping contract 실패 |
| no scenario | Scenario A | `mapping_only` | display-name dependency 제거 가능성 |
| no scenario | no mapping | `both_unresolved` | 양쪽 모두 선택 불가 |

Shadow record는 다음 정보를 보존한다.

- `selection_id`, `identify_run_id`, `inventory_id`, `runtime_card_id`
- legacy scenario와 exact locator evidence
- mapped scenario, matched registry key와 decision
- identify decision, confidence, evidence references
- policy/registry/mapping/routing rule versions
- conflict status와 resolution reason
- match status와 mismatch triage reason
- traversal은 어느 path로 실행되었는지

`mismatch`는 자동으로 V10 또는 legacy 오류로 판정하지 않는다. snapshot evidence와
registry revision을 포함한 manual triage 대상이다.

## 9. Conflict Resolution

Multi-capability device에서는 "관찰된 모든 capability"와 "primary plugin family"를
구분해야 한다. 보조 capability가 있다고 별도 Scenario Policy를 선택하지 않는다.

### 9.1 Conflict Resolution Matrix

| Situation | Decision | Reason |
| --- | --- | --- |
| Motion + Temperature, Motion root가 primary | `device_motion_sensor_plugin` | Temperature는 보조 measurement이며 primary root가 Motion |
| Motion + Vibration, Motion root가 primary | `device_motion_sensor_plugin` | 별도 Vibration scenario가 없고 Motion family 내부 보조 capability |
| Humidity only primary sensor | `device_humidity_sensor_plugin` | humidity-only registry discriminator 충족 |
| Temperature + Humidity가 동일 primary sensor group | `device_temperature_humidity_sensor_plugin` | combined sensor discriminator 충족 |
| Motion device에 Temperature + Humidity도 존재 | `device_motion_sensor_plugin` | measurement 조합만으로 combined sensor scenario를 우선하지 않음 |
| Camera와 Home Camera evidence가 모두 generic | `ambiguous` | subtype discriminator 없이 두 scenario 중 선택 금지 |
| Home Camera 360 전용 signature 확인 | `device_home_camera_plugin` | more-specific eligible mapping 우선 |
| TV와 Audio control이 함께 존재, TV primary structure 확인 | `device_tv_plugin` | media/audio는 TV의 보조 capability일 수 있음 |
| 하나의 capability가 여러 eligible scenario에 mapping | discriminator 적용, 없으면 `ambiguous` | registry 순서나 display name으로 임의 선택 금지 |
| 여러 primary family의 Very High evidence가 공존 | `ambiguous` | multi-device container 또는 classifier conflict 가능 |
| primary family는 명확하지만 mapping entry disabled | `shadow_only` 또는 legacy fallback | 식별 성공과 policy readiness를 분리 |
| legacy scenario와 mapped scenario가 다름 | production 전환 전에는 legacy 유지, mismatch 기록 | shadow 단계에서 자동 우선순위 부여 금지 |

### 9.2 Resolution Order

Conflict는 다음 순서로 처리한다.

1. invalid lifecycle/restoration이면 `skip`
2. primary family-specific structural evidence 확인
3. registry의 required/forbidden evidence 검증
4. more-specific discriminator 적용
5. 검증된 precedence 적용
6. confidence와 top-candidate margin 확인
7. 단일 mapping이 남지 않으면 `ambiguous`

Precedence는 registry에 명시되고 corpus validation을 통과한 경우에만 사용한다.
scenario 목록 순서, 높은 숫자 score 또는 display name은 tie-breaker가 아니다.

## 10. Policy Versioning

Policy Mapping은 서로 다른 변경 축을 하나의 version으로 합치지 않는다.

| Version Field | Scope | Change Rule |
| --- | --- | --- |
| `policy_version` | 개별 Scenario Policy의 traversal behavior | anchor, tab, stop/traversal behavior가 바뀌면 증가 |
| `registry_version` | Registry schema와 contract semantics | 필드 또는 해석의 breaking change 시 major 증가 |
| `mapping_revision` | capability-to-scenario entry 내용 | mapping, discriminator, status, confidence requirement 변경 시 증가 |
| `routing_rule_version` | confidence band별 action/fallback 규칙 | Definite/High/Medium 처리나 fallback gate 변경 시 증가 |
| `identify_contract_version` | 입력 Quick Identify Result contract | selection record에 원본 version 보존 |

권장 초기 형태는 다음과 같다.

```text
policy_version: device_motion_sensor_policy-v1
registry_version: v10-policy-registry-v1
mapping_revision: 1
routing_rule_version: v10-routing-rules-v1
identify_contract_version: v10-quick-identify-v1
```

Version 관리 원칙:

- 모든 selection record에 당시 사용한 version을 함께 저장한다.
- 기존 artifact의 version을 나중 값으로 덮어쓰지 않는다.
- mapping content 변경은 최소 `mapping_revision`을 증가시킨다.
- registry schema의 backward-incompatible 변경은 `registry_version` major를
  증가시킨다.
- Scenario Policy behavior가 바뀌면 mapping이 같아도 `policy_version`을 증가시킨다.
- threshold 변경은 `routing_rule_version` 또는 mapping별 confidence requirement
  revision으로 추적한다.
- rollback은 이전 immutable revision을 다시 활성화하며 revision history를 삭제하지
  않는다.

현재 Repository에는 명시적인 `policy_version`, `mapping_revision`,
`registry_version` 필드가 없다. 이 문서는 향후 contract를 제안하며 기존 config에
즉시 필드를 추가하는 것을 요구하지 않는다.

## 11. Out Of Scope

이 문서는 다음을 정의하거나 구현하지 않는다.

- Traversal Engine 내부 동작
- Scenario Policy 내용 변경
- coverage 수집 및 판정
- Device Inventory 구현
- Quick Identify classifier 또는 signature extraction 구현
- Plugin Discovery 변경
- Frontend 표시 및 운영 승인 UI
- scenario config 수정
- capability signature의 최종 production calibration
- device card open/back 동작
- legacy routing 제거 시점

## 12. Acceptance Criteria

Phase 3 Architecture Contract는 다음 조건을 모두 만족하면 완료로 판단한다.

- Quick Identify Result의 필수 입력과 validation gate가 정의된다.
- Traversal Policy Selection output schema와 decision semantics가 정의된다.
- Policy Mapping이 기존 Scenario Policy만 선택하고 Traversal Engine을 변경하지
  않는다는 경계가 명확하다.
- 현재 Repository의 12개 Device Scenario가 Policy Registry에 반영된다.
- capability key가 V10 canonical mapping key임이 명시된다.
- Definite, High, Medium, Unknown, Ambiguous, Failed의 routing action이 Routing
  Decision Matrix로 정의된다.
- High confidence route가 family별 eligible registry 상태에 의해 제한된다.
- legacy display name이 identity가 아닌 strict fallback locator로 정의된다.
- fallback 허용 및 금지 조건이 명확하다.
- multi-capability, one-to-many mapping과 subtype conflict가 Conflict Resolution
  Matrix로 정의된다.
- discriminator 없이 여러 scenario 중 하나를 임의 선택하지 않는다.
- Shadow Validation의 match/mismatch/unknown/ambiguous/failed 기록 계약이 정의된다.
- policy, registry, mapping, routing rule, identify contract version이 독립적으로
  추적된다.
- `unknown`, unresolved `ambiguous`, `failed`가 traversal을 강제 시작하지 않는다.

Phase 3 완료는 Policy Mapping 구현 또는 production routing 전환을 의미하지 않는다.
완료 조건은 향후 구현과 Shadow Validation이 따라야 할 mapping/routing contract가
명확하고 versioned하게 정의되는 것이다.
