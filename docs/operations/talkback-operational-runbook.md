# TalkBack Accessibility Helper Operational Runbook

Controlled/manual Phase 10 procedure. Human Approval is explicit; Comparator and Frontend do not mutate Approved Baselines.

## 1. Purpose

Install a clean checkout, run English/Korean Full Validation, create and validate a Candidate, compare it with the correct predecessor, review JSON/Markdown, approve a new Baseline, migrate a portable observation bundle, verify the repository, and publish reviewed changes.

## 2. Preconditions

- Windows PowerShell, Python 3.10–3.12, Git, Node/npm, and Android platform tools.
- A supported model in config/device_classification_policy.json.
- Helper APK built locally; it is not stored in Git.
- Reviewed limitation disposition and reviewer identity before repository writes.

    python -m pip install -r requirements-script_test.txt
    python -m pip install -r requirements-qa_frontend.txt
    Set-Location qa_frontend/frontend
    npm install
    Set-Location ../..

## 3. Repository Clean Check

    git status --short
    git diff --check
    git log -1 --oneline --decorate

Resolve dirty-source findings; do not reset unrelated user changes.

## 4. Device and ADB Preflight

    adb devices -l
    adb shell getprop ro.product.model
    adb shell getprop ro.build.version.sdk
    adb shell getprop ro.build.version.release
    .\gradlew.bat :app:assembleDebug

The model must be listed in config/device_classification_policy.json. Unknown models require policy review. Use QA Frontend Helper/TalkBack actions and resolve locale, TalkBack, popup, and ADB blockers first.

## 5. QA Frontend Startup

From the repository root:

    uvicorn qa_frontend.backend.main:app --reload

In another PowerShell:

    Set-Location qa_frontend/frontend
    npm run dev

Open the Vite URL, normally http://localhost:5173.

    Invoke-RestMethod http://127.0.0.1:8000/api/health
    Invoke-RestMethod http://127.0.0.1:8000/api/comparator/baselines
    Invoke-RestMethod http://127.0.0.1:8000/api/comparator/candidates

Available run / candidate is a local input list, not an approval list. APPROVED SOURCE requires exact Candidate/source-run/source-batch identity match with an Approved Baseline.

## 6. Full Validation Profile

Select Full Validation, Clean launch, all scenarios, and the target locale. The profile enables Full mode, Coverage Probe, Evidence Ledger, Identity V2, Production Traversal V2, and Profiler; Shadow Validation is off. Smoke/Targeted runs are reproduction inputs, not approval evidence.

## 7. English Full Run / 8. Korean Full Run

Run once with English (en-US) and once with Korean (ko-KR). Resolve manual language changes if required. Preserve each terminal run summary, Environment Profile, Evidence, XLSX, Coverage, Identity, Recovery, Profiler, and crop artifacts. English and Korean are separate BaselineKey slots.

## 9. Candidate Generation

Batch Runner automatically creates `candidate_*.baseline_candidate.json` after a Full Validation only when the batch is `finished`, the device is `passed` with return code `0`, the full Scenario Registry was selected and reached terminal state, `no_target_candidate_scenarios` is `0`, and all required artifacts are available. Smoke, targeted/custom/debug runs, stopped/cancelled/crashed runs, device failures, partial runs, and incomplete artifacts do not create a Candidate.

Automatic generation is additive (`write=True, integrate=False`): it does not approve, integrate, or overwrite an existing Candidate. After a qualifying run completes, Batch Runner first builds a read-only preview and then writes exactly one Candidate. It verifies the output file, Candidate ID, and canonical document digest before recording success. A readable `NOT_ELIGIBLE` Candidate is still created and remains selectable for Comparator review. The operating flow is:

```text
Full Validation
  -> Candidate automatic generation (when all conditions pass)
  -> Comparator
  -> Human Review
  -> Approval
  -> Baseline
```

### Candidate generation diagnostics and recovery

Each automatic attempt appends an event to `<device_run>/candidate_generation.json`. This additive, machine-readable artifact retains timestamp, batch/device/run context, Candidate ID/digest/output path, and a bounded failure message where applicable. Event values are `AUTO_CANDIDATE_STARTED`, `AUTO_CANDIDATE_SKIPPED`, `AUTO_CANDIDATE_PREVIEW_SUCCEEDED`, `AUTO_CANDIDATE_PREVIEW_FAILED`, `AUTO_CANDIDATE_WRITE_STARTED`, `AUTO_CANDIDATE_WRITE_SUCCEEDED`, `AUTO_CANDIDATE_WRITE_FAILED`, and `AUTO_CANDIDATE_ALREADY_EXISTS`. Batch Runner also emits the same event name to its backend logger for live operator visibility.

`AUTO_CANDIDATE_WRITE_FAILED` does not change a finished Batch or cause a device run to fail. When the completed run still has terminal summaries, zero `NO_TARGET_CANDIDATE`, and all required artifacts, a Full Run does not need to be repeated: inspect `candidate_generation.json`, correct the local write/runtime issue, then safely use the existing explicit builder command below with `write=True, integrate=False`. Verify the new Candidate with the offline validation commands before Comparator review.

The implemented Candidate builder remains available for historical backfill or explicit regeneration on a completed device run containing `summary.json`:

    from pathlib import Path
    from tb_runner.baseline_candidate_builder import build_baseline_candidate
    run_root = Path(r"qa_frontend_runs\<batch_id>\<device_run>")
    result = build_baseline_candidate(run_root, write=True, integrate=False)
    print(result.path)
    print(result.candidate.candidate_id, result.candidate.approval_state.value)

Use this in a PowerShell here-string piped to python. `integrate=False` keeps explicit generation additive and unapproved. `NOT_ELIGIBLE` Candidates remain selectable when readable.

## 10. Offline Validation

    python -m tb_runner.baseline_cli inspect-candidate .\path\candidate_x.baseline_candidate.json
    python -m tb_runner.baseline_cli validate-candidate .\path\candidate_x.baseline_candidate.json

Repair schema, EnvironmentFingerprint, artifact, terminal-scenario, reconciliation, profiler, or dirty-source findings before treating a Candidate as approval eligible.

## 11. Comparator Execution

Use Compare UI: select Available run / candidate, the locale-matching Approved Baseline, then Compare. API equivalent:

    $body = @{ baseline_id = "baseline_..."; candidate_id = "candidate_..." } | ConvertTo-Json
    Invoke-RestMethod http://127.0.0.1:8000/api/comparator/compare -Method Post -ContentType application/json -Body $body

Use /api/comparator/results/{comparison_id}, /markdown, /report.json, and /report.md for result and downloads. Compatible app upgrades use predecessor selection; a version change alone is not an accessibility regression.

## 12. Verdict Interpretation

| Verdict | Meaning | Approval/action |
|---|---|---|
| PASS | Compatible, complete, no active failure/review | May proceed to explicit human approval |
| PASS_WITH_LIMITATIONS | Raw failures bind to reviewed limitations | Review issue, scope, expiry, then approve explicitly |
| REVIEW_REQUIRED | Structural, environment, ambiguity, eligibility, or availability finding | No automatic approval; disposition, RCA, or clean rerun |
| FAIL | New accessibility failure or critical aggregate regression | Do not approve; preserve evidence and RCA |
| INCOMPARABLE | Input/compatibility contract cannot compare | Repair input or obtain a valid predecessor |

Known limitation keeps raw FAIL. Structural UI changes require review. DATA_UNAVAILABLE never implies PASS. Profiler regression alone is not accessibility FAIL. Dirty working tree and Smoke/Targeted runs are not clean approval evidence.

## 13. Human Approval

After reviewing the report and limitation JSON:

    $candidate = ".\path\candidate_x.baseline_candidate.json"
    $digest = (python -m tb_runner.baseline_cli inspect-candidate $candidate | ConvertFrom-Json).document_digest
    python -m tb_runner.baseline_cli approve $candidate --repository .\baselines --actor "<reviewer-id>" --auth-source "manual-review" --reason "<reviewed decision>" --digest $digest --acceptance "PASS WITH LIMITATIONS" --known-limitations-json .\review\known-limitations.json --accept-limitations

Never suppress unreviewed failures or invoke approval automatically.

## 14. Baseline Repository Verify

    python -m tb_runner.baseline_cli list-baselines --repository .\baselines --active-only
    python -m tb_runner.baseline_cli verify-repository --repository .\baselines

Confirm package, locale, source provenance, checksums, lifecycle tail, and active/superseded state.

## 15. Observation Bundle Generation

After approval, migrate additively with the implemented function:

    from pathlib import Path
    from tb_runner.comparison_input import adapt_approved_baseline
    from tb_runner.observation_bundle import migrate_baseline_observation_bundles
    root = Path('.')
    repo = root / 'baselines' / 'com.samsung.android.oneconnect'
    baselines = [adapt_approved_baseline(p) for p in sorted(repo.glob('baseline_*/baseline.json'))]
    index = migrate_baseline_observation_bundles(baselines, output_root=root/'observation_bundles', qa_runs_root=root/'qa_frontend_runs', artifact_root=root/'.baseline-artifacts')
    print(index['index_digest'])

Verify the index and every document digest. Do not overwrite differing immutable bundle bytes.

## 16. Git Commit and Push

    git status --short
    git diff --check
    git diff --stat
    git add README.md docs baselines observation_bundles config
    git commit -m "Document TalkBack Phase 10 operations"
    git push origin main

Never stage qa_frontend_runs, raw logs, XLSX, screenshots, local CAS, or temporary build output.

## 17. New One Connect Version SOP

1. Confirm APK/version and reviewed policy changes.
2. Confirm clean tree and current origin.
3. English Full Validation → automatic Candidate generation (when qualified) → Offline Validation → predecessor Compare.
4. Review failures, structural changes, limitations, availability, and report.
5. Fix/RCA or obtain Human Approval.
6. Repeat the full sequence for Korean.
7. Approve the new revision, generate the portable bundle, and verify the repository.
8. Inspect previous active lifecycle, then publish reviewed package, bundle, indexes, and docs.

1.8.47.24 → 1.8.48.x can use compatible predecessor selection; exact fingerprint equality is not required when policy permits the upgrade.

## 17a. Current Approved Baseline Reference

| Locale | Baseline | Source commit | Environment |
|---|---|---|---|
| en-US | baseline_8f00aed49e61a07b_r0001 | b3b25a568e9afff4a17427989b1d7d1e127c2eb8 | galaxy-z-flip6, foldable_phone, Android 15, One UI 7, TalkBack 15 |
| ko-KR | baseline_1f697e9b60c655df_r0001 | 10cf94d8ad610dae3ac16967b3446555c4077116 | galaxy-z-flip6, foldable_phone, Android 15, One UI 7, TalkBack 15 |

Both target package com.samsung.android.oneconnect at app version 1.8.47.24. Reviewed issue IDs are
ST-A11Y-LOW-BATTERY-001, ST-A11Y-CLOTHING-DASC-001, and ST-A11Y-HOME-MONITOR-SETTINGS-001.
Both approved references have acceptance PASS_WITH_LIMITATIONS. Raw FAIL rows remain in source
evidence; review binding is the limitation annotation.

## 18. Failure Recovery

Preserve the run and report. Classify device/preflight, collection, artifact/validation, compatibility, Comparator, or app accessibility cause before rerunning. A clean rerun may replace a non-eligible Candidate, never rewrite an Approved Baseline, and never delete regression evidence.

### Known limitations and debt

Operational limitations: Candidate observation bundles are not generated automatically; Human
Approval is required; Compare history is session memory; remote CAS distribution is absent; some
comparisons require local Full Run artifacts; Windows may lock frontend dist output.

Coverage limitations: device/model mapping is manually registered; multi-device Baselines and
OS/TalkBack-major Baselines are sparse; dynamic UI state coverage is incomplete.

Technical debt: temporary-directory ACL issues, legacy Shadow code, further Candidate/Run UX work,
CLI/Frontend feature imbalance, and durable report-history persistence.

Known app accessibility limitations: the three issue IDs above are reviewed per locale/scope.
Raw FAIL is never suppressed. When a signature is absent in a future Candidate, Comparator reports
RESOLVED; it does not rewrite historical evidence.

## 19. Cross-PC Operation

Git includes production code, docs, Approved Baseline core, catalog/lifecycle/index, portable bundles, and device policy. It excludes qa_frontend_runs, raw Evidence JSONL, XLSX, logs, local CAS, screenshots/crops, and session history. A clean clone can replay tracked Baselines but Candidate list may be empty until a local Full Run. Unknown device models require policy review.

## 20. Data Retention and Cleanup

Keep in Git: Baseline core, bundles, catalog/lifecycle/index, closure/RCA docs. Keep locally: approved source Full Runs, unresolved regression evidence, source XLSX/Evidence/crops, and recent N Full Runs. After review, failed temporary Smoke runs, build-test output, stale dist-verify, and duplicates may be deleted. Do not delete active source evidence, unresolved evidence, lifecycle-referenced artifacts, or approved observation source. No automatic cleanup exists.

## 21. Emergency Rollback

Stop new approvals and preserve evidence. Do not rewrite/delete an active Baseline. Inspect lifecycle and use explicit supersede/archive with reviewer identity/reason, or revert code/docs through normal Git review while retaining the immutable audit trail.

## 22. Operational Checklist

- [ ] Clean tree, diff check, and current commit recorded.
- [ ] ADB, model policy, Helper, TalkBack, locale, and preflight verified.
- [ ] Full Validation/all scenarios reached terminal state.
- [ ] Candidate was automatically generated after a qualified Full Validation (or explicitly backfilled with `integrate=False`) and offline-validated.
- [ ] Locale-matching predecessor and report reviewed.
- [ ] Verdict, limitations, failures, structural changes, and availability dispositioned.
- [ ] Human Approval explicitly recorded, if applicable.
- [ ] Repository and bundle verification passed.
- [ ] Only reviewed artifacts/docs staged before commit/push.

## Troubleshooting quick map

- UI Not Found: start backend and check /api/health.
- Empty Candidate list: qa_frontend_runs is local/Git-ignored; perform or restore a local run.
- Multiple Candidates: expected; use source status, batch, and run—not locale/version alone.
- NOT_ELIGIBLE / SMOKE: rerun all scenarios with Full Validation.
- NOT_ELIGIBLE / DIRTY: clean the tree and build a new Candidate.
- Profiler archive missing: enable Profiler and regenerate; never infer performance PASS.
- Incomplete EnvironmentFingerprint: repair Environment Profile/preflight and regenerate.

## Documentation alignment notes

The legacy QA Frontend README still describes the general run APIs; Phase 10 Compare routes and
operations are now linked to this Runbook. The root README and docs index now point to the Phase 10
closure/Runbook. Phase 10.3 design documents remain historical contracts; this Runbook is the
current operator procedure when an older design description and an implemented CLI/UI detail differ.
