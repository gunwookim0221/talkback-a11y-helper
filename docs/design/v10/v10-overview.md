# V10 Overview

## 1. Background

현재 Device plugin 진입은 `scenario_config.target_stable_labels`와 stable display
name exact match를 전제로 한다. 이 방식은 동일 plugin이라도 계정, 위치, 언어,
사용자 naming policy에 따라 기기 이름이 달라질 수 있다는 점에서 운영 확장성이
낮다.

현재 진입 구조는 아래와 같다.

```text
Display Name
-> Scenario
-> Traversal
```

Motion Sensor, Door Sensor, Leak Sensor 같은 plugin은 화면에 보이는 device card의
stable display name이 scenario config와 일치해야만 현재 구조에서 안전하게 진입할
수 있다.

## 2. Current Problem

핵심 문제는 "기기 이름"이 plugin identity의 source of truth처럼 사용된다는 점이다.

- 사용자 기기 이름이 바뀌면 기존 scenario mapping이 바로 약해진다.
- 다른 계정/다른 집 구조에서는 동일 plugin이어도 display name이 달라질 수 있다.
- Discovery가 card를 보여 주더라도, 현재 known/scenario 판정은 여전히 label lookup에
  가깝다.
- 진입 전 단계에서 plugin type을 안정적으로 알 수 있는 신호가 약하다.

즉 현재 구조는 "카드를 찾는 문제"와 "어떤 policy를 적용할지 결정하는 문제"가
display name 하나에 과도하게 결합되어 있다.

## 3. Display Name Dependency

현재 Device card entry는 아래 흐름에 의존한다.

```text
scenario_config.target_stable_labels
-> find_device_card_by_stable_label()
-> stable display name exact match
```

이 구조에서는 `거실 모션`, `Motion Sensor 1`, `Bedroom Motion`처럼 사용자 임의
display name을 쓰는 경우 generic Motion Sensor scenario에 자동 연결되기 어렵다.

Display name은 runtime locator로는 유용할 수 있지만, semantic plugin identity로는
불안정하다.

## 4. Current Limits Of Discover Plugins

현재 Discover Plugins는 visible candidate inventory로는 유용하지만, Device plugin
type classifier로는 아직 충분하지 않다.

현재 한계:

- Device discovery는 helper dump 기반 visible card inventory 중심이다.
- card container, label, stable label, bounds, resource id 등은 수집 가능하다.
- 그러나 pre-open 단계에서 Motion, Door, Leak 같은 plugin family를 강하게 구분하는
  구조 신호는 부족하다.
- current-view-only 특성이 있어 offscreen card를 포괄하지 못한다.
- known/scenario 값도 독립 classifier라기보다 stable label 매칭 결과에 가깝다.

즉 Discover Plugins 결과만으로 plugin 종류를 확정하는 것은 현재 기준으로는
No-Go다.

## 5. Why Post-Open Identify Is More Feasible

진입 후에는 capability card resource-id, header title, local tab structure, helper
dump와 XML 구조를 함께 볼 수 있기 때문에 식별 가능성이 크게 올라간다.

예:

- capability resource-id signature
- capability header/title
- control/history/local tab 조합
- screen-specific XML structure

이 신호들은 display name보다 plugin family를 더 직접적으로 설명한다.

따라서 V10의 핵심 전환은 "진입 전 완전 식별"이 아니라 "짧게 열고 식별한 뒤
적절한 policy를 선택"하는 것이다.

## 6. V10 Goal

V10의 목표는 traversal engine을 교체하는 것이 아니다. 기존 traversal engine과
scenario policy를 최대한 재사용하면서, 어떤 policy를 적용할지 결정하는 방식을
display name 중심에서 discovery + identify 중심으로 전환하는 것이다.

목표 구조:

```text
Device Card Inventory
-> Quick Plugin Identify
-> Policy Selection
-> Existing Traversal Engine
```

## 7. Non-Goals

V10의 비목표는 아래와 같다.

- 기존 traversal engine 전면 교체
- 기존 scenario policy 재작성
- 모든 Device plugin을 pre-open만으로 완전 식별
- 초기 단계에서 display name fallback 제거
- 첫 구현에서 production routing을 바로 전환

## 8. Architecture Summary

V10은 세 층으로 이해하는 것이 적절하다.

### Inventory

현재 Devices 화면에서 보이는 card를 runtime inventory로 수집한다. 이 단계의 목적은
"무엇이 보이는가"를 기록하는 것이지, plugin type을 최종 확정하는 것이 아니다.

### Identify

선택한 candidate를 짧게 open하고 helper dump/XML/capability 구조를 수집하여
plugin family를 분류한다. Unknown 또는 ambiguous는 허용하되, 억지로 특정 scenario로
매핑하지 않는다.

### Policy Selection

식별된 family/signature를 기존 scenario policy에 연결한다. 이후 traversal은 현재
engine을 그대로 사용한다.

## 9. Expected Benefits

- 계정별 display name 차이에 대한 민감도가 낮아진다.
- Motion Sensor 같은 generic device plugin을 이름 표준화 없이 다룰 가능성이 커진다.
- 기존 scenario/traversal 자산을 재사용할 수 있다.
- shadow mode로 안전하게 품질을 비교할 수 있다.
- unknown/ambiguous를 fail-closed 처리하여 잘못된 routing 위험을 줄일 수 있다.

## 10. Risks

- capability signature가 항상 plugin identity와 1:1은 아니다.
- multi-capability device는 ambiguous mapping을 만들 수 있다.
- resource-id나 XML 구조가 앱 버전에 따라 drift할 수 있다.
- quick identify를 위해 card를 열었다가 원래 list context로 복귀하는 과정이 깨질 수
  있다.
- current-view-only inventory는 전체 device universe를 대표하지 못할 수 있다.

## 11. Go / No-Go

판단은 아래처럼 나뉜다.

- `Go`: post-open capability/XML structure 기반 Quick Identify를 shadow MVP로
  도입하는 것
- `No-Go`: 현재 Discover Plugins 결과만으로 display name dependency를 즉시 제거하는 것

따라서 V10은 "Display Name 완전 제거"가 아니라, "Display Name only routing에서
벗어나기 위한 식별 계층 추가"로 시작하는 것이 맞다.
