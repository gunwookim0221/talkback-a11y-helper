# Phase 3A — Auto Discovery Integration Foundation

2026-10-05 · branch `feature/phase3-auto-discovery-integration` · baseline `ec36a2e8176b6c352942126657f58ec8cf6d566d`.

## 1. Verdict

**현재: PASS_WITH_LIMITATIONS. READY_FOR_PHASE3B=YES.**

Candidate Churn Evidence Closure 완료 결과는 §21이다. 최초 review의 `READY_FOR_PHASE3B=NO`와 미분류 incident 1건은 아래 역사 기록으로 보존한다. 현재 gate는 Home/Devices/Life 각12회, unexpected churn0, 완전한 before/after evidence 및 regression에 근거하여 갱신했다. 원래 사건의 구체적 원인은 여전히 확정하지 않는다.

State Observation → Phase 2 Registry → 기존 candidate/Audit producer → immutable DiscoverySnapshot → diagnostic JSONL을 연결했다. 현재 화면의 후보를 기술하는 opt-in 경로이며, candidate 선택·실행·visit credit을 수행하지 않는다.

최종 전체 Python **2906 passed / 0 failed / 0 errors / 1 skipped**, Phase 2 + 신규 regression **233 passed**, 신규 tests **56 passed**. 최종 실단말 smoke 18 observations/3 states, 반복 안정성 11 cases, 실제 focus 이동 2회, 기존 경로의 down/up scroll, Global Nav 5/5, persistence/replay가 통과했다.

추가 Audit 연동 smoke 첫 실행에서 반복 hash assertion이 1회 실패했다. 두 번째 raw/snapshot이 assertion 전에 저장되지 않아 원인을 확정할 수 없다. 재실행 3회는 안정적이지만, 이 최초 사건을 정상 availability 변화로 단정하거나 성공 기록에서 삭제하지 않는다. 보수적으로 미분류 churn 1건을 남기며, 이 증거 공백을 닫기 전 Phase 3B readiness를 승인하지 않는다. 후보 계약을 약화하거나 production 코드를 바꾸어 통과시키지 않았다.

증거는 ignored `output/phase3a_auto_discovery_20261005/`에 있다. Phase 3A commit/push/merge는 없다.

## 2. Phase 2 Inputs

기준 문서:

- [Phase 1 gap analysis](phase1-state-auto-discovery-gap-analysis.md)
- [2A fingerprint](phase2a-state-fingerprint-contract.md)
- [2B identity/equality](phase2b-state-identity-equality.md)
- [2C registry/persistence](phase2c-state-registry-persistence.md)
- [Phase 2 closure](phase2-state-model-closure.md)

기존 verdict는 `PHASE2_PASS_WITH_LIMITATIONS`, `READY_FOR_PHASE3=YES`였다. Publication scope audit에서 Phase 2 관련 18개 파일만 stage했고 기존 `out/`, ignored output, IDE/environment/build 파일은 포함하지 않았다. 18 files / 6405 insertions의 단일 commit을 만들고 feature branch push → main checkout/pull ff-only → fast-forward merge → main push → HEAD/origin/main 일치를 확인했다. 이후 최신 main에서 Phase 3 branch를 생성했다.

```ini
PHASE2_COMMIT=ec36a2e8176b6c352942126657f58ec8cf6d566d
PHASE2_BRANCH_PUSH=SUCCESS
PHASE2_MAIN_MERGE=SUCCESS_FAST_FORWARD
MAIN_PUSH=SUCCESS
HEAD_ORIGIN_MAIN_MATCH=YES
PHASE3_BRANCH=feature/phase3-auto-discovery-integration
```

Evidence: `publication_scope.json`, `publication_staged_files.txt`, `publication_staged_stat.txt`, `publication_gate.json`. Phase 3 최종 HEAD/main/origin/main도 같은 SHA다. Phase 3 구현 후 Phase 2 18개 파일의 SHA-256은 post-publication baseline과 모두 일치한다.

## 3. Goals / Non-goals

목표는 “현재 관찰한 logical state에 어떤 action candidates가 존재하는가”를 재현 가능하게 기록하는 것이다. 기존 32 scenarios는 context/provenance로 사용할 수 있다.

이번 변경에는 autonomous click, DFS/BFS, graph, scheduling, safe-navigation policy, scenario 대체, production selection/termination 변경이 없다. Phase 3B transition execution도 구현하지 않았다. Device smoke의 명시적 root 이동·focus 이동·scroll은 기존 경로를 호출하는 고정된 검증 절차였다. DiscoverySnapshot에서 action을 선택하지 않았다.

## 4. Existing Candidate Producers

실제 producer → consumer 관계를 확인했다:

| 단계 | 기존 코드 / 계약 | Phase 3A 연결 |
|---|---|---|
| 관찰 | `talkback_lib.A11yAdbClient.dump_tree`, `scroll_reliability.dump_with_capabilities`, UIAutomator XML | 기존 Phase 2 opt-in collector 재사용 |
| Audit population | `collection_flow._capture_focusable_inventory_snapshot` → `_register_focusable_inventory_node` → `_register_focusable_inventory_item` | registration producer를 별도 sink에서 실행하거나 기존 inventory를 명시적으로 입력 |
| positional population | `completeness.candidate/eligibility`, ContentTerminal의 unlabeled actionable 예외 | 현재 tree의 instance와 eligibility 생성에 재사용 |
| identity / strict focus | `traversal_reliability.instance_id/focus_instance` | state scope로 재기반한 instance-v1, 실제 A11y proof 적용 |
| stale reconciliation | `candidate_lifecycle.CandidateLifecycle`와 scoped output | 현재 state/observation에 해당하는 output만 읽음; lifecycle을 실행하거나 ledger를 수정하지 않음 |
| SMART_NEXT consumer | Python `move_focus_smart` → Helper service → navigator/traversal analyzer → 실제 landing ACK | untargeted FOCUS_NEXT만 기술; Helper의 선택을 대체하지 않음 |
| Global Nav | `global_navigation.discover/current` | 검증된 destination/selected/evidence 유지 |
| scroll | Helper metadata → Python `scroll_reliability.capability` axis-v1 | known axis + 방향별 지원 evidence를 가진 container만 기술 |
| plugin/card | `plugin_card_discovery.discover_device_cards/discover_life_cards_from_nodes` | 현재 위치와 일치할 때 provenance annotation |

Production Audit inventory는 historical population과 label 기반 key를 포함할 수 있고 input focus를 focusability hint에 OR할 수 있다. 이를 새 action availability나 physical visit의 근거로 승격하지 않는다. Discovery는 현재 raw node flag와 Phase 0 positional identity를 권위로 유지한다.

## 5. Reused Assets

새 discovery tree walker나 SMART_NEXT selector를 만들지 않았다. 기존 `flat_nodes`, normalization/eligibility, instance-v1, strict focus, axis-v1, Global Nav, plugin producers와 Phase 2 canonical serialization/equality normalization을 재사용한다.

V7 producer는 `SimpleNamespace` sink에만 registration한다. runtime client, snapshot probe, expected coverage writer, VisitTracker, Helper executor를 호출하지 않는다. 외부 inventory/lifecycle records는 복사하여 읽으며 현재 tree에 없는 historical target을 후보로 추가하지 않는다.

Phase 2 collector의 XML에 `visible-to-user`가 없으면 visibility가 null이다. 기존 V7 producer는 이를 visible로 확정하지 않으므로 자동 registration이 비어 있을 수 있다. visibility를 true로 합성하지 않았다. 실단말 supplemental smoke에서는 실제 Helper dump로 생성한 V7 inventory를 현재 XML observation에 연결하여 이 경로를 별도로 검증했다.

## 6. Discovery Architecture

```text
Saved raw observation / explicit current-screen capture
  → build_state_observation (fingerprint + secondary evidence)
  → diagnostic StateRegistry.observe (CREATED / REUSED / UNRESOLVED)
  → existing current-tree population + fresh Audit provenance
  → strict focus / scoped lifecycle / verified nav / axis-v1 capability
  → DiscoveryActionCandidate[]
  → DiscoverySnapshot (canonical JSON + candidate_set_hash)
  → explicit append-only diagnostic JSONL
```

신규 runtime consumer는 없다.`tb_runner/discovery_candidates.py` と `tools/state_discovery_diagnostic.py` は opt-in diagnostic compositionである。Registry更新も diagnostic instanceに限定される。

## 7. DiscoveryActionCandidate Model

`discovery-action-candidate-v1`:

- deterministic `candidate_id`, nullable `state_id`, `binding_status`, `action_kind`
- `target_identity`: instance_id/resource_id/exact bounds/class、または untargeted operation
- `target_semantics`: Phase 2で正規化した label/value/control state/role/flags
- sorted `source`, bounded `confidence`, diagnostic `safety_hint`
- `eligibility`: observed population eligibility、availability、`auto_activation_allowed=False`
- `evidence`: producer、strict focus、Audit/plugin provenance、scroll supporting signalsなど
- observation/viewport reference、`physical_visit_credited=False`

Frozen dataclass + private canonical JSONを使用し、`to_dict()` は独立した copyを返す。Snapshot candidatesは tuple。候補観察から visit creditは発生しない。

Action inventory:

| Action | 分類 | 現時点の意味 |
|---|---|---|
| FOCUS_NEXT | AVAILABLE_NOW | Helperが次を選ぶ untargeted operation |
| FOCUS_TARGET | AVAILABLE_WITH_ADAPTER | explicit bounds focus transport; landing検証は別契約 |
| CLICK | UNSAFE_FOR_AUTO_ACTIVATION | observed clickable; 効果は未知 |
| ACTIVATE | FUTURE | 共通 activation contract未実装 |
| BOTTOM_NAV | AVAILABLE_WITH_ADAPTER | verified destination; execution/re-entry検証は別 |
| SCROLL_FORWARD/BACKWARD_VERTICAL/HORIZONTAL | AVAILABLE_WITH_ADAPTER | axisと方向別 evidenceが必要 |
| MORE / EXPAND | FUTURE | labelだけでは actionを推測しない |
| BACK | UNSAFE_FOR_AUTO_ACTIVATION | app exit / unsaved state等の効果が未知 |
| PLUGIN_NAVIGATION | AVAILABLE_WITH_ADAPTER | current-view provenance; 独立した safe routeではない |

未実装の actionは inventoryに予約するだけで候補を捏造しない。Selected bottom destinationは `ALREADY_SELECTED`、disabledは `DISABLED`、enabled未知は `UNKNOWN`。

## 8. Candidate Identity

```text
candidate_id = discovery:SHA256(canonical(
  schema_version + logical state scope + action_kind + target_identity))
```

Target instanceは Phase 0 `instance-v1` の resource ID + exact boundsを維持する。Logical stateが解決できない場合は `unresolved:<observation_id>` scopeを使い、既知 stateに帰属させない。FOCUS_NEXTは予測 targetを持たない singletonである。

同じ resource IDでも異なる boundsの instanceは別 candidateとなる。同じ targetでも FOCUS_TARGETとCLICKは別ID。Focus、timestamp、scenario step、source追加だけでは IDやbehavior set hashを変えない。Enabled/selected/checked/control semanticsの変化は hash/deltaに現れる。

動的 temperature/time/batteryと既存 typed location-age等は Phase 2 normalizationを再使用する。Semantic lock/control stateを一律削除しない。同一 positional targetに相反する normalized semanticsがあれば、その targetを除外して `TARGET_IDENTITY_COLLISION` を記録する。Last-write-winsで消さない。

## 9. State Binding

Callerから state_idを注入させない。**当該 raw observation**を構築し、当該 diagnostic Registryで解決する。すべての候補の state_idは Snapshot state_idと一致する。

Ambiguous/unknown activity/popup context、empty observation、coarse collisionは nullable state_id + `UNRESOLVED` provenanceを保持する。Fingerprintしかない入力は secondary evidence不足として、state_id null、候補0で記録する。

既存 scroll continuityは `VerifiedScrollEvidence` の observation linkageとmovement evidenceを検証して使う。異なる viewportを同じstateと決めつけない。CLI raw-list replayには continuity importがないため、APIでproofを与えた smokeと同じscroll resolutionを無条件に保証しない。

## 10. Candidate Sources

実装する sourceは `ACCESSIBILITY_TREE`, `AUDIT_EXPECTED`, `CURRENT_FOCUS`, `SMART_NEXT`, `SCROLL_CAPABILITY`, `GLOBAL_NAV`, `PLUGIN_NAVIGATION`。Sourceはidentityとは独立したdiagnostic metadata。

Audit inputは state/epochのforeign recordと現在存在しないtargetを除外する。Lifecycleのstale/current_presence falseは **同じ state_id + observation_id** の場合のみactionabilityに反映する。Unscoped historical stale flagで現在存在するtargetを退役させない。

Input focusのみ、false-focus fallback、ambiguous/conflicting reconciliation proofから `CURRENT_FOCUS` を付与しない。実際に確認された current A11y focusでも候補としての記録はvisitではない。

## 11. Scroll Integration

`axis_contract=axis-v1` + known VERTICAL/HORIZONTAL/BIDIRECTIONAL + valid container bounds + 非contradictory evidenceが必要。Generic scrollableだけでは候補を生成しない。Pager/unknown axisは除外する。

Known single axisはgeneric forward/backward action 4096/8192または既存support flagsを使用できる。Bidirectionalではup/down/right/leftの方向別supportが必要。Evidenceには `capability_source`, `axis_source`, `requested_direction`, 実際の `supporting_signals` を保存する。

Home実測：既存verified-scroll経路で `SCROLL_MOVED`, action success=true, viewport_changed=true。Logical stateは同一、candidate数56→54、**NEW=30 / REMOVED=32 / CHANGED=0**。Exact positional instancesとsupport方向の変化として保存し、viewport差をstableと誤判定しない。既存up-scrollでtopに戻した後56候補/hashが復元した。

## 12. Global Navigation Integration

Home/Devices/Lifeの全18 snapshotsで Home/Devices/Life/Routines/Menu の5 destinationを観察した。Nav target identityとselected availabilityを保持する。

Discoveryによる tab activationは0。Smokeは指定された3rootsにだけ既存tap経路で移動した。Full global-nav traversalやFull32は実行していない。

## 13. Safety Metadata

READ_ONLY / NAVIGATION / UNKNOWN等は診断上のhint。安全policyやauthorizationではない。特にCLICKのeffect、BACK、plugin routeは safe navigation未承認である。FOCUS_TARGETやscrollのREAD_ONLY hintも、view/tooltips等への効果がないという保証には使えない。

全候補で `auto_activation_allowed=False`、Snapshotで `action_executed=False`, `visit_credit=0`。Production visit ledger、expected population、traversal metrics、selection/terminationは変更しない。

## 14. Diagnostic Artifact

`discovery-snapshot-v1` のJSONLにはtimestamp、scenario/context、state resolution/reasons、fingerprint hash、observation ID/status、viewport signature、candidate count/hash、candidates、sources、strict-current-focus、excluded diagnostics、collision countとsafety contractを記録する。巨大raw XMLは複製しない。

CLI:

```powershell
python -m tools.state_discovery_diagnostic --input saved_raw.json --registry-out output/diagnostic_registry.json --output output/discovery_candidates.jsonl
python -m tools.state_discovery_diagnostic --capture --serial R3CX40QFDBP --scenario-id home --registry-out output/diagnostic_registry.json --output output/discovery_candidates.jsonl
```

必要に応じて `--registry-in`, `--producer-input` または `--fingerprint-input` を明示する。Offline modeでADB clientを作らない。JSONLはcanonical UTF-8 + LF、appendのみ。raw/reference収集と候補artifactは分離し、raw/XMLをcandidate JSONL内に埋めない。

実証artifacts:

- `device_run2/discovery_candidates.jsonl`, `state_registry.json`, `cases.json`, `scroll_evidence.json`
- `device_offline_replay.jsonl`, `artifact_replay_validation.json`
- `phase2a_discovery_replay.jsonl`, `phase2d_discovery_replay.jsonl`
- `live_audit2/discovery_candidates.jsonl`, `producer_0.json`～`producer_2.json`, `summary.json`
- `supplemental_delta_review.json`, 最初の追加smoke失敗log

## 15. Determinism Tests

| 必須契約 | 証拠 |
|---|---|
| 同じstate/observationのID | canonical identity / repeat / process restart tests |
| 入力順不変・duplicate dedup | reversed/shuffled nodes、producer duplicates |
| focus-only不変 | synthetic flags tests + actual SmartNext2回 |
| Home/Devices区別 | distinct states/sets + root tests |
| 同一resource IDの複数instance | multi-bounds test + Devices device_card12 instances |
| 同一targetの異なるaction | FOCUS_TARGET/CLICK identity test |
| axis-aware scroll | vertical/horizontal/bidirectional/generic/unknown/contradictory tests |
| Nav5 stable | tests + 全18 device snapshots |
| dynamic/control state | volatile value不変、semantic state変化可視化 |
| ambiguous state安全 | unknown activity/context/popup/empty/collision tests |
| strict A11y focus | input-only/false flags/conflicting proof exclusion |
| ledger不変 | VisitTracker invocation禁止 + raw ledger deep-copy equality |
| scoped stale | same state/epochのみ適用、foreign/history除外 |
| producer再利用 | V7 registration spy、plugin ID変更でinstance population不変 |
| serialization | immutable export、JSONL exact bytes、subprocess restart |

結果:

| Suite | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| 新規 Phase 3A | 56 | 0 | 0 | 0 |
| Phase 2 + Phase 3A | 233 | 0 | 0 | 0 |
| Full Python | 2906 | 0 | 0 | 1 |

Skipは既存 `test_save_excel_xlsxwriter_thumbnail_insert_does_not_raise_file_not_found`。環境にxlsxwriterがないためで、新規skip/excludeはない。

```powershell
python -m pytest tests -q -p no:cacheprovider --basetemp ../pytest_full_final --junitxml ../full_regression_final.xml
python -m pytest tests/test_state_fingerprint.py tests/test_state_fingerprint_diagnostic.py tests/test_state_equality.py tests/test_state_registry.py tests/test_state_replay.py tests/test_discovery_candidates.py tests/test_state_discovery_diagnostic.py -q -p no:cacheprovider --basetemp output/phase3a_auto_discovery_20261005/pytest_phase2_final --junitxml output/phase3a_auto_discovery_20261005/phase2_and_discovery_final.xml
```

Full suiteは既存unrelated `out/` をテストの相対path書き込みから保護するため、ignored directory内の **673 byte-identical source files** のsnapshotで実行した。実行cwdは `output/phase3a_auto_discovery_20261005/regression_source2`。全test sourceを含む。アクセス制限のある既存 `.test_tmp*` 等generated dataを複製対象から外したが、testを除外していない。

初回の隔離full suiteは既存ignored baseline/run inputs不足で9 failed / 2885 passed / 5 skipped。入力補充中の限定再実行は6 failed / 77 passed、その次は1 failed / 82 passedだった。原因は既存candidate JSON、XLSX、environment profiles、frozen ledger、V10 input dataの欠落。原本から必要な実データをcopyし、テストやassertionを変更せず最終full suiteで0 failed / 0 errorsを確認した。コピーしたinputのhash/sizeは `regression_source_manifest.json`、最終Junit/logは `full_regression_final.*`。最終source hashも作業treeと一致する。

Offline artifact replay:

- 今回device18件：3states、unresolved0、snapshot **18/18 byte identical**、save/load一致。
- Phase2A raw17件：reviewed expected groups一致、3states、unresolved0、collision/binding mismatch0。
- Phase2D raw28件：3states、unknown context1件unresolvedのまま、unsafe bind0、reviewed groups一致。
- Fingerprint-only17件：全17 unresolved、definitive candidates0、states0。

## 16. Device Smoke

Device `SM-F741N / R3CX40QFDBP`。Helper READY。APK更新・installなし。最終runは `device_run2/summary.json`。

| Root | Logical state | Repeat observations | 候補数 | 主なaction内訳 |
|---|---|---:|---:|---|
| Home | `phase3-device:state:00000001` | 3以上 | 56 | FOCUS_TARGET29 / CLICK19 / NAV5 / vertical forward1 / horizontal forward1 / NEXT1 |
| Devices | `phase3-device:state:00000002` | 3 | 80 | FOCUS_TARGET42 / CLICK30 / NAV5 / vertical backward1 / horizontal forward1 / NEXT1 |
| Life | `phase3-device:state:00000003` | 3 | 73 | FOCUS_TARGET39 / CLICK27 / NAV5 / vertical backward1 / NEXT1 |

18 captures/snapshots、3 logical states、11 stable comparisons。Focus移動2回はHelper ACK moved + actual A11y focused flagを確認し、logical equality SAMEとcandidate set stableを維持した。Scroll/restoreは§11のとおり。Home re-entry後hashも復元。Discovery-selected actions0、visit credit0。

同一resource IDの分離実例:

- Home `shortcutCard`: 2 positional instances。
- Devices `device_card`: 12、`device_icon`: 7、`subheader_card`: 2、`expand`: 2。
- Life `marker_focus`: 3。

これらはaction数ではなく異なるtarget instanceの数。FOCUS_TARGETとCLICKの双方があれば、それぞれ別candidate IDを持つ。

Supplemental Audit validation：Helper nodes → unchanged V7 producerで42 inventory recordsを作成し、現在treeに対応する35 candidatesに `AUDIT_EXPECTED` を付与。3観察とも同じlogical state、56候補、同じbehavior hash。Provenance追加によるdelta0、実行0、visit0。

ただし先行したsupplemental実行には未分類のrepeat hash assertion失敗1件がある。失敗のsecond raw/snapshotが未保存だったため、新しい3回の成功で当該事象を説明済みにしない。保存されたfirst rawと再実行first rawの比較はSAME / 56→56 / new0 removed0 changed0だった。原事件のsecond observationを代用する証拠にはならない。

## 17. Performance

Local diagnostic measurement。各root10 iterationsのmedian（ms）。Fingerprint段階はsecondary sidecarを含む。Candidate段階はV7 registration + candidate construction + initial canonical snapshot serializationを含む。Export costは再canonicalizationとして別測定し、二重にlatency合計へ足さない。

| Root | Raw nodes / candidates | Fingerprint+sidecar | Registry warm reuse | Candidate phase | Snapshot export | UTF-8 bytes |
|---|---|---:|---:|---:|---:|---:|
| Home | 128 / 56 | 87.78 | 58.04 | 90.35 | 6.54 | 105058 |
| Devices | 179 / 80 | 129.49 | 88.72 | 111.98 | 5.92 | 152764 |
| Life | 178 / 73 | 123.43 | 82.41 | 124.83 | 6.87 | 146954 |

Read-only device acquisition3回はmedian **4103.44 ms**、range **4072.33–4124.26 ms**。既存collectorのHelper/XML/window/focus逐次readを含む。

既存large artifact Registry：**5676877 bytes / 46 events / 3 states**、load **6474.61 ms**。既存Home stateへのcandidate binding PASS。Warm full diagnostic pipeline5回median **272.25 ms**（257.01–286.76 ms）。最初のreuse後event47。

これはhot production pathの性能承認ではない。Candidate integrationのoffline追加費用は測定規模では約90–125 msだが、Registry load、events retention、partial capture、artifact growthは引き続きbudgetが必要。最適化やruntimeへの組込みは今回行っていない。Evidence: `performance.json`, `live_audit2/summary.json`。

## 18. Known Limitations

1. **Supplemental repeat hash差1件が未分類。** 原事件second observationが保存されず、正当なavailability変化・非atomic capture・candidate churnを区別できない。再現待ちでもfailure logを保全する。Readinessは保留する。
2. Helper/XML/focus/windowは逐次収集でatomic snapshotではない。遅延中のUI変化を排除できない。今後の比較harnessはassertion前に両raw/snapshot/deltaを保存する必要がある。
3. XML visibility/overlay absence等はpartial。Unknown activity/popup/coarse contextはunresolved。既知stateへの強制bindやaction実行はしない。
4. Fingerprint-only入力はsecondary/target evidence不足。候補0、state_id null。CLIにはscroll continuity manifest importがない。
5. Instance-v1のexact geometryはPhase 0契約を維持する。Layout jitterや別位置への再配置はID deltaになり得る。Viewportをまたぐdurable target identityを新規に保証しない。
6. Audit hintsはPhase 0 strict focusより広く、古いinventoryはhistorical。Fresh tree一致とstate/epoch scopeで制限する。XML visibility未知のautomatic V7 outputは空になり得る。
7. Safety hintsはauthorization/classifierではない。Desired-target SMART_NEXT、MORE/EXPAND、generic activation、plugin safe routeは未実装。
8. 大規模Registryのload約6.47秒、JSONL約105–153KB/snapshot。Retention/index/load budgetと広いdevice/locale corpusは未承認。
9. 実単末は1device、3roots、限定focus/scroll。Full32や全plugin routeのacceptanceを主張しない。xlsxwriterの既存skip1は残る。

## 19. Phase 3B Preconditions — Initial Review

| 条件 | 判定 |
|---|---|
| Deterministic candidate identity / input order / canonical serialization | PASS |
| State binding / ambiguous-safe behavior / no unsafe state binding | PASS |
| 最終bounded repeated/focus-only/device snapshots stable | PASS |
| Phase 2 regressions clean | PASS |
| Production runtime/config/Helper unchanged | PASS |
| Supplemental未分類churnのevidence closure | **PENDING** |

**READY_FOR_PHASE3B=NO**。次の最小作業はdiagnostic evidence closureであり、比較前にraw/capability/snapshotをすべて保存して、supplemental failureの原因を分類する。Availabilityが実際に変わったなら既存deltaで説明する。同じlogical actionなのにvolatile fieldで変わるならPhase3Aの最小修正とregressionを行う。

そのclosure後にすすめるPhase3Bは **Transition Observation Contract**：State A + 明示された既存controlled action → State B observation / resulting evidence。Autonomous action selectionを入れず、Phase 2 ambiguous behaviorとstrict visit契約を保護する。今回Phase3Bは実装していない。

## 20. Initial Review Verdict — Historical Gate

```ini
PHASE2_COMMIT=ec36a2e8176b6c352942126657f58ec8cf6d566d
PHASE2_BRANCH_PUSH=SUCCESS
PHASE2_MAIN_MERGE=SUCCESS_FAST_FORWARD
MAIN_PUSH=SUCCESS
HEAD_ORIGIN_MAIN_MATCH=YES

PHASE3_BRANCH=feature/phase3-auto-discovery-integration
PHASE3A_VERDICT=PASS_WITH_LIMITATIONS
PYTHON_TEST_RESULT=2906_PASSED_0_FAILED_0_ERRORS_1_SKIPPED
STATE_BINDING_MISMATCH_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
UNSAFE_STATE_BIND_COUNT=0
CANDIDATE_SET_UNEXPECTED_CHURN_COUNT=1
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
READY_FOR_PHASE3B=NO
```

Churn countは未分類supplemental assertion1件を保守的に含む。Completed primary smokeのunexpected churnは0であり、対象の違いを隠して全観察0と報告しない。Collision count0はreal-device/replayでの観測値。Collision negative testで意図的に作った1件は正しく検出・除外され、実測件数に混ぜない。

Production config SHA-256:

```text
6dd5d8a191d21e4366ed2513627d97b37515a1e2ae9c2ed342b8d2317fecb964
```

Changed files（Phase 3Aのみ、すべてuntracked）:

| File | 目的 |
|---|---|
| `tb_runner/discovery_candidates.py` | producer integration、immutable candidates/snapshot、state binding、delta、JSONL |
| `tools/state_discovery_diagnostic.py` | opt-in offline/capture CLI、diagnostic persistence |
| `tests/test_discovery_candidates.py` | 51 candidate/identity/source/safety/determinism cases |
| `tests/test_state_discovery_diagnostic.py` | 5 CLI/process/offline/capture contract cases |
| `docs/design/phase3a-auto-discovery-integration.md` | 本設計・検証・publication/readiness報告 |

Git state:

```text
$ git branch --show-current
feature/phase3-auto-discovery-integration

$ git status --short
?? docs/design/phase3a-auto-discovery-integration.md
?? out/
?? tb_runner/discovery_candidates.py
?? tests/test_discovery_candidates.py
?? tests/test_state_discovery_diagnostic.py
?? tools/state_discovery_diagnostic.py

$ git diff --stat
(empty)

$ git diff --name-only
(empty)
```

`git diff` はuntracked新規ファイルを含まないためempty。Stage済み変更も0。`git ls-files --others --exclude-standard` の完全なraw output（既存out/615件を含む）は `output/phase3a_auto_discovery_20261005/final_git_state.txt` に保存した。新規tracked-source候補は上記5ファイルである。

Scope audit: 元の `out/` **615/615 files、SHA-256一致、追加/削除なし**。Phase2 files18/18 unchanged。全tracked production/runtime/Helper/scenario/config/frontendのdiffは0。Phase3 source4filesを含む隔離regression sources673件はcurrent worktreeとbyte-identical。最終gate/source/artifact referencesは `final_scope_audit.json`, `phase3a_gate.json` に記録する。

Phase 2は公開済み。Phase 3Aはこのbranchのworktreeに保持し、commit/push/mergeしない。

## 21. Candidate Churn Evidence Closure — Current Gate

2026-10-05 · 같은 branch/worktree에서 수행. 증거 directory: `output/phase3a_churn_closure_20261005/`.

### 21.1 Original churn incident

기존 `output/phase3a_auto_discovery_20261005/live_audit_observation.log`의 supplemental repeat hash assertion 실패1건을 보존한다. 직전 관찰은 Home56 candidates였으며, assertion 이전에 second raw/snapshot을 저장하지 않아 정확한 diff가 없다. 이후3회 성공으로 원래 사건이 없었다고 취급하지 않았다. 최초 gate의 unexpected count1, readiness NO는 §20에 보존했다.

현재 분류는 **NON_REPRODUCED_TRANSIENT**. 이는 요청의 non-reproduced closure 규칙에 따른 evidence 분류이며, TIMING_RACE나 특정 producer 결함이 실제 원인이었다는 진단이 아니다.

### 21.2 Evidence limitation

원래 사건의 second observation은 복구되지 않았다. 당시 UI availability, viewport, capability, state binding, ordering 중 무엇이 달랐는지 확정할 수 없다. `ROOT_CAUSE=UNKNOWN_ORIGINAL_SECOND_OBSERVATION_MISSING`를 유지한다.

이번 gate는 새 evidence window의 결과에 근거한다. 역사적 incident count는1로 유지하며, 이번 window에서 발생하지 않은 사건을 실측 unexpected count에 합치지 않는다. 카운터 무시, hash bypass, assertion 완화로 closure하지 않았다.

### 21.3 New capture contract

새 opt-in 도구 `tools/state_discovery_churn_diagnostic.py`는 action executor 없이 다음 순서를 강제한다:

1. raw observation + 실제 Helper producer input + Phase2 StateObservation + 전체 DiscoverySnapshot + candidate ID 목록을 observation bundle에 저장.
2. 임시 파일 write/flush/fsync → atomic replace 후 checksum과 record index 저장.
3. before/after 양쪽 파일을 다시 읽고 checksum 검증.
4. `candidate_churn_diff-NNNN.json`에 두 파일 reference/checksum, equality, state/fingerprint/viewport/hash, semantic delta, source별 delta 저장.
5. 그 뒤 assertion/classification을 실행.

모든44 관찰과80 비교에서 이를 수행했다. Hash가 달라진5 비교도 양쪽 증거가 완전하다. Hash 차이는 기본 `UNKNOWN/expected=null`이며, 저장된 증거로 설명하기 전 정상 변화로 자동 분류하지 않는다. Source별 ADDED/REMOVED/CHANGED와 PROVENANCE_CHANGED를 분리한다.

Comparison/ assertion 실패를 주입한 test에서도 두 observation bundle이 남았다. 손상된 파일은 checksum mismatch로 거부했고, 기존 run directory를 overwrite하지 않는다. Production runtime이나 기존 collector/discovery engine은 수정하지 않았다.

### 21.4 Reproduction method

SM-F741N / R3CX40QFDBP, USB charging battery62%, Helper READY. 실단말 capture window는 **2026-10-05 08:45:27–08:50:05 KST**.

원래 supplemental source 경로인 **fresh Helper dump → V7 inventory producer → 기존 Phase2 Helper/XML/focus/window collector → StateRegistry → DiscoverySnapshot**을 그대로 사용했다. Producer input도 매회 저장했다.

Home12 passive → Home focus2 → 기존 controlled down/up scroll → Devices12 passive → Life12 passive → Home 복원 순서. Passive block 내부에는 intentional focus, scroll, tab switch, candidate activation이 없었다. Root 이동과 scroll은 미리 정한 기존 검증 경로이며 discovery가 선택하지 않았다. Full32는 실행하지 않았다.

Harness: `device_closure.py`; 원본 log: `device_closure.log`; 결과: `device_final1/summary.json`, `samples.json`, `comparison_index.json`.

### 21.5 Passive observation results

| Root | Passive observations | Candidates | AUDIT_EXPECTED 후보 | State/hash/viewport |
|---|---:|---:|---:|---|
| Home | 12 | 56 | 35 | 각1개, 전 관찰 동일 |
| Devices | 12 | 80 | 65 | 각1개, 전 관찰 동일 |
| Life | 12 | 73 | 33 | 각1개, 전 관찰 동일 |

3개의 logical state를 유지했다. 각root의 연속 비교와 최초 baseline 비교 모두 candidate hash가 같았다. Actual raw population key delta0, exact bounds changed nodes0. 기존 오류는 충분한 반복에서 재현되지 않았다.

### 21.6 Focus churn results

Home에서 실제 SMART_NEXT2회, ACK `moved`와 actual A11y focused flag를 확인했다. 두 번 모두 logical state·viewport·candidate hash가 유지됐다.

각 focus baseline 비교의 CURRENT_FOCUS source에는 target의 FOCUS_TARGET/CLICK2개 provenance가 추가됐다. Source membership은 진단 정보이며 behavior hash를 바꾸지 않았다. Physical visit credit은0, discovery-selected actions는0.

### 21.7 Scroll results

| Transition | Classification | Logical state | Viewport | Added / Removed / Changed |
|---|---|---|---|---|
| Home controlled down | VIEWPORT_CHANGE | 동일 | 다름 | 30 / 32 / 0 |
| Home controlled up restore | VIEWPORT_CHANGE | 동일 | 다름 | 32 / 30 / 0 |

`VerifiedScrollEvidence`에 movement/action/container/observation linkage를 저장하고 equality logical_state_equal=true를 확인했다. 복원 후 Home56/hash는 baseline과 같았다. 두 변화는 **EXPECTED_CANDIDATE_CHURN_COUNT=2**에 포함한다.

Exact artifacts:

- `device_final1/evidence/candidate_churn_diff-0029.json`: observation0016 →0017, down.
- `device_final1/evidence/candidate_churn_diff-0031.json`: observation0018 →0019, restore.
- `device_final1/scroll_proofs.json`, `summary.json`의 기존 scroll transition.

Home→Devices, Devices→Life, Life→Home의3 root-entry hash 변화도 모두 저장했다. 이는 실제 다른 logical state/root entry이므로 same-state churn metric에서 제외한다. 이3건까지 합쳐 hash-change artifacts는5건이다.

### 21.8 Source-by-source diff

Same-state scroll delta를 producer별로 분해한 결과. Source는 중첩하므로 행별 합은 전체 candidate count와 같을 필요가 없다.

| Source | Down Added / Removed / Changed | Restore Added / Removed / Changed |
|---|---|---|
| ACCESSIBILITY_TREE | 28 / 30 / 0 | 30 / 28 / 0 |
| AUDIT_EXPECTED | 17 / 19 / 0 | 19 / 17 / 0 |
| SCROLL_CAPABILITY | 2 / 2 / 0 | 2 / 2 / 0 |
| CURRENT_FOCUS | 0 / 0 / 0 | 0 / 0 / 0 |
| GLOBAL_NAV | 0 / 0 / 0 | 0 / 0 / 0 |
| SMART_NEXT | 0 / 0 / 0 | 0 / 0 / 0 |
| PLUGIN_NAVIGATION | 0 / 0 / 0 | 0 / 0 / 0 |

현재target 위치와 capability/container 변화가 나타났으며 stale candidate를 historical inventory에서 복구해 candidate 수를 맞추지 않았다. Passive source deltas는 모두 안정적이었다. Global Nav5 destinations와 state별 candidate IDs는 각root12회 모두 같았다. 다른root는 다른logical state이므로 state-scoped candidate IDs도 다르다. Selected availability 변화는 저장된 root context로 설명된다.

Source별 전체 raw delta, provenance change와 root-entry3건은 `evidence_audit.json` 및80 pair artifacts에 보존한다.

### 21.9 Root cause

새 window에서는 ORDERING_NONDETERMINISM, VOLATILE_FIELD_LEAK, STATE_BINDING_DRIFT, SOURCE_PRODUCER_RACE, STALE_CANDIDATE_CHANGE, SERIALIZATION_NONDETERMINISM 또는 DUPLICATE_DEDUP_INSTABILITY를 나타내는 unexplained hash 변화가 없었다. 실단말44건의 raw/producer 순서를 뒤집은 replay도 candidate rows와 hash가 같았다.

원래 사건의 root cause는 **UNKNOWN**. 수집 당시 second observation 누락이 RCA의 직접적인 evidence blocker였음은 확정할 수 있다. 충분한 반복 및 완전한 capture, current unexpected0 조건으로 **NON_REPRODUCED_TRANSIENT** closure를 적용한다.

Bounds jitter 검토: synthetic1/2/3px 이동은 Phase0 exact positional instance ID와 discovery hash에 delta를 만든다. 실제 반복에는 jitter0이었다. 현재 target의 confidence가 POSITIONAL_ONLY이므로 다른위치의 같은resource ID를 같은object로 합치는 수정은 안전하지 않다. Exact instance identity와 durable semantic identity 분리는 더 강한 correspondence evidence가 필요한 후속설계이며, 이번에는 bounds를 제거하거나 bucket으로 object distinction을 약화하지 않았다.

### 21.10 Fix

**FIX_APPLIED=NO**: 재현된 discovery engine defect가 없어 engine 계약을 수정하지 않았다. Scenario/Home patch, count hardcoding, hash bypass, tolerance 완화는 없다.

추가 파일:

| File | 목적 |
|---|---|
| `tools/state_discovery_churn_diagnostic.py` | 비교 전 durable evidence, semantic/source diff, reviewed classification, offline CLI |
| `tests/test_discovery_churn_closure.py` | 공통계약 + bounds jitter + failure-safe evidence의21 cases |

기존 Phase3A engine/CLI/56 test cases는 원본hash와 일치한다. 보고서만 현재gate 및 closure section으로 갱신했다. 새 capture 도구는 instrumentation이며 engine fix로 집계하지 않는다.

### 21.11 Regression

| Suite | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| Closure contract cases | 21 | 0 | 0 | 0 |
| Phase2 + Phase3A + Closure | 254 | 0 | 0 | 0 |
| Full Python | 2927 | 0 | 0 | 1 |

기존skip1은xlsxwriter 미설치 조건이다. 새로운exclude/skip은 없다. 전체suite는 원본out/을 보호하는 이전 격리snapshot을 사용했고, 추가2 source를 포함해 **675 source files byte-identical**, test source 제외0을 확인했다. Source 및local regression data manifest는 새evidence directory의 `regression_source_manifest.json`에 기록했다.

```powershell
# cwd: output/phase3a_auto_discovery_20261005/regression_source2
python -m pytest tests -q -p no:cacheprovider --basetemp ../../phase3a_churn_closure_20261005/pytest_full --junitxml ../../phase3a_churn_closure_20261005/full_regression.xml

# cwd: repository root
python -m pytest tests/test_state_fingerprint.py tests/test_state_fingerprint_diagnostic.py tests/test_state_equality.py tests/test_state_registry.py tests/test_state_replay.py tests/test_discovery_candidates.py tests/test_state_discovery_diagnostic.py tests/test_discovery_churn_closure.py -q -p no:cacheprovider --basetemp output/phase3a_churn_closure_20261005/pytest_related --junitxml output/phase3a_churn_closure_20261005/related_regression.xml
```

새test 최초실행3 failures는 fixture 기대 오류였다. Raw tree를 통째로2배로 늘리면 Phase2의observation multiplicity가 달라져 AMBIGUOUS가 되어 same-state ordering case가 아니며, enabled 의미변화는 Phase2에서DIFFERENT/new-state로 분류되어 동일ID CHANGED가 아니라 ADDED/REMOVED로 나타난다. Ordering과duplicate producer case를 분리하고, availability test는 equality DIFFERENT와동일target의 AVAILABLE→DISABLED를 명시적으로 검증했다. Test삭제나engine변경으로 숨기지 않았고 최종21 cases 전부통과했다.

추가 offline audit:

- 모든44 bundles checksum/reference/state binding 검증 PASS.
- **44/44 snapshot replay byte-identical**.
- **44/44 실제raw/producer reverse-order candidate rows/hash 동일**.
- **44/44 snapshot repeated serialization/key-order byte-identical**.
- Registry persistence byte-identical, state count3.
- 모든5 hash-change pair의 raw before/after와 complete candidate/equality diff 존재.

### 21.12 Device stability metrics

```ini
TOTAL_SAME_STATE_OBSERVATIONS=43
PASSIVE_OBSERVATIONS=36
TOTAL_CAPTURED_OBSERVATIONS=44
EXPECTED_CANDIDATE_CHURN_COUNT=2
UNEXPECTED_CANDIDATE_CHURN_COUNT=0
STATE_BINDING_MISMATCH_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
UNSAFE_STATE_BIND_COUNT=0
GLOBAL_NAV_CANDIDATES=5
EVIDENCE_COMPLETE=YES
```

Metric 정의: same-state observation43 = passive36(각root의baseline포함) + focus2 + controlled scroll/restore before/after4 + Home re-entry1. 별도entry/preflight 관찰1은 total capture44에만 포함한다. Expected churn2는 같은logical state의down/restore이며, 다른logical state의root entry3건은 별도 기록한다. Baseline/연속중복비교80개를event count로 이중집계하지 않는다.

### 21.13 Remaining limitations

- 기존 사건의 실제 root cause는 second observation 부재로 확정하지 못한다. 사건1건과원래failure log를보존하며, non-reproduced closure가 원인증명을대체하지는 않는다.
- 1device/3roots/한capture window의bounded evidence다. Sequential Helper/XML capture는atomic하지않으며 미래churn은같은완전한capture계약으로다시분류해야한다.
- Phase0 exact geometry의1–3px delta 가능성, partial XML visibility/unknown overlay, largeRegistry load/retention, Safe Navigation미구현등 §18의다른제한은유지한다.
- Plugin source는이번live roots에서실제matching provenance가없을수있다. Producer변경/중복/순서안정성은기존및추가tests로검증했다. Full32/다른device·locale acceptance로확대해주장하지않는다.

### 21.14 Phase 3B readiness and final Git state

요청§22의non-reproduced 기준을 충족했다: complete new evidence capture, 충분한passive반복, current unexpected0, replay/determinism0failure, state binding안정. 요청§21의나머지gate도통과했다.

```ini
PHASE3A_CLOSURE_VERDICT=PASS_WITH_LIMITATIONS
ORIGINAL_CHURN_CLASSIFICATION=NON_REPRODUCED_TRANSIENT
ROOT_CAUSE=UNKNOWN_ORIGINAL_SECOND_OBSERVATION_MISSING
FIX_APPLIED=NO
TOTAL_SAME_STATE_OBSERVATIONS=43
EXPECTED_CANDIDATE_CHURN_COUNT=2
UNEXPECTED_CANDIDATE_CHURN_COUNT=0
STATE_BINDING_MISMATCH_COUNT=0
CANDIDATE_ID_COLLISION_COUNT=0
UNSAFE_STATE_BIND_COUNT=0
PYTHON_TEST_RESULT=2927_PASSED_0_FAILED_0_ERRORS_1_SKIPPED
PHASE2_PHASE3A_REGRESSION_RESULT=254_PASSED_0_FAILED_0_ERRORS_0_SKIPPED
PRODUCTION_RUNTIME_CHANGED=NO
PRODUCTION_CONFIG_CHANGED=NO
HELPER_CHANGED=NO
READY_FOR_PHASE3B=YES
```

Commit/push/mergeなし。Phase3Bは実装していない。現在branchとHEADは変更していない。

```text
$ git branch --show-current
feature/phase3-auto-discovery-integration

$ git status --short
?? docs/design/phase3a-auto-discovery-integration.md
?? out/
?? tb_runner/discovery_candidates.py
?? tests/test_discovery_candidates.py
?? tests/test_discovery_churn_closure.py
?? tests/test_state_discovery_diagnostic.py
?? tools/state_discovery_churn_diagnostic.py
?? tools/state_discovery_diagnostic.py

$ git diff --stat
(empty)

$ git diff --name-only
(empty)
```

Untracked 파일이므로 git diff는 비어 있다.Staged0、tracked production差分0。`git ls-files --others --exclude-standard`は関連7新規ファイルと既存out/615ファイル。전체 raw 출력은 `output/phase3a_churn_closure_20261005/final_git_state.txt`、scope hash auditは `scope_audit.json`、현재 gate는 `closure_gate.json` 에 저장한다.

既存out/615/615 files의 hash와 파일 집합을 보존했고,initial Phase3Aのengine/CLI/既存tests4files를 보존했다.Production config hashは§20와 같다.기존 Phase2 publication, 과거 incident artifacts, 사용자 unrelated 변경은 그대로 보존했다.
