# Crash Capture & Repro Guide Design

이 문서는 SmartThings(OneConnect) 자동 검증 중 FC/Crash가 발생했을 때의 감지, 증거 수집, 재시도, Batch 복구, Frontend 표시, Manual Repro Guide 생성 정책을 정의합니다.

현재 문서는 구현 전 설계 기준이며, runtime/frontend/backend/helper APK 변경은 포함하지 않습니다.

---

# 1. Goal

Crash Capture의 목적은 자동화 실행 중 SmartThings 앱이 강제 종료되거나 비정상 상태로 전환되었을 때, 원인을 재현 가능한 형태로 남기고 Batch 전체가 불필요하게 중단되지 않도록 하는 것입니다.

- 자동 검증 중 SmartThings FC 발생 위치를 시나리오/스텝 단위로 기록합니다.
- 개발자가 재현 가능한 로그, 화면, 포커스, TalkBack 발화 정보를 함께 제공합니다.
- 비개발자도 Device Details에서 어떤 화면과 동작 직후 문제가 발생했는지 확인할 수 있게 합니다.
- 단일 시나리오 Crash가 전체 Batch 실패로 확대되지 않도록 재시도 및 skip 정책을 둡니다.
- 반복 Crash, ADB 단절, Helper 비정상 종료처럼 자동 복구가 의미 없는 상태는 Batch 중단 기준으로 분리합니다.

---

# 2. Crash Definition

Crash 관련 상태는 원인 확정 정도와 복구 가능성을 기준으로 구분합니다.

## Confirmed Crash

앱 프로세스의 실제 FC로 확정할 수 있는 상태입니다. Phase 3-A에서는 logcat을 primary source로 사용합니다.

판정 예:

- `FATAL EXCEPTION`
- `Process: com.samsung.android.oneconnect`
- Android runtime crash stack trace가 OneConnect 프로세스와 함께 기록됨
- Crash 직후 foreground package가 OneConnect에서 이탈함

운영 의미:

- Crash artifact를 반드시 수집합니다.
- 해당 scenario는 retry 대상입니다.
- 동일 scenario에서 반복되면 `CRASH_REPEATED`로 skip합니다.

## App Terminated

Crash stack trace는 없지만 OneConnect 프로세스가 종료된 상태입니다.

판정 예:

- `adb shell am force-stop com.samsung.android.oneconnect`에 준하는 상태
- 프로세스 조회 결과 OneConnect가 없음
- foreground app이 없거나 launcher로 복귀했으며 logcat에 FC signature가 없음

운영 의미:

- Crash로 단정하지 않고 `APP_TERMINATED`로 기록합니다.
- 자동화 또는 외부 요인에 의한 종료 가능성을 남깁니다.
- relaunch 후 1회 retry할 수 있습니다.

## Possible Crash

Crash 확정 로그는 없지만 실행 흐름상 앱이 비정상 이탈한 상태입니다.

판정 예:

- foreground package가 OneConnect가 아님
- launcher/home으로 이동됨
- current package를 확인할 수 없음
- UI dump가 비어 있거나 package가 unknown
- 마지막 action 이후 앱 화면이 사라졌으나 logcat crash block을 찾지 못함

운영 의미:

- `POSSIBLE_CRASH`로 낮은 신뢰도의 issue를 생성합니다.
- foreground 복구를 시도하고, 복구 성공 여부를 context에 남깁니다.
- 반복되면 scenario skip 후보가 됩니다.

## ANR

ANR은 Phase 3-A의 직접 구현 범위는 아니며 향후 확장 대상으로 둡니다.

판정 후보:

- `Application Not Responding`
- `Input dispatching timed out`
- ANR traces 또는 bugreport 기반 evidence

운영 의미:

- 현재는 Crash Capture schema에 `crash_type: "ANR"`를 예약합니다.
- 향후 bugreport/traces 수집과 함께 별도 timeout/retry 정책을 정의합니다.

---

# 3. Detection Strategy

Phase 3-A의 detection은 logcat 기반 판단을 primary로 두고, foreground 상태를 보조 신호로 사용합니다.

기본 흐름:

```text
Run start
↓
adb logcat -c
↓
background logcat capture 시작
↓
scenario/step 실행
↓
step boundary 또는 foreground check 지점에서 crash detect
↓
crash context/artifacts 수집
↓
retry 또는 scenario skip 판단
```

## Logcat 기반 판단

- Run 시작 시 `adb logcat -c`로 이전 실행 로그를 정리합니다.
- 실행 중 별도 background capture로 logcat을 파일에 저장합니다.
- `FATAL EXCEPTION`과 `Process: com.samsung.android.oneconnect`가 같은 crash block에 있으면 `CONFIRMED_CRASH`로 판정합니다.
- crash block의 timestamp, exception class, top stack frame, process, pid를 context에 저장합니다.

## Foreground 기반 보조 판단

- step boundary, recovery 진입 전, scenario 종료 직전에 foreground package를 확인합니다.
- OneConnect가 foreground가 아니면 launcher/settings/system popup 여부를 확인합니다.
- logcat crash signature가 있으면 `CONFIRMED_CRASH`, 없으면 `POSSIBLE_CRASH` 또는 `APP_TERMINATED`로 분류합니다.
- popup recovery로 설명 가능한 이탈은 Crash Issue가 아니라 Runtime Recovery event로 기록합니다.

## 중복 감지 방지

- 동일 timestamp/pid/exception signature의 crash는 하나의 crash event로 묶습니다.
- retry 중 같은 signature가 다시 발생하면 repeated count를 증가시킵니다.
- scenario가 바뀌면 count는 scenario 단위로 초기화하되, batch-level total crash count는 별도 누적합니다.

---

# 4. Crash Artifacts

Crash 발생 시에는 개발자가 원인 분석과 재현을 시작할 수 있는 최소 artifact를 같은 디바이스 결과 디렉터리에 저장합니다.

수집 대상:

- `runner.log`: runner 실행 로그
- `logcat.txt`: run 시작 이후 background capture 로그
- `crash_screenshot.png`: Crash 감지 직후 화면
- `crash_window_dump.xml`: Android UIAutomator window dump
- `crash_helper_dump.json`: TalkBack A11y Helper dump
- `focus_state.json`: 마지막 접근성 포커스 및 foreground 상태
- `crash_context.json`: scenario/step/action/evidence를 요약한 구조화 context

예시 디렉터리:

```text
device_xxx/
├ crash_context.json
├ crash_screenshot.png
├ crash_window_dump.xml
├ crash_helper_dump.json
├ focus_state.json
├ logcat.txt
└ runner.log
```

복수 Crash가 발생할 수 있으므로 Crash event별 하위 디렉터리 구조를 사용합니다. 각 event는 batch 내 고유 `crash_event_id`를 가지며, artifact directory 이름도 같은 값을 사용합니다.

```text
device_xxx/
└ crashes/
   ├ CRASH-0001/
   │  ├ crash_context.json
   │  ├ crash_repro.md
   │  ├ crash_screenshot.png
   │  ├ crash_window_dump.xml
   │  ├ crash_helper_dump.json
   │  └ focus_state.json
   └ CRASH-0002/
      └ ...
```

`crash_event_id`는 아래 항목을 연결하는 공통 식별자입니다.

- Frontend Crash Card
- logcat excerpt
- artifact directory
- `crash_context.json`
- `crash_repro.md`

---

# 5. Crash Context Schema

`crash_context.json`은 사람이 읽을 수 있고 Frontend가 그대로 표시할 수 있는 구조를 목표로 합니다.

예시:

```json
{
  "schema_version": 1,
  "crash_event_id": "CRASH-0001",
  "device_id": "R5CT123ABCD",
  "package": "com.samsung.android.oneconnect",
  "crash_type": "CONFIRMED_CRASH",
  "confidence": "high",
  "timestamp": "2026-06-03T19:42:11+09:00",
  "scenario": {
    "name": "life_home_monitor",
    "plugin": "life_home_monitor_plugin",
    "run_mode": "selected_full"
  },
  "step": {
    "index": 7,
    "name": "enter_home_monitor",
    "attempt": 1
  },
  "last_action": {
    "type": "tap",
    "label": "Home Monitor",
    "bounds": [72, 418, 480, 512]
  },
  "last_focus_label": "Home Monitor",
  "last_speech": "Home Monitor, button",
  "last_visible_text": [
    "Life",
    "Home Monitor",
    "Energy",
    "Pet Care"
  ],
  "foreground": {
    "before": "com.samsung.android.oneconnect",
    "after": "com.sec.android.app.launcher"
  },
  "logcat": {
    "exception": "java.lang.NullPointerException",
    "process": "com.samsung.android.oneconnect",
    "pid": 12345,
    "top_frame": "com.samsung.android.oneconnect.example.HomeMonitorActivity.onCreate",
    "signature": "NullPointerException@HomeMonitorActivity.onCreate"
  },
  "artifacts": {
    "runner_log": "runner.log",
    "logcat": "logcat.txt",
    "screenshot": "crashes/CRASH-0001/crash_screenshot.png",
    "window_dump": "crashes/CRASH-0001/crash_window_dump.xml",
    "helper_dump": "crashes/CRASH-0001/crash_helper_dump.json",
    "focus_state": "crashes/CRASH-0001/focus_state.json",
    "repro_guide": "crashes/CRASH-0001/crash_repro.md"
  },
  "recovery": {
    "decision": "retry",
    "retry_count": 1,
    "result": "pending"
  }
}
```

필수 필드:

- `schema_version`
- `crash_event_id`
- `device_id`
- `package`
- `crash_type`
- `confidence`
- `timestamp`
- `scenario.name`
- `step.index`
- `last_action`
- `artifacts`
- `recovery.decision`

가능하면 채우는 필드:

- `last_focus_label`
- `last_speech`
- `last_visible_text`
- `foreground.before`
- `foreground.after`
- `logcat.exception`
- `logcat.top_frame`
- `logcat.signature`

## Crash Event ID

`crash_event_id`는 batch 내에서만 고유한 순번 기반 식별자입니다.

예:

- `CRASH-0001`
- `CRASH-0002`
- `CRASH-0003`

생성 규칙:

- Crash event가 확정 또는 기록 대상이 되는 시점에 증가시킵니다.
- 같은 crash event의 context, screenshot, dump, repro guide, logcat excerpt는 동일 ID를 사용합니다.
- retry 중 같은 signature가 다시 발생하면 새 `crash_event_id`를 부여하되, 같은 crash group에 연결할 수 있습니다.

## Crash Grouping

Crash Grouping은 반복 발생한 동일 유형 Crash를 식별하기 위한 최소 규칙입니다. 초기 구현에서는 grouping metadata를 저장하는 것까지를 기본 목표로 하며, Frontend에서 group UI를 노출하는 것은 후속 단계로 둘 수 있습니다.

동일 Crash Group 후보:

```text
동일 Scenario
+
동일 Exception
+
동일 Top Frame
```

예:

```text
Scenario: life_home_monitor
Exception: NullPointerException
Top Frame: HomeMonitorActivity.onCreate
Occurred: 3 times
```

Frontend 표시 예:

```text
Crash Group A
Scenario: life_home_monitor
Signature: NullPointerException @ HomeMonitorActivity.onCreate
Occurred 3 times
```

초기 grouping key 후보:

- `scenario.name`
- `logcat.exception`
- `logcat.top_frame`

`POSSIBLE_CRASH`처럼 exception/top frame이 없는 경우에는 grouping을 강제하지 않고 개별 event로 남깁니다.

---

# 6. Retry Policy

Retry는 scenario 단위로 제한하며, 동일 scenario가 반복 Crash로 Batch 전체를 지연시키지 않도록 합니다.

## 기본 정책

```text
Crash 1회
→ artifact 수집
→ OneConnect relaunch
→ popup recovery/preflight subset 수행
→ 동일 scenario 1회 retry
```

```text
Crash 2회 연속
→ CRASH_REPEATED
→ 해당 scenario skip
→ 다음 scenario 진행
```

## 상태별 처리

- `CONFIRMED_CRASH`: artifact 수집 후 1회 retry합니다.
- `APP_TERMINATED`: relaunch 후 1회 retry하되, context에 crash 확정 로그 없음으로 기록합니다.
- `POSSIBLE_CRASH`: foreground recovery를 먼저 시도하고, 실패하거나 반복되면 retry count를 소모합니다.
- `ANR`: 현재는 future reserved입니다. 구현 전에는 timeout issue로 별도 기록합니다.

## Retry 성공 기준

- OneConnect가 foreground로 복귀합니다.
- Helper와 TalkBack 상태가 정상입니다.
- scenario가 retry 후 crash 없이 완료되거나, 다음 step으로 진행됩니다.

## Retry 실패 결과

- scenario status: `skipped`
- failure reason: `CRASH_REPEATED`
- quality issue: `Crash Issue`
- batch는 계속 진행합니다.

---

# 7. Batch Abort Policy

Batch는 개별 scenario Crash에는 계속 진행하지만, 자동 검증 환경 자체가 깨진 경우에는 중단합니다.

Batch 중단 조건:

- ADB disconnected: 대상 디바이스가 `adb devices`에서 사라짐
- Helper dead: helper dump/API가 반복 실패하고 accessibility service 복구가 불가능함
- TalkBack disabled: TalkBack이 꺼졌고 자동 복구 실패
- Crash 5회 이상: batch 전체에서 `CONFIRMED_CRASH` 또는 retry를 소모한 `POSSIBLE_CRASH`가 5회 이상 누적
- OneConnect relaunch 불가: relaunch 후에도 foreground 진입 실패가 반복됨

## Batch Crash Count

Batch Crash Count는 Batch 중단 여부를 판단하기 위한 운영 카운터입니다. 모든 앱 이탈이나 복구 이벤트를 세지 않고, 실제 Crash로 확정되었거나 retry 비용을 소모한 Crash 후보만 누적합니다.

누적 대상:

- `CONFIRMED_CRASH`
- retry를 소모한 `POSSIBLE_CRASH`

누적하지 않는 대상:

- 단순 popup contamination
- foreground recovery 성공
- retry 없이 복구된 `APP_TERMINATED`

예:

```text
Scenario A
CONFIRMED_CRASH x2

Scenario B
POSSIBLE_CRASH(retry used) x2

Scenario C
CONFIRMED_CRASH x1

Total = 5
→ Batch Abort
```

중단 결과:

- batch status: `aborted`
- abort reason: `ADB_DISCONNECTED`, `HELPER_DEAD`, `TALKBACK_DISABLED`, `CRASH_LIMIT_EXCEEDED`, `APP_RELAUNCH_FAILED`
- 이미 완료된 scenario 결과와 crash artifacts는 보존합니다.
- Frontend는 Batch 전체 실패와 개별 Crash Issue를 분리해서 표시합니다.

---

# 8. Frontend UX

Frontend는 Crash를 TalkBack 품질 문제와 섞어 숨기지 않고, Device Details에서 별도 구조로 노출해야 합니다.

## Device Details 구조 제안

- Device summary
- Runtime status
- TalkBack Quality
- Quality Issues
- Crash Issues
- Scenario list
- Logs / Artifacts

## TalkBack Quality와 Crash Issues의 관계

- TalkBack Quality는 접근성 발화/표시 품질 판독 결과를 유지합니다.
- Crash Issues는 runtime 안정성 문제로 별도 표시합니다.
- Crash로 인해 검증이 중단된 scenario는 TalkBack Quality에서 `issue`로 반영될 수 있지만, 원인 설명은 Crash Issues가 담당합니다.

## Crash Card 예시

```text
Crash Issue
Status: CRASH_REPEATED
Scenario: life_home_monitor
Step: 7 / enter_home_monitor
Last action: tap "Home Monitor"
Last focus: Home Monitor
Last speech: Home Monitor, button
Foreground after crash: com.sec.android.app.launcher
Exception: java.lang.NullPointerException
Top frame: HomeMonitorActivity.onCreate
Recovery: retried once, scenario skipped

Artifacts:
- Screenshot
- Logcat
- Window dump
- Helper dump
- Manual Repro Guide
```

## 표시 원칙

- Crash count와 repeated 여부를 Device card에서 바로 확인할 수 있어야 합니다.
- `CONFIRMED_CRASH`, `APP_TERMINATED`, `POSSIBLE_CRASH`를 badge로 구분합니다.
- 비개발자에게는 scenario, step, last action, screenshot을 먼저 보여줍니다.
- 개발자용 logcat exception/top frame은 접힘 영역 또는 상세 영역에 둡니다.
- Manual Repro Guide는 Crash Card에서 바로 열 수 있어야 합니다.

---

# 9. Manual Repro Guide

Manual Repro Guide는 crash context를 사람이 재현 가능한 절차로 변환한 Markdown artifact입니다.

생성 시점:

```text
Crash Detect
↓
Artifact 수집
↓
crash_context.json 생성
↓
crash_repro.md 생성
```

생성 위치:

```text
device_xxx/
└ crashes/
   └ CRASH-0001/
      ├ crash_context.json
      ├ crash_repro.md
      ├ crash_screenshot.png
      ├ crash_window_dump.xml
      ├ crash_helper_dump.json
      └ focus_state.json
```

Frontend는 `crash_repro.md`를 그대로 표시하거나 다운로드할 수 있어야 합니다.

예시:

```markdown
# Manual Repro Guide

Device: R5CT123ABCD
Package: com.samsung.android.oneconnect
Scenario: life_home_monitor
Crash Type: CONFIRMED_CRASH

## Preconditions

1. SmartThings 앱을 설치하고 로그인 상태를 준비합니다.
2. TalkBack을 ON으로 설정합니다.
3. TalkBack A11y Helper accessibility service를 활성화합니다.
4. 디바이스 언어와 region을 테스트 실행 당시 설정과 맞춥니다.

## Steps

1. SmartThings를 실행합니다.
2. 하단 탭에서 Life 탭으로 이동합니다.
3. 화면에서 Home Monitor 항목으로 포커스를 이동합니다.
4. Home Monitor 항목을 실행합니다.
5. 화면 전환 직후 앱이 종료되는지 확인합니다.

## Observed Result

SmartThings가 launcher로 이탈하며 FC가 발생했습니다.

## Last Automation Context

- Last action: tap "Home Monitor"
- Last focus: Home Monitor
- Last speech: Home Monitor, button
- Foreground after crash: com.sec.android.app.launcher

## Crash Evidence

- Exception: java.lang.NullPointerException
- Top frame: HomeMonitorActivity.onCreate
- Screenshot: crashes/CRASH-0001/crash_screenshot.png
- Logcat: logcat.txt
```

생성 원칙:

- 자동화 내부 용어보다 사용자가 수행할 수 있는 단계 문장을 우선합니다.
- scenario/step 이름만으로 부족하면 `last_visible_text`, `last_focus_label`, `last_speech`를 사용해 단계를 보강합니다.
- Crash 확정 로그가 없으면 "FC 확정" 대신 "앱 이탈" 또는 "possible crash"로 표현합니다.
- artifact 경로는 상대 경로로 기록합니다.

---

# 10. Future Extension

향후 확장 후보:

- Android `bugreport` 자동 수집
- ANR traces 수집 및 `ANR` crash type 활성화
- Crash Grouping: exception/top frame/signature 기준 그룹화
- 9900 dump 수집 자동화
- Crash signature별 history 추적
- Batch summary에서 crash trend 표시
- known issue allowlist 또는 expected crash marking

---

# 11. Implementation Phases

Crash Capture는 detection, context, recovery, UI를 한 번에 구현하지 않고 단계별로 분리합니다.

## Phase 3-A: Crash Detection + Logcat Capture

범위:

- logcat capture
- crash detect
- crash event 저장

비포함:

- retry
- frontend crash UI
- repro guide UI

## Phase 3-B: Crash Context Capture

범위:

- screenshot 수집
- window/helper/focus dump 수집
- `crash_context.json` schema 저장
- `crash_repro.md` 생성

## Phase 3-C: Recovery / Retry Policy

범위:

- OneConnect relaunch
- retry 실행
- `CRASH_REPEATED` 판정
- Batch Crash Count 누적
- batch abort 정책 적용

## Phase 3-D: Frontend Crash Issues

범위:

- Crash Issues section
- Crash Card
- Repro Guide 표시
- Artifact 다운로드

---

# Non Goals

이번 설계 및 다음 초기 구현 단계에서 하지 않는 일:

- 자동 PLM 생성
- 자동 Jira 생성
- 9900 dump 자동화
- bugreport 전체 자동 수집
- ANR 완전 판정
- Crash 원인 자동 분석
- helper APK 수정
- TalkBack 품질 판정 로직 변경
- Frontend 대규모 정보 구조 개편
