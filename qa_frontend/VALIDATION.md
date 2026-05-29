# QA Frontend Phase 1 Validation

Phase 1 MVP validation is split into:

- Automated checks that do not require a real Android device
- Manual checks that require a connected device, helper service state, or end-to-end runner execution

The constraints for this validation set are:

- Do not modify Android helper logic
- Do not modify `script_test.py`
- Do not modify `tb_runner/collection_flow.py`
- Keep automated checks device-free

## Automated Validation

Run these commands from the repository root:

```powershell
python -m py_compile qa_frontend/backend/*.py
python -m pytest tests/test_qa_frontend_outputs.py tests/test_qa_frontend_adb.py tests/test_qa_frontend_preflight.py tests/test_qa_frontend_runner.py -q
python tools/validate_qa_frontend.py
cd qa_frontend/frontend
npm run build
```

PowerShell note:

- `python -m py_compile qa_frontend/backend/*.py` may pass the wildcard literally.
- Equivalent PowerShell-safe form:

```powershell
Get-ChildItem qa_frontend/backend/*.py | ForEach-Object { python -m py_compile $_.FullName }
```

PASS criteria:

- `py_compile` exits with code `0`
- pytest exits with code `0`
- `tools/validate_qa_frontend.py` prints only `[PASS]` lines
- `npm run build` produces `qa_frontend/frontend/dist/`

FAIL logs to inspect:

- Python traceback from the command output
- backend import errors from `qa_frontend/backend/*.py`
- Vite build errors from `qa_frontend/frontend`

## Manual Checklist

### 1. Backend startup

Command:

```powershell
uvicorn qa_frontend.backend.main:app --reload
```

PASS:

- Server starts without traceback
- `GET /api/health` returns `{"status":"ok"}`
- `GET /api/scenarios` returns a non-empty `scenarios` array

FAIL logs:

- Uvicorn console
- Python import traceback

### 2. Frontend startup

Command:

```powershell
cd qa_frontend/frontend
npm run dev
```

PASS:

- Vite dev server starts
- Browser opens `http://localhost:5173`
- Initial screen renders without blank page or uncaught API crash

FAIL logs:

- Browser DevTools console
- Network tab for `/api/*`
- Vite terminal output

### 2-1. Scenario default selection policy

PASS:

- `/api/scenarios` still exposes each scenario's source `enabled` state from `config/runtime_config.json`
- Frontend initial checkbox selection is `global_nav_main` only
- `global_nav_main` is the default because Phase 1 smoke should start from the smallest stable sanity-check entry point
- Source-enabled scenarios such as `life_family_care_plugin` are not auto-selected just because the source config has `enabled=true`
- UI text clearly separates run selection count from source runtime_config enabled count
- `Select Global Nav` selects only `global_nav_main`
- `Clear All` clears the run selection and a run start should be blocked by the backend with `No scenario selected`

FAIL logs:

- Browser DevTools console
- `/api/scenarios` response payload
- `/api/run/start` response payload

### 3. ADB status 확인

Precondition:

- Real device connected with USB debugging enabled

PASS:

- `GET /api/adb/status` returns `status=ok`
- Response `devices` contains target device serial and state `device`
- UI reflects connected device state without crashing

FAIL logs:

- Backend response payload from `/api/adb/status`
- `adb devices` terminal output
- Uvicorn console

### 4. Helper status 확인

Precondition:

- Helper APK installed or intentionally absent for negative check

PASS:

- Installed + enabled returns `status=ok`
- Installed + disabled returns `status=disabled`
- Local APK missing returns `status=apk_not_found` and shows build command `.\gradlew.bat :app:assembleDebug`
- Missing package returns `status=not_installed`
- ADB/device failure returns `status=error` with `adb_status=adb_error`
- `POST /api/helper/enable` preserves existing TalkBack services and appends only `com.iotpart.sqe.talkbackhelper/com.iotpart.sqe.talkbackhelper.A11yHelperService`
- `POST /api/helper/open-accessibility-settings` opens Android Accessibility Settings best-effort
- UI helper panel reflects the returned backend state

Manual setup path:

- `설정 > 접근성 > 설치된 앱 > TalkBack A11y Helper > 사용 중`

FAIL logs:

- Backend response payload from `/api/helper/status`
- `adb shell pm list packages`
- `adb shell settings get secure enabled_accessibility_services`
- Uvicorn console

### 5. Runtime Preflight status

PASS:

- `/api/run/status` includes `preflight_state`, `talkback_state`, `helper_state`, and `foreground_package`
- `/api/run/status` includes `language_mode` and `device_locale`
- `/api/run/dashboard` includes parsed runtime metrics, scenario progress, and event feed data without backend crash
- `/api/run/dashboard` displays `language_mode` and `device_locale`
- `/api/runs/recent` separates `process_status` from `scenario_result_status`
- `/api/runs/recent` includes the run language mode and verified device locale when available
- Scenario status separates `passed`, `warning`, and `failed`; `FAIL_STUCK` or `repeat_no_progress` after successful entry/rows/summary is warning unless hard validation failure evidence exists
- Run completion writes `qa_frontend_runs/<run_id>_summary.json`
- `summary.json` includes `language_mode` and `device_locale`
- `summary.json` is a cache/index; the run log remains the source of truth
- Recent Runs uses valid `summary.json` as a fast path and falls back to log parsing when the summary is missing or malformed
- `qa_frontend_runs/<run_id>_<mode>.log` contains `[QA_FRONTEND][preflight]` lines
- Foreground verification failure is logged as unknown/non-matching and does not block by itself

FAIL logs:

- `qa_frontend_runs/*.log`
- `/api/run/start` response payload
- `/api/run/status` response payload
- `/api/run/dashboard` response payload
- `qa_frontend_runs/<run_id>_summary.json`

### 5A. Language Mode

PASS:

- `Current device language` starts a run without locale change commands
- `Korean (ko-KR)` reads current locale, attempts `ko-KR`, verifies `device_locale=ko-KR`, then starts the run
- `English (en-US)` reads current locale, attempts `en-US`, verifies `device_locale=en-US`, then starts the run
- A locale verification failure blocks the run with a clear language setup error
- On devices that do not allow ADB system language changes, `/api/run/status` exposes `manual_language_change_required=true`, `target_locale`, `device_locale`, and `language_error`
- The top action banner shows `Open Language Settings` and tells the user to run again with `Current device language`
- `POST /api/device/open-language-settings` opens Android Language Settings, falling back to general Settings if needed
- The selected language mode appears in Run panel, Runtime Dashboard, Recent Runs, and summary JSON

FAIL logs:

- `qa_frontend_runs/*.log` lines with `[QA_FRONTEND][language]`
- `/api/run/status` response payload
- `adb shell getprop persist.sys.locale`
- `adb shell getprop ro.product.locale`

### 6. SmartThings 미실행 상태에서 Warm launch smoke

Precondition:

- SmartThings is not foreground
- Launch mode is `Warm launch`
- Note: `Warm launch` is now a debug option. The default UI selection is `Clean launch`.

PASS:

- `/api/run/start` logs `launch_mode='warm'`
- `force_stop_attempted='false'`
- monkey launch is attempted
- SmartThings becomes foreground or foreground check is logged best-effort without blocking only on foreground parse failure
- `outside_app` does not recur at scenario start because SmartThings was not foreground

FAIL logs:

- `qa_frontend_runs/*.log`
- `adb shell dumpsys window`
- `adb shell dumpsys activity activities`
- `output/*.log`

### 7. SmartThings 실행 상태에서 Clean launch smoke

Precondition:

- SmartThings is already running or foreground
- Launch mode is `Clean launch`

PASS:

- `/api/run/start` logs `launch_mode='clean'`
- `force_stop_attempted='true'`
- monkey launch succeeds after force-stop
- Run proceeds only after preflight passes

FAIL logs:

- `qa_frontend_runs/*.log`
- Backend response payload from `/api/run/start`
- Uvicorn console

### 8. TalkBack OFF 상태에서 UX 확인

Precondition:

- TalkBack is disabled on the connected device

PASS:

- Run does not start `script_test.py`
- UI displays `TalkBack A11y Helper is enabled, but Samsung/Google TalkBack is disabled. Enable TalkBack and retry.`
- UI offers `Enable TalkBack via ADB`
- UI offers `Open Accessibility Settings`
- `POST /api/talkback/enable` appends a Samsung or Google TalkBack service without removing TalkBack A11y Helper
- `/api/run/status` has `preflight_state=blocked` and `talkback_state=disabled`
- `qa_frontend_runs/*.log` contains `[QA_FRONTEND][preflight][talkback] status='disabled'`

FAIL logs:

- Browser UI Runtime Preflight panel
- `/api/run/start` response payload
- `qa_frontend_runs/*.log`

### 9. Accessibility settings 자동 이동 확인

Precondition:

- TalkBack is disabled

PASS:

- Backend attempts `adb shell am start -a android.settings.ACCESSIBILITY_SETTINGS`
- Device opens Accessibility settings, when supported by the OS
- UI shows `Accessibility settings opened on device` if the command succeeds

FAIL logs:

- `qa_frontend_runs/*.log`
- `adb shell am start -a android.settings.ACCESSIBILITY_SETTINGS`
- Uvicorn console

### 10. Clean launch Google Play 리뷰 팝업 자동 dismiss 확인

Precondition:

- Clean launch after SmartThings is likely to show a Google Play review/rating prompt

PASS:

- `qa_frontend_runs/*.log` contains `[QA_FRONTEND][preflight][popup] detected_package='com.android.vending'`
- Preflight logs include `uiautomator_package` and `uiautomator_focused_package`
- Dismiss method is either a safe dismiss label such as `Not now`/`No thanks`/`나중에` or BACK fallback
- Log shows `foreground_after='com.samsung.android.oneconnect' result='cleared'`
- `/api/run/status` exposes `popup_detected=true`, `popup_package=com.android.vending`, and `popup_result=cleared`
- No star rating, submit, send, review, `리뷰`, `평가`, or `제출` action is clicked

FAIL logs:

- `qa_frontend_runs/*.log`
- `/api/run/status` response payload
- `adb shell dumpsys window`
- UIAutomator dump captured manually if the prompt remains visible

### 11. com.android.vending focus 잔류 여부 확인

PASS:

- After preflight, foreground/focus package is `com.samsung.android.oneconnect`
- `com.android.vending` does not appear as the final foreground, UIAutomator root, or UIAutomator focused package
- If `com.android.vending` remains, preflight returns a clear `external_popup_uncleared` block/warning state before runner scenario logic starts

FAIL logs:

- `[QA_FRONTEND][preflight][popup]` lines in `qa_frontend_runs/*.log`
- `/api/run/start` and `/api/run/status` response payloads

### 12. global_nav_main bottom nav 탐색 확인

PASS:

- `global_nav_main` starts after popup preflight is cleared
- Log no longer fails immediately with `packageName='com.android.vending'`
- `TAB verify reason='no_bottom_nav_candidates'` does not recur from Google Play focus takeover

FAIL logs:

- `qa_frontend_runs/*.log`
- `output/*.log`
- Runtime Preflight panel values

### 13. outside_app 재발 여부 확인

PASS:

- Warm and Clean launch runs do not fail immediately with `outside_app`
- If `outside_app` appears later, logs show SmartThings launch and foreground package evidence before runner start

FAIL logs:

- `qa_frontend_runs/*.log`
- `output/*.log`
- Runtime Preflight panel values

### 14. `global_nav_main` smoke

Precondition:

- Device connected
- Runtime config prepared so only `global_nav_main` smoke target is enabled

PASS:

- Run starts from UI
- Smoke mode shows reduced-step intent in the Run panel and uses a reduced `max_steps` override in the per-run runtime config
- `qa_frontend_runs/<run_id>_smoke.log` is created
- Run reaches terminal `finished` or expected stop condition without backend crash
- Output/log evidence shows `global_nav_main` traversal happened

FAIL logs:

- `qa_frontend_runs/*.log`
- `output/*.log`
- Browser Network tab for `/api/run/start`, `/api/run/status`, `/api/run/log`

### 15. Life plugin smoke

Target example:

- `life_food_plugin` or another intended life plugin scenario

PASS:

- UI run completes without backend error transition caused by frontend integration
- Log tail updates while run is active
- Expected scenario id appears in run log/output log

FAIL logs:

- `qa_frontend_runs/*.log`
- `output/*.log`
- Uvicorn console

### 16. Device plugin smoke

Target example:

- `device_smoke_sensor_plugin` or another device plugin scenario

PASS:

- Run can be started from the frontend
- Backend remains responsive while scenario executes
- Scenario-specific log evidence appears in run log or output log

FAIL logs:

- `qa_frontend_runs/*.log`
- `output/*.log`
- Browser Network tab

### 17. Stop button test

PASS:

- Start a long-enough run
- Press Stop in the UI
- `/api/run/stop` returns state `stopped` or subsequent `/api/run/status` transitions to `stopped`
- Process terminates without orphaned repeated output growth

FAIL logs:

- `qa_frontend_runs/*.log`
- `/api/run/stop` response payload
- OS process list if `script_test.py` appears to remain alive

### 18. Full regression 1회

PASS:

- `full` mode can be launched from the UI
- Full mode shows source-`max_steps` regression intent in the Run panel and preserves source `max_steps` in the per-run runtime config
- Backend remains responsive during the long run
- Final state becomes `finished`, `stopped`, or a scenario-level failure reflected in logs, not a frontend/backend crash

FAIL logs:

- `qa_frontend_runs/*.log`
- `output/*.log`
- Uvicorn console

### 19. Output/download 확인

PASS:

- `/api/outputs` lists generated `.log`, `.json`, or `.xlsx` files
- Selecting a listed file downloads the matching file
- Invalid filenames and traversal attempts are rejected
- `/api/run/log/download` returns the current run log after the run finishes or stops
- Recent Runs shows newest-first rows with read-only log/xlsx download links

FAIL logs:

- Browser Network tab for `/api/outputs` and `/api/outputs/{filename}`
- Backend HTTP status codes
- Uvicorn console

### 20. Log tail 장시간 확인

PASS:

- `/api/run/log` continues returning recent lines during a long run
- `/api/run/dashboard` continues returning normalized summary data during a long run
- UI stays responsive during repeated polling
- Tail text matches current `qa_frontend_runs` file contents

FAIL logs:

- Browser Network tab for `/api/run/log`
- `qa_frontend_runs/*.log`
- Uvicorn console

## Notes

- Device-required scenarios remain manual because they depend on real ADB transport, helper state, SmartThings screen state, and live runner behavior.
- The automated set only validates `qa_frontend` importability, API structure, safe path handling, static file presence, and runner guard behavior.
- Smoke means a reduced-step sanity check for the currently selected scenarios. Full means a regression run that keeps source `runtime_config.json` `max_steps`.
- Source `enabled` flags are display-only in the UI. The actual run selection comes from the current checkbox state, which defaults to `global_nav_main`.
- Launch mode defaults to `Clean launch` so SmartThings starts from a more stable baseline. `Warm launch` is retained for advanced/debug runs that intentionally preserve the current app state.
- Presets (`Global Nav Smoke`, `Life Smoke`, `Device Smoke`, `Select All Scenarios`, `Clear All`) only change frontend checkbox selection state. Smoke/Full buttons choose execution mode. Presets do not modify the source runtime config.
- Run status is process execution status. Scenario status is validation result status parsed from the run log and may be `failed` even when the process exits successfully.
