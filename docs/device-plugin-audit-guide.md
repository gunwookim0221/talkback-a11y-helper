# Device Plugin Audit Guide (V3)

## 한국어 요약 (Korean Summary)

### 목적
* Device Plugin Audit은 SmartThings Device Plugin의 TalkBack 자동 검증 결과를 분석하는 CLI 도구입니다.
* 실제 순회는 `script_test.py` 및 Runner가 수행합니다.
* Audit Tool은 `normal.log` 및 `*.xlsx` 결과를 분석합니다.
* Coverage 검증 및 Verdict 산출이 목적입니다.
* Frontend 없이 단독 실행 가능합니다.

---

### 사용 방법

#### 전체 Device Plugin Audit 실행
```powershell
python tools/audit_device_plugins.py --serial <DEVICE_SERIAL> --max-plugins all --output-dir output/audit_all
```
*예시:*
```powershell
python tools/audit_device_plugins.py --serial R3CX40QFDBP --max-plugins all --output-dir output/audit_all
```

---

#### 특정 플러그인만 실행
```powershell
python tools/audit_device_plugins.py --serial <DEVICE_SERIAL> --scenarios device_motion_sensor_plugin device_audio_plugin --output-dir output/audit_subset
```
*예시:*
```powershell
python tools/audit_device_plugins.py --serial R3CX40QFDBP --scenarios device_motion_sensor_plugin --output-dir output/audit_motion
```

---

#### 기존 결과 재분석 (Dry Run)
```powershell
python tools/audit_device_plugins.py --dry-run --output-dir output/audit_all
```
*설명:*
* 단말 실행 없이 기존 로그를 재분석합니다.
* Coverage Rule 수정 후 재평가할 때 주로 사용합니다.

---

### 실행 전 확인사항
* `adb devices` 연결 확인
* TalkBack 활성화
* Helper 실행 상태 확인
* SmartThings 실행 가능 상태 (포그라운드)
* 단말 잠금 해제 상태
* 외부 Popup (Google Play 등) 제거

---

### 결과 확인
**생성 파일:**
* `audit_report.md`
* `audit_report.json`
* `audit_report.csv`

**확인 순서:**
1. `audit_report.md` 확인
2. `REVIEW` 대상 확인
3. 개별 Plugin 분석
4. 수정 후 단독 Audit
5. 전체 Audit 재실행

---

### Verdict 의미
* **PASS**: 진입 성공, Local Tab 순회 성공, Coverage 충족
* **PASS_NOT_AVAILABLE**: 현재 계정/위치에 해당 Device 없음
* **REVIEW**: 순회 부족, Coverage 부족, Value Exclusion 등 사람이 확인 필요
* **FAIL**: 잘못된 진입, Traversal 실패, Target Mismatch
* **ENVIRONMENT_ERROR**: Helper 오류, Empty Dump, Popup 오염, ADB 문제

---

## Audit Evolution

### V1
* Device 진입 여부 확인
* Tab 방문 여부 확인

### V2
* Tab Coverage 확인
* Exhaustion 상태 확인

### V3
* Expected Content 검증
* `normal.log` + `*.xlsx` 통합 분석
* False PASS 최소화
* Coverage 기반 REVIEW 판정

---

## Case Study: Motion Sensor

**초기 Audit 결과:**
* `PASS`

**실제 문제:**
* `Controls` 탭 방문
* `Routines` 탭 방문
* `History` 탭 방문
하지만,
* `Temperature`
* `Vibration Sensor`
값을 실제로 읽지 못했습니다.

**결론:**
Tab 방문만으로 PASS 처리하면 안 됩니다.
**Audit V3**에서 Content Coverage 검증을 추가하여 해당 현상을 **REVIEW**로 정확히 검출하는 데 성공했습니다.

---

## 1. Overview

The **Device Plugin Audit** tool is a CLI-based utility designed to sequentially evaluate and audit all `device_*_plugin` scenarios. It orchestrates the underlying `script_test.py` runner to execute accessibility traversal on connected devices, and comprehensively analyzes the resulting `normal.log` and `.xlsx` artifacts. 

**Note**: This tool acts primarily as an auditing and reporting wrapper. It relies on the core traversal engine to execute the tests, and its primary purpose is to aggregate the data, verify content coverage, and assign a standardized verdict to each plugin.

## 2. Usage

Commands are illustrated for Windows PowerShell.

### Run All Plugins
To run an exhaustive audit across all available device plugins:
```powershell
python tools/audit_device_plugins.py --serial <DEVICE_SERIAL> --max-plugins all --output-dir output/audit_all_v3
```

### Run Specific Plugins
To audit only a specific subset of plugins:
```powershell
python tools/audit_device_plugins.py --serial <DEVICE_SERIAL> --scenarios device_motion_sensor_plugin device_audio_plugin --output-dir output/audit_subset
```

### Dry-Run (Re-analyze Existing Logs)
If you have already executed the audit and simply want to recalculate verdicts or re-generate reports without triggering a new on-device traversal:
```powershell
python tools/audit_device_plugins.py --dry-run --output-dir output/audit_all_v3
```

## 3. Pre-requisites

Ensure the following conditions are met before initiating an audit:
- The device is successfully connected and recognized via `adb devices`.
- **TalkBack** is enabled on the device.
- The **Helper app** is running and authorized.
- **SmartThings** is capable of running in the foreground.
- The device screen is unlocked.
- Any interfering external pop-ups or Google Play dialogues (contamination) are cleared.

## 4. Output Artifacts

Upon completion, the tool will generate the following artifacts within the specified `--output-dir`:
- `audit_report.md`: A human-readable markdown breakdown of coverage and verdicts.
- `audit_report.json`: Machine-readable JSON structured report.
- `audit_report.csv`: Tabular spreadsheet format report.
- Subdirectories per scenario (e.g., `device_motion_sensor_plugin/`) containing:
  - `*.normal.log`
  - `*.xlsx` (Data frames)

## 5. Verdict Definitions

The audit assigns one of five possible verdicts to each scenario:

- **PASS**: The runner successfully entered the target, explored all detected local tabs, fulfilled coverage goals, and encountered the expected critical contents.
- **PASS_NOT_AVAILABLE**: The target device card is currently absent from the user's account or location, so the runner correctly recognized the absence and terminated safely.
- **REVIEW**: The plugin completed its traversal, but manual inspection is needed. This is triggered by missed tabs, insufficient content coverage, unexpected exclusions, or suspicious traversal loops.
- **FAIL**: A critical plugin logic failure occurred (e.g., navigated to the wrong target, failed to match intended UI boundaries, or traversal crash).
- **ENVIRONMENT_ERROR**: The execution failed due to environmental instability (e.g., Helper app returned null, empty dump payload, pop-up contamination, or ADB/preflight connectivity issues).

## 6. Audit V3 Coverage Criteria

V3 is a strict transition from simply "visiting" tabs to ensuring the content *within* those tabs is adequately reviewed. The reporting tool merges signals from both `normal.log` and `*.xlsx` files to track:
- `detected_tabs` vs `visited_tabs`
- `tabs_exhausted` (viewport bounds verified)
- `tab_coverage_summary` (unique labels, focus counts, representative checks)
- `missing_content`

**Rule of Thumb**: A scenario is no longer granted a `PASS` merely for visiting all tabs; it must demonstrate functional content coverage inside those tabs.

## 7. Plugin Expected Content Rules (`PLUGIN_EXPECTED_CONTENT`)

To combat false positives, the framework evaluates `PLUGIN_EXPECTED_CONTENT`—a dictionary of required text/synonym groups per plugin. 
- **Conservative Application**: These rules are intentionally kept conservative. The priority is to flag severe issues (`REVIEW`) rather than failing a test outright due to minor localization or state variants.
- **Synonym Groups**: Requirements are formatted as lists of interchangeable terms. For instance, if a group is `["Temperature", "°C"]`, the engine considers the group satisfied if it finds *either* term.
- These rules will be incrementally tuned according to geographic locales and varying device states.

### Example Rules

- **Motion Sensor**: Requires components like `Motion sensor`, `Battery`, `Temperature / °C / °F`.
- **Audio**: Requires media controls like `Play / Pause`, `Next`, `Previous`, `Volume`.
- **Door Lock**: Requires components like `Lock / Unlock`, `History`.
- **Home Camera**: Requires views like `Camera`, `Live / Connecting`, `Offline`, `History`.

## 8. Understanding the Results

A typical execution summary will look like this:

```
Total: 12
PASS: 10
REVIEW: 2
FAIL: 0
ENVIRONMENT_ERROR: 0
```

**Analyzing a REVIEW Case:**

- `device_home_camera_plugin`: Failed due to `missing content coverage`. (e.g., the traversal engine only hit diagnostics and missed the live camera feed).
- `device_water_leak_sensor_plugin`: Failed due to `sensor values excluded`. (e.g., the sensor state like "Dry" was explicitly filtered out by the logic, preventing proper verification).

## 9. Known Limitations

- **Rule Rigidity**: The `expected_content` rules are heuristics intended to catch suspicious traversals, not absolute source-of-truth answers. They might flag `REVIEW` on valid screens depending on UI localization or dynamic states.
- **Dry-Run Limits**: A `--dry-run` solely relies on existing logs. If the logs are incomplete or out of date, the dry-run report will reflect those deficiencies.
- **Log Synthesis**: Excel logs (`*.xlsx`) occasionally strip fine-grained local tab markers. The audit engine dynamically correlates `normal.log` and `.xlsx` to rebuild an accurate picture of what happened.
- **Environment Constraints**: `ENVIRONMENT_ERROR` represents external device/network issues, not inherently a failure of the plugin's code quality.

## 10. Recommended Workflow

1. Execute the full suite: `python tools/audit_device_plugins.py --serial <DEVICE_SERIAL> --max-plugins all --output-dir output/audit_all`
2. Inspect the generated `audit_report.md`.
3. Select and prioritize scenarios flagged for `REVIEW`.
4. Debug and patch the individual plugin or traversal rules.
5. Re-run an isolated audit for that specific plugin using the `--scenarios` parameter.
6. Once stable, run the full `--max-plugins all` command to confirm no regressions.
7. Commit and push the updates.

---

### Recent Verification Baseline (V3 Conservative Rules)
*As of latest Audit V3 test run*

- **Total**: 12
- **PASS**: 10
- **REVIEW**: 2
  - `device_home_camera_plugin`: missing content coverage
  - `device_water_leak_sensor_plugin`: sensor values excluded
- **FAIL**: 0
- **ENVIRONMENT_ERROR**: 0
