# QA Frontend Local Run Guide

Windows PowerShell 기준으로 QA Frontend backend/frontend를 로컬에서 실행하고 실기기 Smoke batch를 검증하는 절차입니다.

## 1. 사전 조건

- Python 환경이 준비되어 있어야 합니다.
- Node.js 및 npm이 설치되어 있어야 합니다.
- `adb`가 PATH에서 실행 가능해야 합니다.
- Android device는 USB debugging이 enabled 상태여야 합니다.
- TalkBack A11y Helper APK가 설치되어 있고 accessibility service가 활성화되어 있어야 합니다.
- SmartThings 앱이 대상 단말에 설치되어 있어야 합니다.

## 2. Backend 실행

프로젝트 루트에서 실행합니다.

```powershell
uvicorn qa_frontend.backend.main:app --reload --host 0.0.0.0 --port 8000
```

정상 확인:

- http://localhost:8000/docs
- http://localhost:8000/api/adb/status

`/api/adb/status`에서 `devices` 배열에 대상 단말이 `device` 상태로 표시되어야 합니다.

## 3. Frontend 실행

새 PowerShell 터미널을 열고 실행합니다.

```powershell
cd qa_frontend/frontend
npm install
npm run dev
```

브라우저 접속:

- http://localhost:5173

주의: 현재 Vite dev server는 `localhost` 기준 접속을 권장합니다. 환경에 따라 `127.0.0.1:5173` 접속은 실패할 수 있습니다.

## 4. ADB 확인

PowerShell에서 확인합니다.

```powershell
adb devices
```

정상 예:

```text
List of devices attached
R3CX40QFDBP	device
```

## 5. Smoke 실행 순서

1. Backend를 실행합니다.
2. Frontend를 실행합니다.
3. 브라우저에서 http://localhost:5173 에 접속합니다.
4. ADB device가 표시되는지 확인합니다.
5. `Launch`를 `Clean`으로 선택합니다.
6. `Mode`를 `Smoke`로 선택합니다.
7. `Language`를 `Current`로 선택합니다.
8. device 1개를 선택합니다.
9. `Run`을 클릭합니다.

## 6. Phase 1 Preflight 확인 로그

Run 시작 직후 backend/runner log에서 아래 로그를 확인합니다.

```text
[PREFLIGHT] device_connected PASS
[PREFLIGHT] wake_screen PASS
[PREFLIGHT] unlock_swipe PASS
```

또는 secure lockscreen 상태에 따라 unlock swipe는 WARN일 수 있습니다.

```text
[PREFLIGHT] unlock_swipe WARN
```

SmartThings foreground 확인:

```text
[PREFLIGHT] app_foreground PASS
```

Google Play 리뷰 Bottom Sheet가 나타난 경우에는 필요 시 dismiss recovery 로그가 표시됩니다.

```text
[PREFLIGHT][popup] recovered=true method='dismiss_review_sheet'
```

## 7. Live Monitor 확인

Run 중 Live Monitor가 자동으로 펼쳐지고 아래 항목이 갱신되는지 확인합니다.

- `Completed Devices`
- `Scenarios` selected/observed 표시
- `Observed Runtime Events`
- `Current Device`
- `Current Scenario`
- `Current Step / Event`
- Preflight badges
- `Latest Runtime Event`
- `Raw Latest Log`

Live Monitor는 실시간 관측 화면입니다. 최종 품질 판정은 Run History, Device Details, `summary.json`, xlsx report 기준으로 확인합니다.

## 8. 완료 후 확인

Batch 완료 후 아래 항목을 확인합니다.

- Run History에 batch가 표시됩니다.
- Device Details가 열립니다.
- TalkBack Quality가 표시됩니다.
- Quality Issues가 표시됩니다.
- Log 다운로드가 가능합니다.
- XLSX 다운로드가 가능합니다.

## 9. 자주 나는 문제

### ADB unknown

ADB 상태가 `unknown`이거나 device가 비어 있으면 먼저 PowerShell에서 확인합니다.

```powershell
adb devices
```

필요 시 ADB server를 재시작합니다.

```powershell
adb kill-server
adb start-server
adb devices
```

단말에서 USB debugging authorization 팝업이 떠 있는지도 확인합니다.

### Helper UNKNOWN

Helper 상태가 `UNKNOWN`이면 ADB 연결을 먼저 확인합니다.

```powershell
adb devices
```

이후 QA Frontend의 Helper 카드에서 설치/활성화 상태를 확인합니다. Helper APK가 설치되어 있어도 accessibility service가 비활성화되어 있으면 Run이 막힐 수 있습니다.

### Google Play 리뷰 팝업

Google Play 리뷰 Bottom Sheet의 `Not now` 버튼은 preflight popup recovery 대상입니다. 그래도 복구에 실패하면 log에서 popup recovery 흐름을 확인합니다.

```text
[PREFLIGHT][popup]
```

### 화면 OFF 상태

Phase 1 runtime preflight에서 wake screen이 자동 수행됩니다.

```text
[PREFLIGHT] wake_screen PASS
```

다만 PIN, 패턴, 생체잠금 같은 secure lockscreen은 자동 해제 대상이 아닙니다. unlock swipe는 단순 swipe만 수행하며 secure lockscreen이 남아 있으면 WARN으로 계속 진행하거나 이후 foreground 확인에서 실패할 수 있습니다.
