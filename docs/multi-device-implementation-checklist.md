# Multi Device Implementation Checklist

## Phase M-1.5: Pre-Implementation Audit

* [x] ADB Serial Audit
  * [x] adb shell 호출 위치 확인
  * [x] adb logcat 호출 위치 확인
  * [x] adb install / pull / push 호출 위치 확인
  * [x] -s <serial> 또는 ANDROID_SERIAL 주입 가능 여부 확인
* [x] Output Directory Audit
  * [x] output/ 하드코딩 위치 확인
  * [x] qa_frontend_runs 사용 위치 확인
  * [x] runner.log / report.xlsx / summary.json 저장 위치 확인
* [x] Run State Audit
  * [x] qa_frontend/backend/runner.py의 단일 run_state 구조 확인
  * [x] Batch level 누적 상태 관리 필요 여부 확인

## Phase M-2: Device Detection

* [x] Backend /api/devices 추가
* [x] adb devices 파싱
* [x] serial 반환
* [x] device state 반환
* [x] model name 반환
* [x] helper_ready 반환
* [x] talkback_enabled 반환
* [x] foreground_package 반환
* [x] Frontend Device Panel 추가
* [x] 단말 체크박스 선택 UI 추가
* [x] device별 preflight 상태 표시

## Phase M-3: Sequential Batch Run

* [x] selected_devices 배열을 backend start_run에 전달
* [x] batch_id 생성
* [x] qa_frontend_runs/batch_xxx 폴더 생성
* [x] device_<model>_<serial> 하위 폴더 생성
* [x] 기존 runner를 serial별로 순차 호출
* [x] runner CLI에 --serial 추가
* [x] runner CLI에 --output-dir 추가
* [x] A11yAdbClient에 dev_serial 전달
* [x] collection_flow.py의 Path("output") 하드코딩 제거 또는 output_dir 주입
* [x] device별 summary.json 생성
* [x] batch_summary.json 생성

## Phase M-4: Device Result Viewer

* [x] Recent Runs에 Batch Run 표시
* [x] Batch 상세 화면 추가
* [x] device별 결과 리스트 표시
* [x] device별 runner.log 열람
* [x] device별 report.xlsx 링크 표시
* [x] quality summary 표시

## Phase M-5: Parallel Execution (Deferred)

> 현재 실전 운영은 Sequential Batch Run 기준으로 진행한다.
> 병렬 실행은 안정화 이후 별도 phase로 재개한다.

* [ ] RunState를 Map<serial, RunState> 또는 BatchState 구조로 확장
* [ ] device별 logcat stream 분리
* [ ] subprocess 병렬 실행 검토
* [ ] USB/ADB 부하 제한 정책 추가
* [ ] 병렬 실행 실패 시 partial result 처리
* [ ] sequential fallback 유지

## Phase M-4 Operational Fixes

* [x] Batch payload includes launch/language/scenario selection
* [x] Batch runner uses selected runtime_config copy
* [x] Batch runner applies clean/warm launch
* [x] Batch runner writes runner.log during execution

## Phase M-4 UX Fixes

* [x] Batch log tail displayed during running batch
* [x] Batch log available after selecting finished batch
* [x] Batch Runs and Single Runs labels clarified
* [x] Batch Details links use explicit runner_log/log/xlsx paths

## Phase M-3 Smoke Test

* [x] TypeScript check passed
* [x] Backend routes import passed
* [x] Device Panel API passed
* [x] Single-device batch smoke passed
* [x] Batch status polling passed
* [x] Output isolated under qa_frontend_runs/batch_xxx/device_xxx
* [x] batch_summary.json generated
* [x] Existing single-run fallback preserved

## Non-Goals for Now

* [ ] M-2에서 실행 로직 수정하지 않기
* [ ] M-3에서 병렬 실행하지 않기
* [ ] runner 내부 대규모 리팩토링하지 않기
* [ ] Live Monitor 완전 병렬 UI는 M-5 전까지 보류

---

## Current Recommended Next Step
M-5 Parallel Execution은 당분간 보류하고, 실전 운영에서 안정성을 검증하며 남은 버그를 해결한다.
