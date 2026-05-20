# QA Frontend Platform Phase 1

Local Control Panel MVP for the existing TalkBack QA runner.

## Scope

- The backend runs `python script_test.py` as a subprocess from the repository root.
- The existing runner, Android helper, `SMART_NEXT`, `move_smart`, and `tb_runner/collection_flow.py` are not modified.
- CLI and UI runs use the same repository working directory, `config/runtime_config.json`, and `output/` directory.
- Scenario checkboxes are present in the UI, but Phase 1 does not rewrite `runtime_config.json`; runs use the current config.

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
- `GET /api/scenarios`
- `POST /api/run/start`
- `POST /api/run/stop`
- `GET /api/run/status`
- `GET /api/run/log`
- `GET /api/outputs`
- `GET /api/outputs/{filename}`

Run logs are written under `qa_frontend_runs/`. Runner output files continue to be written under `output/`.

## Frontend

Run:

```powershell
cd qa_frontend/frontend
npm install
npm run dev
```

Open the Vite URL, usually `http://localhost:5173`.

## Limitations

- Only one run can be active at a time.
- Smoke and Full both execute `script_test.py`; current scenario enablement comes from `config/runtime_config.json`.
- Helper install searches for APKs under `app/build/outputs/apk/**/*.apk` and `android/app/build/outputs/apk/**/*.apk`.
- The backend reports ADB errors in API responses instead of crashing the server.
