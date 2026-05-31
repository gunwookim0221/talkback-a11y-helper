# Phase M-1: Multi Device Architecture Design

## 1. 현재 구조에서 단일 단말 의존 부분 (단일 단말 한계)

현재 QA Frontend 및 Runner는 기본적으로 연결된 1대의 단말을 가정하고 설계되어 있습니다. 다중 단말 확장을 위해 다음 요소들의 디커플링(Decoupling)이 필요합니다.

- **ADB Devices 및 Serial 처리**: 백엔드와 Runner가 실행될 때 명시적인 `serial` 인자 없이 기본 디바이스를 타겟팅하거나, 전역 상태로 하나의 Serial만 관리하고 있습니다.
- **Output 경로**: `output/` 하위에 날짜/시간 기반(예: `20260601_001`)으로 디렉터리나 파일(로그, 엑셀)이 단일로 생성되어 여러 단말의 결과가 덮어써지거나 충돌할 수 있습니다.
- **Runtime State 및 Polling**: 프론트엔드가 `/api/run/status` 등 단일 엔드포인트를 바라보며, 백엔드 역시 하나의 `run_state`만 글로벌하게 들고 있어 다중 단말 상태 병렬 모니터링이 불가능합니다.
- **Log Monitor**: 단일 `logcat` 프로세스를 띄워 파이프로 읽어들이고 있으며, 여러 디바이스의 스트림을 동시에 식별 및 파싱할 수 없습니다.
- **Helper 상태 및 Preflight**: 단말 1대의 TalkBack, 접근성 권한 여부만 체크하며, 1대라도 조건이 안 맞으면 전체가 Block되는 구조입니다.

---

## 2. Multi Device 설계 (Batch Run 구조)

여러 단말에 대해 동시에 테스트를 수행하는 단위를 `Batch Run`으로 정의합니다. 각 단말은 하위 독립 `Run`으로 관리되어야 합니다.

**권장 계층 구조**:
```text
Batch_Run (예: run_20260601_001)
 ├─ Device_A (예: device_R3CX...)
 ├─ Device_B (예: device_R58X...)
 └─ Device_C (예: device_R12X...)
```

---

## 3. 실행 방식 비교 및 권장안

### A. 순차 실행 (Sequential Execution)
- **장점**: 
  - 백엔드와 Runner의 기존 구조(글로벌 상태 관리, 로그 파싱)를 크게 바꾸지 않고 재사용할 수 있습니다.
  - PC 시스템(CPU, 램) 및 ADB 서버에 가해지는 부하가 적습니다.
- **단점**: 
  - 10대 단말 테스트 시 10배의 시간이 소요되어 자동화의 '시간 절약' 이점이 상쇄됩니다.

### B. 병렬 실행 (Parallel Execution)
- **장점**: 
  - 다수 단말을 테스트하더라도 1대 테스트 시간과 거의 동일하게 종료되어 생산성이 극대화됩니다.
- **단점**: 
  - Runner 프로세스 다중화, Logcat 스트림 분리, API 상태 객체 분리 등 백엔드 아키텍처의 전면 개편이 필요합니다.

**권장안**: 궁극적인 목표는 **B. 병렬 실행**입니다. 하지만 안정성을 위해 **순차 실행(Phase M-3)을 먼저 도입**하여 다중 단말 Output 폴더 구조 및 Frontend UI를 검증한 후, 상태 관리를 분리하여 **병렬 실행(Phase M-5)**으로 고도화하는 점진적 접근을 권장합니다.

---

## 4. Frontend UX 설계

단일 패널에 다중 단말 선택 및 상태 표기를 지원하는 형태로 진화해야 합니다.

**Device Panel 신설 (Preflight/Launch 직전 단계)**
```text
[Device Selection]
☑ Fold6 (R3CX...) - Ready
☑ S24 Ultra (R58X...) - Ready
☑ S23 (R12X...) - TalkBack disabled (Warning)
☐ A55 - Offline

Selected devices: 2
[ Run Batch ]
```

**실행 중 (Live Monitor 확장)**
```text
Batch Run: 20260601_001
---------------------------------
Fold6      [ RUNNING ] 5/10 steps
S24 Ultra  [ PASSED ]  Finished
---------------------------------
```

---

## 5. 결과 저장 구조 (Output Structure)

결과물 충돌 방지를 위해 최상위 Batch 폴더 하위에 Device 시리얼 또는 모델명 폴더를 강제 분리합니다.

```text
output/
  batch_20260601_001/
    summary.json (Batch 통계)
    device_fold6_R3CX.../
      runner.log
      report.xlsx
      summary.json (단일 단말 통계)
    device_s24_R58X.../
      runner.log
      report.xlsx
      summary.json
```
- **충돌 검토**: Runner 실행 시 `--output-dir` 파라미터를 강제하여 해당 디렉터리 내에만 쓰도록 샌드박싱하면 파일 시스템 충돌을 완벽히 회피할 수 있습니다.

---

## 6. Runtime Dashboard (Live Monitor) 확장안

현재 1개 단말 기준으로 구성된 Live Monitor는 다중 단말로 갈 경우 화면이 부족해집니다. 이를 **마스터-디테일(Master-Detail)** 뷰로 설계합니다.

- **마스터 뷰 (상단)**: 참여 중인 기기 전체의 Progress Bar와 상태(Running, Failed, Passed)를 그리드로 보여줍니다.
- **디테일 뷰 (하단)**: 마스터 뷰에서 특정 기기를 클릭(Select)하면, 해당 기기만의 `Event Feed`, `Current Scenario`, `Steps`를 표시합니다. 

---

## 7. 구현 우선순위 (Phases)

1. **Phase M-2: Device Detection**
   - 백엔드 ADB API 개선: 다중 기기 목록(Serial, Model) 반환
   - 프론트엔드 Device Panel 추가 및 선택 로직 구현

2. **Phase M-3: Sequential Execution**
   - 선택된 단말 배열을 받아 1번 기기부터 순차적으로 Runner 반복 실행
   - `Batch_Run` > `Device` 폴더 구조 분리 및 저장 로직 적용

3. **Phase M-4: Device Result Viewer**
   - Recent Runs에 Batch 단위 표시 및 기기별 세부 결과 조회 UI 구성
   - Live Monitor 마스터-디테일 UI 도입

4. **Phase M-5: Parallel Execution**
   - 백엔드 상태(State) 관리기를 `Map<Serial, RunState>` 구조로 변경
   - 파이썬 `asyncio` 또는 프로세스 풀을 이용한 Runner 동시 실행 지원
   - 프론트엔드 다중 상태 폴링 및 병렬 모니터링 최적화
