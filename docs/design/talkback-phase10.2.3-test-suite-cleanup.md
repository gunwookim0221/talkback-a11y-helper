# Phase 10.2.3 Test Suite Cleanup

## 1. Failure Inventory

Initial `python -m pytest tests -q` result was 16 failed, 1,927 passed, 1 skipped, and 36 setup errors.

| Area | Count | Classification | Cause |
| --- | ---: | --- | --- |
| `test_capture_ui_state.py` | 2 | Stale assertion | The tests patched the removed direct ADB screenshot path instead of the current `capture_full_screenshot` client wrapper. |
| `test_script_overlay.py` | 11 | Stale assertion / schema evolution | Tests expected the former five-value stop API, former repeat-stop semantics, former anchor vocabulary, and obsolete bounds handling. |
| `test_qa_frontend_runtime_dashboard.py` | 1 | Additive field | The parser now emits scenario-scoped `traversal_result` and `stop_reason`; the test expected an incomplete exact object. |
| `test_evidence.py` | 1 | Actual code defect | An explicit empty environment mapping was discarded because `env or os.environ` selected ambient process flags. |
| `test_evidence_identity.py` | 1 | Environment-dependent test | The default-state test removed only one of two supported enablement flags. |
| `test_audit_device_plugins.py` | 1 | Flaky test | Consecutive writes can receive equal `mtime` values on Windows. |
| `test_runtime_report_parser.py` | 36 errors | Environment-dependent | The fixture cannot create its unique directory beneath repository `.test_tmp` because of ACL denial. |

Running `python -m pytest -q` from the repository root additionally cannot complete collection because the pre-existing `tmp_pytest_phase951_regression` directory is inaccessible. This is separate from the `tests` suite result.

## 2. Root Cause Classification

No traversal, anchor, candidate, repository, coverage, identity, or recovery behavior was changed. The only production correction is the explicit-environment selection in `evidence_enabled`: `{}` now means an intentionally empty environment, while `None` retains the documented process-environment fallback.

The parser errors are not parser failures: every case fails before its test body executes at `Path.mkdir()` in the local `.test_tmp` fixture directory.

## 3. Updated Assertions

- Screenshot coverage now asserts delegation to `A11yAdbClient._take_snapshot`, including exception propagation.
- Stop assertions use the six-value canonical result and require failed movement plus no-progress evidence before expecting `repeat_no_progress`.
- Overlay realignment and Korean/English anchor assertions match the current configuration contract without introducing generic tokens.
- Runtime Dashboard expects the additive `traversal_result` and `stop_reason` fields in the scenario progress record.
- Identity default-state coverage clears both supported process flags.
- Latest-log selection uses explicit, distinct file modification times rather than filesystem timing.
- The isolated overlay test stub supplies the `pandas.Series` type used by the imported production annotations, removing import-order dependence.

## 4. Remaining Known Limitations

- The local `.test_tmp` ACL prevents all 36 Runtime Report Parser tests from creating test fixtures. Repair the ACL or run in a workspace where the current user can create children beneath `.test_tmp` before treating the full suite as green.
- Root discovery is blocked by the inaccessible `tmp_pytest_phase951_regression` directory. Use `python -m pytest tests -q` until that external directory is removed or its ACL is repaired.

## 5. Regression Result

Targeted regression checks passed:

- `tests/test_capture_ui_state.py`, `tests/test_qa_frontend_runtime_dashboard.py`, `tests/test_collection_flow.py`, and `tests/test_script_overlay.py`: 535 passed.
- `tests/test_script_overlay.py` in isolation: 40 passed.
- `tests/test_evidence.py` and `tests/test_evidence_identity.py`: 69 passed.
- `tests/test_audit_device_plugins.py`: 35 passed.

Final `python -m pytest tests -q --tb=short` result: **1,943 passed, 1 skipped, 36 errors**. Every error is the documented `.test_tmp` ACL setup failure; there are no remaining assertion failures.

## 6. Test Health Summary

The assertion failures identified in the initial run have been resolved without relaxing assertions or deleting tests. With the ACL-blocked parser file excluded, the complete remaining suite is **1,938 passed, 1 skipped**. Test health is blocked only by the 36 `.test_tmp` setup errors in this environment and by the separate root collection ACL issue. Functional regressions in the covered Phase 10.2.2C paths are not indicated.
