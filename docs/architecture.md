# Architecture (현재 운영 기준)

[System Overview](system-overview.md) | [Current Client Architecture](current-client-architecture.md) | [Device Plugin Guide](device-plugin-guide.md)

## 1) 상위 구조

```text
Python Runner
  script_test.py
  tb_runner/*
  talkback_lib/*
    -> A11yAdbClient façade
    -> focus / step / row assembly
    -> runtime log parsing and report save

Android Helper
  app/*
    -> AccessibilityService
    -> target action / dump_tree / SMART_NEXT bridge
```

## 2) 운영 계층

### Client 계층
- `A11yAdbClient`
- `FocusService`
- `StepCollectionService`
- `StepRowBuilder`

### Runner 계층
- `collection_flow.py`: scenario open, main loop, persist
- `anchor_logic.py`, `tab_logic.py`: start stabilization
- `overlay_logic.py`: overlay branch and recovery
- `excel_report.py`: workbook export

### Scenario 계층
- Global / main tabs
- Life plugins
- Device plugins

## 3) Devices plugin 운영 추가점

Devices plugin은 일반 Life plugin과 다르게 Devices list normalization을 먼저
수행한다.

- `enter_device_card_plugin` pre-navigation 사용
- `All devices` selected 보장
- visible inventory 우선 매칭
- 필요할 때만 room expand
- safe tap 적용
- bounded search는 helper scroll이 아니라 **ADB swipe** 사용

자세한 흐름은 [device-plugin-guide.md](device-plugin-guide.md)를 따른다.

## 4) Report row semantics

현재 raw/result 기본 visible 계열은 representative가 아니라 **actual TalkBack
focus 기준**이다.

- 기본 컬럼: actual focus
- `representative_*`: traversal representative

자세한 스키마는 [report-schema.md](report-schema.md)를 본다.

## 5) 불변 계약

- helper protocol unchanged
- traversal / scoring / representative selection unchanged
- stop reason 해석 유지
- 운영 로그 키 유지
- row schema는 additive change를 우선
