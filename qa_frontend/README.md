# QA Frontend Platform Phase 1

Local Control Panel MVP for the existing TalkBack QA runner.

## Scope

- The backend runs `python script_test.py` as a subprocess from the repository root.
- The existing runner, Android helper, `SMART_NEXT`, `move_smart`, and `tb_runner/collection_flow.py` are not modified.
- CLI and UI runs use the same repository working directory, `config/runtime_config.json`, and `output/` directory.
- Scenario checkboxes are applied through an isolated per-run runtime config; the source `config/runtime_config.json` is not rewritten.
- The frontend defaults the run selection to `global_nav_main` for a predictable sanity check; source `enabled` flags are shown for reference only.
- Selected Smoke runs use reduced per-scenario `max_steps` in the isolated per-run runtime config, while Selected Full runs preserve source `max_steps` for the selected scenarios.
- Scenario presets only change checkbox selection. All Plugins selects only `device_*_plugin` and `life_*_plugin`; All Scenarios also includes navigation/main scenarios. Selected Smoke/Selected Full choose the execution mode.
- Launch mode now defaults to `Clean launch` for more consistent SmartThings entry; `Warm launch` remains available as a debug option.
- Phase A language mode runs one selected language per run: current device language, Korean (`ko-KR`), or English (`en-US`).

## Backend

Install dependencies:

```powershell
pip install -r requirements-qa_frontend.txt
```

Run:

```powershell
uvicorn qa_frontend.backend.main:app --reload
```

APIs:

- `GET /api/health`
- `GET /api/adb/status`
- `GET /api/helper/status`
- `POST /api/helper/install`
- `POST /api/helper/enable`
- `POST /api/helper/open-accessibility-settings`
- `POST /api/talkback/enable`
- `POST /api/device/open-language-settings`
- `GET /api/scenarios`
- `POST /api/run/start`
- `POST /api/run/stop`
- `GET /api/run/status`
- `GET /api/run/dashboard`
- `GET /api/run/log`
- `GET /api/run/log/download`
- `GET /api/runs/recent`
- `GET /api/runs/recent/{run_id}/log`
- `GET /api/runs/{run_id}/devices/{device_id}/crashes`
- `GET /api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}`
- `GET /api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}/screenshot`
- `GET /api/runs/{run_id}/devices/{device_id}/crashes/{crash_event_id}/download`
- `GET /api/outputs`
- `GET /api/outputs/{filename}`

Phase 10 Compare APIs are documented in the repository [operational runbook](../docs/operations/talkback-operational-runbook.md):

- `GET /api/comparator/baselines`
- `GET /api/comparator/candidates`
- `POST /api/comparator/compare`
- `GET /api/comparator/history`
- `GET /api/comparator/results/{comparison_id}` and report/download routes

Run logs are written under `qa_frontend_runs/`. Runner output files continue to be written under `output/`.
When a run reaches a terminal state, the backend writes `qa_frontend_runs/<run_id>_summary.json` as a structured sidecar. The log remains the source of truth; the summary is a secondary cache/index for Recent Runs, dashboards, and future queue/statistics work.

At run start, the backend applies `adb shell svc power stayon true` and records the prior
`stay_on_while_plugged_in` value. At run end it restores that exact value only when the
setting still matches the value applied by the run. If the setting changes externally
during the run, cleanup leaves it unchanged rather than overwriting the user's developer option.

Recent Runs is read-only. It exposes the latest run summaries plus log/xlsx downloads without rewriting source config or adding rerun behavior.
Runtime Dashboard is read-only. It parses the current run log for best-effort progress, metrics, and event feed data while keeping the log as the source of truth.
Run history separates process status from scenario result status. `process_status` describes execution (`success`, `failed`, `stopped`, `running`), while `scenario_result_status` describes parsed validation results (`passed`, `warning`, `failed`, `partial`, `unknown`).
Recent Runs uses `summary.json` as a fast path when present and valid. If the summary is missing or malformed, it falls back to parsing the log.

Crash Issues APIs are read-only views over device crash artifact directories under `qa_frontend_runs/<batch_id>/<device_id>/crashes/<crash_event_id>/`. The detail endpoint returns metadata and `crash_repro.md` text, the screenshot endpoint returns `crash_screenshot.png`, and the download endpoint returns a best-effort zip containing available crash artifacts.

## Frontend

Run:

```powershell
cd qa_frontend/frontend
npm install
npm run dev
```

Open the Vite URL, usually `http://localhost:5173`.

Crash Issues is available from:

```text
Run History > Batch Details > Device Details > Crash Issues
```

Each Crash Card shows event id, crash type, scenario, recovery result, timestamp, and artifact availability. Operators can view the repro guide, preview the screenshot, or download a zip of the available artifacts.

## TalkBack A11y Helper

The TalkBack A11y Helper APK is not stored in git. It is generated under `app/build/`, which is ignored by `.gitignore`.
After a fresh clone or pull on another PC, build it when needed:

```powershell
.\gradlew.bat :app:assembleDebug
```

QA Frontend searches these APK paths:

- `app/build/outputs/apk/**/*.apk`
- `android/app/build/outputs/apk/**/*.apk`

Use the Helper card to install the APK and then enable the accessibility service. `Enable via ADB` appends the TalkBack A11y Helper service to the existing `enabled_accessibility_services` value and preserves any existing TalkBack service.
If ADB enable is unavailable on the device, open Settings manually:

```text
설정 > 접근성 > 설치된 앱 > TalkBack A11y Helper > 사용 중
```

When preflight is blocked because Samsung/Google TalkBack itself is disabled, use `Enable TalkBack via ADB`. That action appends the installed Samsung or Google TalkBack service to the existing `enabled_accessibility_services` value, preserves the TalkBack A11y Helper service, and sets `accessibility_enabled=1`.

## Language Mode

QA Frontend supports a single language mode per run:

- `Current device language`: run without changing the device language.
- `Korean (ko-KR)`: switch the device locale to `ko-KR`, verify it, then start the run.
- `English (en-US)`: switch the device locale to `en-US`, verify it, then start the run.

Some Samsung/One UI devices do not allow the shell user to change the effective system language through ADB. In that case, QA Frontend blocks the run with `manual_language_change_required`, shows a top action banner, and offers `Open Language Settings`. Change the device language manually, then run again with `Current device language`. `Current device language` always runs without a language change attempt.

Phase A does not run multiple languages in sequence. Queue, multi-run, and Korean+English batch execution are intentionally out of scope.

## Limitations

- Only one run can be active at a time.
- Selected Smoke and Selected Full both execute `script_test.py`; scenario enablement comes from the per-run runtime config generated by the backend.
- Selected Smoke is a reduced-step sanity check. Selected Full keeps source `max_steps` for the selected scenarios.
- Presets only change the current checkbox selection. All Plugins selects plugin scenarios only; All Scenarios includes navigation/main scenarios too. They do not change Selected Smoke/Selected Full mode and do not edit `config/runtime_config.json`.
- Language mode applies to one run only and is recorded in run status, dashboard, recent runs, and summary JSON.
- Helper install searches for APKs under `app/build/outputs/apk/**/*.apk` and `android/app/build/outputs/apk/**/*.apk`.
- The backend reports ADB errors in API responses instead of crashing the server.
