# TalkBack Production Traversal Migration (Phase 8.5)

상태: complete; full real-device acceptance completed
기준일: 2026-07-13
기본 동작: `TB_TRAVERSAL_IDENTITY_V2_ENABLED=1` (Production Default)
Compatibility: `TB_TRAVERSAL_IDENTITY_V2_ENABLED=0` (run-scoped Legacy Compatibility)
범위: production progress/visit/consumption/stop/recovery의 evidence gate

## 1. Migration scope

Phase 8.5는 Phase 4~8에서 검증한 physical focus evidence를 production traversal이
제한적으로 소비하는 첫 단계다. SMART_NEXT, Helper success, anchor, representative
selection, coverage 계산식, audit 의미, summary verdict, XLSX schema는 변경하지 않는다.

다음 불변식을 유지한다.

- Step과 Action Transaction은 동일하지 않다.
- Helper ACK는 physical focus commit 증거가 아니다.
- Representative는 actual focus 또는 visit credit이 아니다.
- Consumed는 planning attempt이고 Visited는 stable physical landing이다.
- incomplete, unstable, malformed, orphan 또는 uncorrelated evidence는 `Unknown`이다.

## 2. Production evidence gate

새 gate는 `tb_runner/traversal_evidence_gate.py`에 모여 있다. Runner core는 reducer의
raw schema를 직접 해석하지 않고 `ProgressDecision`과 `VisitDecision`만 소비한다.

공통 필수 조건은 다음과 같다.

1. Production Default traversal flag ON (Legacy Compatibility는 명시적 `0`)
2. reducer version allow-list (`target-relation-v2`)
3. requested transaction ID, reducer transaction ID, runtime transaction ID 일치
4. transaction state `closed`
5. evidence `COMPLETE`, Helper transport `ACKED`
6. orphan/malformed count 0
7. `STABLE_LANDING`, high confidence, physical contradiction 없음

| V2 verdict | 추가 조건 | Production 사용 |
|---|---|---|
| `STATIC_FOCUS` | accepted action 또는 explicit `reached_end`; non-scroll action | physical/semantic progress false, visit false |
| `MOVE_CONFIRMED` | accepted action, physical delta changed, strong compatible target relation | physical/semantic progress true, actual focus visit |
| `INDETERMINATE` | 해당 없음 | legacy fallback |
| `MOVE_TO_OTHER_NODE` | positive corpus 부족 | diagnostic + legacy fallback |
| `SNAP_BACK` | positive corpus 부족 | diagnostic + legacy fallback |

Main transaction 뒤 successful direct realign이 실행된 row는 main V2 result가 최종
focus를 설명하지 못하므로 legacy fallback한다. Scroll progress도 physical static만으로
억제하지 않는다.

## 3. Progress model

`ProgressDecision`은 다음 사실을 분리한다.

- `physical_progress`
- `semantic_progress`
- `representative_only`
- `evidence_complete`
- `gate_applied`
- `legacy_progressed`
- fallback 여부와 이유

Strong `STATIC_FOCUS`는 representative label/resource/bounds가 바뀌어도 기존 repeat
counter를 reset하지 않는다. Strong `MOVE_CONFIRMED`는 stale Helper terminal/failure
projection보다 physical landing을 우선해 progress window를 reset한다. Gate가 적용되지
않으면 기존 `should_stop()` 입력과 결과를 그대로 유지한다. 새로운 sleep, retry 또는
stop threshold는 추가하지 않았고 기존 4-step semantic no-progress policy를 재사용한다.

## 4. Visit / Consumed separation

Flag OFF에서는 기존 state mutation이 그대로 실행된다. Flag ON이고 strong gate가
적용되면 다음 규칙을 사용한다.

- `Visited`: same transaction의 complete, stable, compatible actual-focus landing만 기록
- `Consumed`: planning candidate가 실제로 시도됐을 때 별도 기록
- representative와 actual focus가 다르면 actual logical identity만 Visited에 기록
- representative-only projection은 progress, novelty 또는 visit credit을 만들지 않지만,
  이미 시도된 planning candidate의 representative/cluster/semantic consumption은 유지
- accepted-but-static target은 planning consumption은 가능하지만 Visited는 아님

따라서 `representative selected -> visited`와 `ACK moved -> visited`의 암묵적 결합을
flag-ON 경로에서 제거한다.

## 5. Stop and recovery policy

기존 stop evaluator가 repeat 계열 stop을 제안한 뒤에만 recovery를 검토한다. 대상 stop은
`repeat_no_progress`, `bounded_two_card_loop`, `repeat_semantic_stall`,
`repeat_semantic_stall_after_escape`다.

Recovery 후보는 현재 run의 canonical focusable inventory에서 선택하며 다음을 모두
만족해야 한다.

- 현재 scenario와 current local surface가 정확히 일치
- coverage상 미방문(`MISSED`/`UNKNOWN`)
- clickable/focusable 또는 button role
- valid bounds, enabled false 아님
- toolbar/chrome, `IGNORE`, full-screen ancestor 아님
- canonical physical key 기준 미시도, 미방문, non-hard-failed
- 같은 label이라도 resource/class/bounds가 다르면 별도 instance

모든 XML node를 재투입하지 않는다. 하나의 stop decision 안에서 filtered 후보마다 한
번만 direct-focus를 요청하고, strong recovery가 없으면 normal SMART traversal을 추가로
연장하지 않고 기존 stop으로 돌아간다. Recovery
action 전에 별도 `FOCUS_IN_BOUNDS` evidence transaction이 열리지 않으면 action 자체를
실행하지 않는다. Recovery visit은 그 child transaction이 strong `MOVE_CONFIRMED`일 때만
인정한다. Static, incomplete, indeterminate 또는 transport failure는 visit으로 승격하지
않는다. 후보가 더 없으면 기존 stop을 허용한다.

## 6. Feature flag and rollback

QA Frontend Run 설정은 다음 의존성을 run 단위로 전달한다.

```text
Traversal Identity V2 ON
  -> Identity Shadow V2 ON
  -> Evidence Ledger ON
```

Subprocess 환경변수:

```text
TB_EVIDENCE_LEDGER_ENABLED=1
TB_EVIDENCE_IDENTITY_SHADOW_ENABLED=1
TB_TRAVERSAL_IDENTITY_V2_ENABLED=1
```

기본값은 모두 OFF다. 다음 run에서 옵션을 끄면 `RunSpec`이 상속된 세 환경변수를 모두
제거하므로 ON/OFF/ON 또는 OFF/ON/OFF가 독립적이다. Rollback은 traversal flag를 OFF로
설정하는 것이며 artifact migration이나 config rollback이 필요하지 않다.

Metadata와 Evidence manifest의 `feature_flags`가 실제 run 설정을 기록한다. 과거 run은
metadata가 없으므로 Frontend에서 unavailable로 유지된다.

## 7. Diagnostics

Ledger는 scenario 종료마다 append-only
`TRAVERSAL_IDENTITY_V2_DIAGNOSTICS` event를 기록한다. QA Backend는 scenario event를
run 단위로 합산하고 Frontend의 Experimental card에서 다음 7개 counter만 표시한다.

- `false_progress_suppressed`
- `representative_only_progress_ignored`
- `recovered_candidate_attempts`
- `recovered_visits`
- `premature_stop_prevented`
- `fallback_to_legacy_count`
- `indeterminate_count`

기존 result/quality/shadow card는 덮어쓰지 않는다.

## 8. Frozen Safe/Motion replay

Frozen ledger 원본은 rewrite하지 않는다.

| Corpus | Transactions | Strong move | Strong static | Legacy false progress suppressed | Fallback / indeterminate |
|---|---:|---:|---:|---:|---:|
| Motion | 16 | 11 | 5 | 3 | 0 / 0 |
| Safe | 20 | 11 | 9 | 6 | 0 / 0 |

Frozen ledger에는 Phase 8.5 recovery action, live canonical inventory state, post-recovery row,
stop state mutation이 존재하지 않는다. 따라서 새 stop step, recovery success, expected row
delta와 coverage delta는 replay로 확정하지 않는다. 이를 숫자로 추정해 acceptance로
사용하는 것은 금지한다.

## 9. Safe/Motion limited acceptance

실기기 1차 검증은 `home_safe_plugin`과 `device_motion_sensor_plugin`만 수행한다.

1. QA Frontend에서 Evidence Ledger, Identity Shadow V2, Traversal Identity V2를 켠다.
2. 각 scenario를 독립 run으로 실행한다.
3. ledger/reconciliation/manifest, normal log, XLSX, focusable inventory/coverage/probe를 보존한다.
4. 동일 단말·locale·launch mode에서 Traversal Identity V2만 끈 OFF control을 실행한다.
5. ON/OFF의 row count, unique physical visit, coverage, duplicate, stop reason/step, runtime,
   PASS/WARN/FAIL, anchor/local-tab/probe regression을 비교한다.

Safe는 unique physical visit, direct visit, coverage, stop delay 또는 confirmed recovery 중
하나 이상이 개선되어야 하며 duplicate row 증가만으로 통과하지 않는다. Motion은 기존
row/coverage 감소와 duplicate 증가가 없어야 한다. 공통으로 new FAIL, infinite loop,
anchor/local-tab/probe regression이 없어야 한다.

### 9.1 Final limited-device results

단말 `R3CX40QFDBP`, 동일 locale/warm launch에서 최종 consumption correction 후 결과는
다음과 같다.

| Scenario | Flag | Raw / filtered rows | Coverage | Stop | Runtime |
|---|---|---:|---:|---|---:|
| Motion | OFF | 18 / 13 | 72.7% | `confirmed_local_tab_exhaustion`, step 19 | 239.4s |
| Motion | ON | 18 / 13 | 72.7% | `confirmed_local_tab_exhaustion`, step 19 | 241.2s |
| Safe | OFF | 13 / 11 | 30.8% | `repeat_no_progress`, step 13 | 227.2s |
| Safe | ON | 13 / 11 | 30.8% | `repeat_no_progress`, step 13 | 261.2s |

Motion의 초기 ON draft는 attempted representative의 consumption까지 억제해 같은
representative를 재선택했고 step 12에서 조기 종료했다. 최종 규칙은 visit/progress만
억제하고 planning consumption을 유지한다. 이후 ON은 OFF와 동일한 local-tab exhaustion,
row, coverage를 회복했고 strong false progress 3건은 계속 억제했다.

Phase 8.5B는 malformed legacy `TARGET_ACTION_RESULT` line 대신
request/transaction-correlated bounded Helper `ACTION_API_RESULT`를 수집하도록 보완했고
`json_parse_failed`는 0건이 됐다. 이어 Phase 8.5C는 `FOCUS_IN_BOUNDS`가 BroadcastReceiver
메인 스레드에서 poll을 즉시 종료하던 문제를 확인했다. 같은 primitive를 worker thread에서
실행해 기존 verification window가 실제 focus commit을 관측하도록 수정했다. retry 횟수와
wait 값은 변경하지 않았다.

Phase 8.5C Safe acceptance에서는 recovery 후보 다섯 개 중 네 개가
`moved/content_like_focused_row`, `MOVE_CONFIRMED`, `STRONG_PHYSICAL_LINK`로 확인되어
recovered visit 4건을 만들었다. 마지막 top-area 후보만
`no_content_candidate_in_bounds`로 유지됐다. 결과는 17 raw / 16 filtered rows, 76.9% coverage,
stop step 29였다. runtime은 439.3초로 증가했는데 이는 successful recovery가 기존 traversal을
재개한 결과이며 새 sleep/retry를 추가한 결과가 아니다. Phase 8.6 full-run acceptance는 별도
검증으로 남긴다.

모든 최종 ON ledger reconciliation은 `PASS`였고 새 anchor failure나 infinite loop는 없었다.
Motion regression은 제거됐고 Safe 개선 기준도 충족했다.

## 9.2 Full acceptance

Phase 8.6 full acceptance는 representative scenario를 넘어서 full real-device corpus로
확장해 수행했다. 핵심 결과는 다음과 같다.

| Category | Result |
|---|---|
| Safe | 17 raw / 16 filtered / 76.9% coverage / recovery attempts 5 / recovered visits 4 |
| Motion | OFF 대비 parity 유지 |
| Cross-plugin recovery | recovery attempts 19 / recovered visits 11 |
| Reconciliation / Evidence | PASS / PASS |
| Ledger health | orphan 0 / duplicate 0 / ledger failure 0 |
| Scenario FAIL | 0 |
| Runtime | 약 3시간 |
| Positive `MOVE_TO_OTHER_NODE` | 1건 |

Full acceptance 기준 production regression은 확인되지 않았고 Safe recovery improvement,
Motion parity, cross-plugin recovery success가 모두 입증됐다. 따라서 Phase 8.5 migration
완료 판정은 `YES WITH LIMITATIONS`이다.

## 10. Risks and limitations

- Frozen corpus에는 positive `MOVE_TO_OTHER_NODE`/`SNAP_BACK` production promotion 근거가
  없어 두 verdict는 계속 fallback한다.
- Container hierarchy evidence가 부족한 transaction은 strong relation이 아니면 fallback한다.
- Full acceptance에서 Home Monitor shadow FAIL 1건이 남아 있어 known limitation으로
  유지한다. 이는 production scenario FAIL이 아니라 shadow-side follow-up 대상이다.
- Recovery viewport는 current inventory bounds에서 보수적으로 추정한다. scope/bounds가
  불명확하면 후보를 선택하지 않는다.
- Recovery는 stop 시점에 standard focus/announcement observation을 한 번 더 수행하므로
  해당 stop 경로의 runtime이 증가한다. 임의 sleep/retry는 추가하지 않았다.
- Traversal Identity V2는 Production Default다. Legacy traversal은 run-scoped Compatibility
  Mode로 유지하며, Frontend OFF 또는 API `traversal_identity_v2=false`가 명시적으로 선택한다.

## 11. Verification and Phase 8.6 gate

```powershell
python -m pytest tests/test_traversal_evidence_gate.py tests/test_traversal_evidence_integration.py `
  tests/test_evidence.py tests/test_evidence_identity.py tests/test_collection_flow.py `
  tests/test_diagnostics.py -q --basetemp=.\tmp_pytest_phase85 -p no:cacheprovider

cd qa_frontend/frontend
npm run test:selection
npm run build -- --outDir phase85-dist-verify
```

Phase 8.6 full acceptance는 완료됐다. Safe strong recovery, Motion parity, cross-plugin
recovery, reconciliation PASS가 확인됐고 production traversal regression은 관찰되지 않았다.
현재 판정은 `YES WITH LIMITATIONS`이며 remaining limitation은 Known Limitations 절을 따른다.
