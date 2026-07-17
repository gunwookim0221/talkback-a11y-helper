# Phase 10 First Baseline `EMPTY_VISIBLE` Regression RCA

## Executive Summary

분석 대상은 `qa_frontend_runs/batch_20260716_222744`의 영어 Full Run이다. 결과 XLSX의 5개 `EMPTY_VISIBLE` row를 raw row 전후, SMART_NEXT request, Evidence transaction, delayed focus observation, DUMP_TREE, Coverage, Identity Shadow, profiler, crop 및 과거 실행과 대조했다.

결론은 다음과 같다.

- Water Leak step 2와 Motion step 2는 동일한 native plugin template의 `lowBattery` node이다. 실제 TalkBack accessibility focus가 화면 안의 같은 크기 node로 이동했지만 `text`, `contentDescription`, `hint`, `stateDescription`, TalkBack speech가 모두 비어 있다. 두 row는 하나의 공통 앱 접근성 결함 signature이다.
- Clothing Care step 2는 WebView 진입 후 실제로 도달한 `DASC_0127-25` 정보 아이콘이다. targeted crop에서는 의미가 있는 정보 아이콘이지만 accessibility label이 없고, tree에도 대신 사용할 child label이 없다. Anchor evidence가 잘못된 row를 합성한 것이 아니라, Phase 10.2.2A가 이전에 진입하지 못했던 화면을 정상적으로 노출한 결과다.
- Clothing Care step 3은 같은 identity에서 다음 이동이 거절된 뒤 `repeat_no_progress`로 끝난 terminal row이다. 결함의 새 원인이 아니라 step 2의 `DUPLICATE_DERIVED_FAILURE`이다. 다만 현 계약에서는 별도 raw quality FAIL을 유지하는 것이 맞다.
- Home Monitor step 1은 과거와 동일한 `shm_setting_button` signature이다. 이번 실행에서도 실제 focus, bounds, class, empty label/speech가 일치하므로 `KNOWN_APP_ACCESSIBILITY_LIMITATION`이다.
- Identity Shadow는 이동을 `MOVE_CONFIRMED/HIGH`로 판정했고, XLSX quality layer는 접근 가능한 이름이 없는 node를 `EMPTY_VISIBLE/FAIL`로 판정했다. 두 판정은 서로 다른 질문에 답하며 모순되지 않는다. false positive는 0건이다.
- 최신 English targeted replay `batch_20260717_091036`은 Water, Motion, Clothing에서 같은 node signature와 empty accessibility payload를 다시 관찰했다. Water/Motion crop은 해당 `lowBattery` bounds에 실제 배터리 아이콘과 `100%` 픽셀이 있음을, Clothing crop은 실제 정보 아이콘임을 확인한다. 이는 화면의 의미가 accessibility label로 전달되지 않는 앱 결함이라는 결론을 강화한다.

최종 승인 판정은 **APPROVABLE WITH REVIEWED LIMITATIONS**이다. 원본 FULL 결과의 raw FAIL은 유지하고, 세 limitation signature를 검토·등록한 뒤에만 수동 approval을 진행한다. EMPTY_VISIBLE 판정 완화나 traversal 코드 수정은 필요하지 않다.

## Current vs Historical Failure Inventory

| Scenario | Step | Current signature | Current result | Historical comparison | RCA classification |
|---|---:|---|---|---|---|
| `device_water_leak_sensor_plugin` | 2 | `lowBattery`, `android.view.View`, `[747,310,933,382]`, empty label/speech | `EMPTY_VISIBLE/FAIL` | 영어 `batch_20260715_223507` 및 한국어 `batch_20260716_082517`에도 exact signature 존재. Phase 9.5.4에는 이 node가 row로 나타나지 않음 | `NEWLY_REACHED_EXISTING_DEFECT` with confirmed app defect |
| `device_motion_sensor_plugin` | 2 | Water와 동일 | `EMPTY_VISIBLE/FAIL` | 영어/한국어 비교 run에 exact signature 존재. Phase 9.5.4에는 나타나지 않음 | `NEWLY_REACHED_EXISTING_DEFECT` with confirmed app defect |
| `life_clothing_care_plugin` | 2 | `DASC_0127-25`, `android.view.View`, `[930,778,1002,850]`, empty label/speech | `EMPTY_VISIBLE/FAIL` | 영어 targeted `batch_20260716_212043`에서 exact identity 및 empty row 재현 | `NEWLY_REACHED_EXISTING_DEFECT` with confirmed app defect |
| `life_clothing_care_plugin` | 3 | step 2와 동일 identity | `EMPTY_VISIBLE/FAIL`, `repeat_no_progress` | 같은 targeted run에서도 반복 | `DUPLICATE_DERIVED_FAILURE` |
| `life_home_monitor_plugin` | 1 | `com.samsung.android.oneconnect:id/shm_setting_button`, `android.widget.Button`, `[804,118,924,310]`, empty label/speech | `EMPTY_VISIBLE/FAIL` | Phase 9.5.4, `batch_20260715_223507`, 한국어 Full Run 및 더 오래된 runs에 exact signature 반복 | `KNOWN_APP_ACCESSIBILITY_LIMITATION` |

“신규”는 두 가지로 구분해야 한다.

- Phase 9.5.4의 failure inventory 대비 새로 관찰된 primary FAIL row는 Water, Motion, Clothing step 2의 3개이다.
- 독립적인 신규 root cause signature는 2개이다. Water/Motion은 하나의 `lowBattery` template 결함이고 Clothing은 별도 `DASC_0127-25` 결함이다.
- 현재 Full Run에서 처음 생긴 결함은 아니다. Water/Motion은 직전 영어 Full Run에 이미 있었고 Clothing은 직전 targeted run에서 이미 재현됐다.
- 최신 clean-HEAD targeted replay `batch_20260717_091036`은 Water/Motion의 step 2 및 Clothing의 같은 `DASC_0127-25` identity를 다시 재현했다. Clothing의 step index는 시작 focus 위치 때문에 달라질 수 있으므로, limitation match key는 step 번호가 아니라 scenario + node signature + bounds + empty payload다.

## Artifact and Environment Comparison

### Current artifact completeness

다음 artifact를 상호 대조했다.

- `batch_summary.json`, device `summary.json`, `runner.log`, `logcat.txt`
- `talkback_compare_20260716_222754.normal.log`
- raw/filtered/summary/result sheet를 포함한 `talkback_compare_20260716_222754.xlsx`
- `.evidence.jsonl`, `.evidence_manifest.json`, `.evidence_reconciliation.json`
- `.focusable_inventory.json`, `.focusable_coverage.json`
- scenario별 profiler JSON과 `.profiler.zip`
- `.environment_profile.json`, `runtime_config.json`, crops

현재 run은 FULL이고 32개 scenario가 관찰됐으며 process return code는 0이다. Evidence reconciliation은 PASS, event 26,056개, orphan 0, duplicate 0, anchor abort 0이다. Identity V2는 817 transactions 중 COMPLETE 814, PARTIAL 3이고, verdict는 `MOVE_CONFIRMED` 545, `STATIC_CONFIRMED` 241, `SNAPBACK` 1, `INDETERMINATE` 30이다. 대상 5개 row에서 evidence orphan/duplicate 또는 recovery는 없다.

EnvironmentProfile은 COMPLETE이다. 주요 비교 값은 다음과 같다.

| Field | Current Full Run |
|---|---|
| Device | Samsung Galaxy Z Flip6, `SM-F741N` |
| OS | Android 15, One UI 7 |
| Locale | `en-US` |
| SmartThings | `1.8.47.24` / `184724010` |
| TalkBack | Samsung TalkBack `15.1.01.1` / `1510101000` |
| Helper | `1.0`, APK SHA-256 `2348064...aa04` |
| Repository | `b3b25a568e9afff4a17427989b1d7d1e127c2eb8`, dirty `false` |
| Runtime config hash | `bec16a...dfd95` |
| Scenario registry hash | `789ebbd...862b6` |
| Environment fingerprint | `c7b389db...ca7ab0`, COMPLETE |
| Document digest | `27e976ff...c5cf6` |
| Flags | profiler/evidence/identity/coverage enabled |

### Historical parity

| Run | Parity | Use |
|---|---|---|
| `batch_20260715_223507` English Full | Same device, OS/app/TalkBack/helper, locale and runtime config hash; clean. Commit `74643d3` and registry hash differ; profiler was off | Strong signature comparison, not exact code/flag parity. Water/Motion `lowBattery` and Home Monitor exact failures already present |
| `batch_20260716_212043` Clothing English targeted | Same device/app/TalkBack/helper/locale. Single scenario, coverage off, commit `74643d3`, dirty `true`, different runtime hash | Direct UI/signature reproduction, but not approval parity |
| `batch_20260717_091036` English targeted replay | Same device, app, TalkBack, helper, locale, scenario registry and `b3b25a5` HEAD as the Full Run. Evidence/identity/profiler/coverage on; runtime-config hash differs because this is a smoke selection. Its profile marks dirty because the workspace contained this RCA document | Current-code reproduction evidence. It is corroborating evidence, not the baseline candidate itself |
| Phase 9.5.4 `batch_20260715_082735` | Same physical device/app observed in the prior RCA, but predates canonical EnvironmentProfile and current contracts | Historical reference only. Water/Motion `lowBattery` absent; Clothing was a different content state; Home exact signature present |
| `batch_20260716_082517` Korean Full | Same device/app/TalkBack/helper/runtime family but locale differs | Locale-independent corroboration only. Water/Motion exact native node signature present |

Scenario registry, order and flags differ where stated, so targeted/Korean/Phase 9.5.4 data is not treated as strict environment parity. It is used only to establish persistence, exact focus identity, or UI meaning.

### Crop provenance limitation

`tb_runner/image_utils.py` constructs a crop path from `tab_name`, `step_index`, and `visible_label`. It does not include `scenario_id` or a row/transaction key:

```text
{tab_name}_step_{step_index}_{visible_label}.png
```

Consequently, both Water and Motion point to `i_._devices._step_2_item.png`, and Clothing points to a shared `i_._life._step_2_item.png`. In the Full Run later scenarios overwrite these paths: the current device step-2 crop contains a later Spotify UI and the current life step-2 crop is also from a later scenario. These images cannot prove or disprove their original rows.

This is an artifact provenance defect, not the cause of `EMPTY_VISIBLE`: the row payload, full DUMP_TREE, stable focus snapshots and Evidence transactions retain the correct identities. `batch_20260716_212043` and the latest replay both show `DASC_0127-25` as an information icon. The latest replay's shared Water/Motion crop still cannot be attributed to one scenario path, but both rows have the same `lowBattery` resource, class, bounds and UI template; its crop is the recorded target bounds and visibly contains the battery icon with `100%`. It corroborates the semantic conclusion but does not replace transaction evidence.

### Latest replay signature confirmation

| Scenario / replay row | Node and representative | Action / transaction | Identity and evidence | Visible/speech/crop |
|---|---|---|---|---|
| Water step 2 | actual-focus `lowBattery`, `android.view.View`, SmartThings, `[747,310,933,382]`; no representative replacement | SMART_NEXT `9de1824b`, success; `tx_6d752bd9011a47659a9cb81ea43c57ee` | `MOVE_CONFIRMED`; immediate + 3 delayed focused/visible/enabled observations; reconciliation PASS | visible and speech empty; crop at target bounds shows battery icon and `100%` |
| Motion step 2 | identical actual-focus signature; no representative replacement | SMART_NEXT `201980ff`, success; `tx_84128bfe80864b06ae6236deb225b9b0` | `MOVE_CONFIRMED`; immediate + 3 delayed stable observations; reconciliation PASS | visible and speech empty; same target crop content |
| Clothing first DASC row | actual-focus `DASC_0127-25`, `android.view.View`, SmartThings, `[930,778,1002,850]`; no representative replacement | SMART_NEXT `37737c6c`, success; `tx_8ac19c1badef4ba1bb75f1d8240152fd` | successful focus commit and delayed observations; anchor already accepted | node label empty; entry-context speech is “Clothing Care”; crop is information icon |
| Clothing repeat rows | same actual-focus identity and bounds | `e572f9e9` / `tx_b75016976d91468ba73d8203aac766d6` rejected, followed by `d7625762` | same node persists; one recovery attempt remains unrecovered; terminal stop is `repeat_no_progress` | visible and speech empty; information-icon crops remain stable |

The Clothing entry-context announcement is not a label recovered from the information icon: the helper node, DUMP_TREE and row's `visible_label` remain empty. It is therefore not representative selection or parser loss.

## Water Leak RCA

### Row and transaction trace

The XLSX schema has no standalone persisted `row_id`; therefore `scenario_id + step` is the stable row join key.

| Field | Value |
|---|---|
| Row key | `device_water_leak_sensor_plugin:2` |
| SMART_NEXT request / transaction | `dc1d1484` / `tx_9e55ba65017e4db48c34d9f453feacce` |
| Action | SMART_NEXT, success `true`, result `moved` |
| Pre-focus | `more`, “More options”, Button, `[936,118,1008,310]` |
| Immediate / delayed / post focus | all `lowBattery`, same class and bounds |
| Focus node | `android.view.View`, package SmartThings, `[747,310,933,382]` |
| Accessibility focused / visible / enabled | `true / true / true` |
| Text fields | text, contentDescription, hint, stateDescription, talkbackLabel all empty |
| Speech / announcement | empty / none, announcement count 0 |
| DUMP_TREE | `lowBattery` and its empty TextView child have no label; “Water sensor”, “History”, “Dry” are separate/outside nodes |
| Identity / progress / visit | `MOVE_CONFIRMED`, HIGH / accepted / accepted |
| Recovery / stop | none / none for step 2 |
| Shadow result | normalized visible is empty -> `EMPTY_VISIBLE` -> quality `FAIL` -> `SHADOW_FAIL` |

Focus bounds are non-zero and inside the logical display. Immediate, three delayed observations, and post snapshot are stable. There is no late TalkBack speech and no stale focus/identity join. The helper did not choose an unrelated container: it recorded the node on which TalkBack actually placed accessibility focus.

The tree shows this is a native SmartThings plugin view, not the WebView path changed in Phase 10.2.2A. The same exact signature in Motion indicates a shared device plugin UI template. Historical June evidence also contains cases where the same `lowBattery` resource had a real value such as “100%”; the current battery/state presentation instead exposes the resource without an accessible value. Phase 9.5.4 did not traverse this node because that dynamic node was not present in its candidate sequence.

The latest targeted replay provides current-code reproduction: its SMART_NEXT request `9de1824b` / transaction `tx_6d752bd9011a47659a9cb81ea43c57ee` succeeds and commits `lowBattery`; the immediate observation plus three delayed observations remain focused, visible, enabled and empty. Its crop for `[747,310,933,382]` visibly contains the battery icon and `100%`, while the helper observation and empty child TextView still contain no text, content description, merged/TalkBack label or speech. Evidence reconciliation is PASS with no orphan or duplicate events. This excludes a missing visual control, stale focus, or delayed-speech explanation.

**Classification:** `NEWLY_REACHED_EXISTING_DEFECT` (underlying `CONFIRMED_APP_ACCESSIBILITY_DEFECT`), confidence HIGH. It can be an explicit baseline limitation after replay; it does not justify changing traversal or downgrading `EMPTY_VISIBLE`.

## Motion RCA

| Field | Value |
|---|---|
| Row key | `device_motion_sensor_plugin:2` |
| SMART_NEXT request / transaction | `0dceca71` / `tx_35ffe7ed44bb467c946c3df53d0ad924` |
| Action | SMART_NEXT, success `true`, result `moved` |
| Pre-focus | `more`, “More options”, Button, `[936,118,1008,310]` |
| Immediate / delayed / post focus | all `lowBattery`, same class and bounds |
| Focus node | `android.view.View`, package SmartThings, `[747,310,933,382]` |
| Accessibility focused / visible / enabled | `true / true / true` |
| Text fields and speech | all accessibility label fields empty; no speech/announcement |
| DUMP_TREE | same empty node/child structure as Water; surrounding Motion card labels are not contained labels |
| Identity / progress / visit | `MOVE_CONFIRMED`, HIGH / accepted / accepted |
| Recovery / stop | none / none for step 2 |

TalkBack log additionally reports that its custom-label manager failed to parse resource `lowBattery`. This is corroborating evidence, not the sole basis of the verdict. Water and Motion have the same resource, class, bounds, action sequence, label absence and historical occurrence, so they are one common root cause. Both are native plugin UI and unrelated to the recent WebView anchor changes.

The latest targeted replay independently repeats the sequence with SMART_NEXT request `201980ff` / transaction `tx_84128bfe80864b06ae6236deb225b9b0`. It records a successful move to the same focused/visible/enabled `lowBattery` node, with three stable delayed observations and no speech. The crop is the same battery-value control at the same bounds. Since Water and Motion share the exact visual and accessibility signature, the common crop-path limitation does not create an ambiguity about root cause; nevertheless, future evidence storage must make the two images independently addressable.

**Classification:** `NEWLY_REACHED_EXISTING_DEFECT` (underlying `CONFIRMED_APP_ACCESSIBILITY_DEFECT`), confidence HIGH. It shares one app defect ticket and limitation family with Water but should preserve both scenario signatures in the limitation snapshot.

## Clothing Care RCA

### Entry and anchor boundary

Card discovery, selection, screen transition and verification all succeeded. Anchor evidence records:

```text
accepted=true reason=correlated_empty_webview_landing
```

That evidence is consumed only for post-entry anchor acceptance. The first anchor row is Clothing Care, and the following same-title logical row is filtered. `DASC_0127-25` appears only after traversal has started. No anchor metadata is copied into row text or speech fields.

### Step 2 primary defect

| Field | Value |
|---|---|
| Row key | `life_clothing_care_plugin:2` |
| SMART_NEXT request / transaction | `1cd95066` / `tx_a2109d9823bb493fbe4e2e83222e0015` |
| Action | SMART_NEXT, success `true`, result `moved` |
| Immediate / delayed / post focus | all `DASC_0127-25`, exact bounds |
| Focus node | `android.view.View`, package SmartThings, `[930,778,1002,850]` |
| Accessibility focused / visible / enabled | `true / true / false` in evidence |
| Text fields and speech | text/contentDescription/hint/stateDescription/talkbackLabel/speech all empty |
| DUMP_TREE | Clothing Care title is a separate node; DASC node and its WebView/container descendants contain no usable label |
| Identity / progress / visit | `MOVE_CONFIRMED`, HIGH / accepted / accepted |
| Recovery | none |
| Result | `EMPTY_VISIBLE/FAIL`; result recomputation marks `terminal_not_handled` because a failed follow-up exists |

The targeted English run `batch_20260716_212043` reproduces the exact resource, class, bounds, and empty fields. Its non-colliding crop shows a visible information icon. This is case B: the screen conveys icon meaning, but the accessibility node has no name. It is not case C or D; there is no contained label to merge and no label present earlier in the evidence pipeline.

The latest replay confirms the same conclusion on `b3b25a5`. It reaches `DASC_0127-25` at `[930,778,1002,850]`; its first traversal row is a successful move (`37737c6c` / `tx_8ac19c1badef4ba1bb75f1d8240152fd`) with empty visible text but the surrounding entry announcement “Clothing Care”. The subsequent request `e572f9e9` / transaction `tx_b75016976d91468ba73d8203aac766d6` is rejected while the same empty icon remains focused. The latest crops for those rows visibly show the information icon. The row index differs from the Full Run because the initial focus is already on that icon, not because a different node was selected.

### Step 3 derivative

| Field | Value |
|---|---|
| Row key | `life_clothing_care_plugin:3` |
| SMART_NEXT request / transaction | `ee7ff589` / `tx_969d95611b7c4704a1b4bb8f917e400d` |
| Action | SMART_NEXT rejected/reached end, success `false` |
| Focus observations | same `DASC_0127-25`, same bounds, stable and empty |
| Identity | V2 indeterminate because action was rejected; legacy fallback used |
| Duplicate flags | exact/recent semantic duplicate of step 2 |
| Stop | `repeat_no_progress`; traversal stopped normally |
| Result | `EMPTY_VISIBLE/FAIL` plus terminal failure reason |

The repeated-item stop works as intended. Result-group collapse keys include `failure_reason`; step 2 (`terminal_not_handled`) and step 3 (`repeat_no_progress`) therefore remain distinct rows. Deleting the second row or treating repetition as accessibility PASS would hide useful terminal evidence. For defect counting, however, step 3 is not a second app defect.

**Classification:** step 2 is `NEWLY_REACHED_EXISTING_DEFECT` with underlying `CONFIRMED_APP_ACCESSIBILITY_DEFECT`, confidence HIGH. Step 3 is `DUPLICATE_DERIVED_FAILURE`, confidence HIGH. Phase 10.2.2A is an exposure/enabling cause, not a defect-creation or row-corruption cause.

## Home Monitor Signature Verification

| Field | Current and historical signature |
|---|---|
| Row key | `life_home_monitor_plugin:1` |
| SMART_NEXT request / transaction | `cca506e6` / `tx_7b699e04866449b1bd6eb78dd4b36502` |
| Resource / class | `com.samsung.android.oneconnect:id/shm_setting_button` / `android.widget.Button` |
| Bounds / position | `[804,118,924,310]`, top-right toolbar |
| Action and focus | SMART_NEXT success/moved; immediate, delayed and post focus stable |
| Accessibility state | focused, visible, enabled, non-zero/in-screen bounds |
| Label and speech | all accessibility label fields empty; no speech/announcement |
| Tree | real empty settings button; sibling “More options” is a distinct node |
| Identity | `MOVE_CONFIRMED`, HIGH, complete evidence |
| Mismatch | `EMPTY_VISIBLE/FAIL` |

The resource, class, bounds, step, visual position and mismatch match the known issue across Phase 9.5.4 and later English/Korean runs. It is therefore the same `KNOWN_APP_ACCESSIBILITY_LIMITATION`, confidence HIGH. The actual FAIL must remain in the source result.

## Shadow Classification Path

The implemented path is:

```text
collected actual-focus row
  -> representative/focus-node label backfill only when a real non-empty label exists
  -> visible/speech normalization
  -> _mismatch_type: empty raw visible_label => EMPTY_VISIBLE
  -> bounded nearby-contained-label check
  -> _final_result: EMPTY_VISIBLE => FAIL
  -> _shadow_verdict_for_row: final_result FAIL => SHADOW_FAIL
  -> result XLSX / summary quality issue
```

Relevant implementation is in `tb_runner/excel_report.py`:

- focus-node fallback considers only `talkbackLabel`, `mergedLabel`, `contentDescription`, and `text`; it cannot manufacture a label.
- representative semantics are used only when `_representative_row_source == "representative"` and `representative_visible` is non-empty.
- `_mismatch_type` tests raw `visible_label` first and returns `EMPTY_VISIBLE` when it is empty.
- `_find_nearby_contained_label` can change the result to `REPRESENTATIVE_CONTEXT` only for a bounded, semantically related row with both real visible text and speech. None of the five rows has such a candidate.
- `_final_result` maps `EMPTY_VISIBLE`, `EMPTY_SPEECH`, and `LABEL_MISMATCH` to FAIL.
- Shadow maps a final quality FAIL to `SHADOW_FAIL`.

“Visible” here means an accessible visible label represented in the collected row, not merely visible pixels. Icon-only controls have no blanket exception. Action success proves movement, not label quality. Identity Shadow therefore correctly says the node was reached, while the result layer correctly says the reached node is unnamed.

Speech was observed through the normal immediate/delayed/post windows. The stable empty observations and zero announcements rule out a single idle-window miss. New anchor evidence is scoped to entry and does not participate in label normalization. No parent text is unconditionally copied to a child.

## Root Cause Matrix

| Row(s) | Primary classification | Confidence | Direct evidence | Recent change causality | Baseline limitation | Code fix | App defect |
|---|---|---|---|---|---|---|---|
| Water 2 + Motion 2 | `NEWLY_REACHED_EXISTING_DEFECT` | HIGH | exact stable focus, empty tree/fields/speech, current replay reproduces successful move and target crop | No Phase 10.2.2 relationship; dynamic device-state node appeared | Yes; retain both scenario signatures under one shared root cause | No traversal/shadow fix | Yes, one shared template ticket |
| Clothing 2 | `NEWLY_REACHED_EXISTING_DEFECT` | HIGH | exact stable focus, both targeted crops show info icon, empty node/tree, current-HEAD reproduction | 10.2.2A enabled entry only; did not create node/row | Yes | No current pipeline fix | Yes |
| Clothing 3 | `DUPLICATE_DERIVED_FAILURE` | HIGH | same identity, rejected action, duplicate flags, repeat stop | Expected terminal behavior | Include as derivative evidence, not a second defect | No | Covered by Clothing ticket |
| Home Monitor 1 | `CONFIRMED_APP_ACCESSIBILITY_DEFECT` | HIGH | exact historical resource/class/bounds/step/empty state | None | Yes; existing known limitation signature | No | Existing ticket/limitation |

Rejected alternatives:

- `CONFIRMED_TRAVERSAL_DEFECT`: focus movement and target identity are complete and stable.
- `CONFIRMED_SHADOW_CLASSIFICATION_DEFECT`: classification follows the canonical empty-label contract.
- `CONFIRMED_EVIDENCE_COLLECTION_DEFECT` as the row cause: tree, helper payload and TalkBack events agree. Crop collision is separate provenance debt.
- `DYNAMIC_TRANSIENT`: lowBattery may be state-dependent, but its unnamed signature persists across multiple full runs/locales; the observations themselves are not transient.
- `UNPROVEN`: sufficient node, event and historical evidence exists. Only strict approval-parity visual replay remains.

## Baseline Approval Assessment

### Answers to approval questions

- **Are Water, Motion and Clothing new quality regressions?** They are new relative to the Phase 9.5.4 failure inventory, but not newly introduced in the current commit. They are existing app accessibility defects newly reached/exposed by current UI state and recovered entry coverage.
- **Did Phase 10.2.2A/B/C cause them?** No for Water, Motion and Home. For Clothing, 10.2.2A made valid entry possible and thus exposed the node; it did not create the unnamed node, lose its label, or corrupt its row. 10.2.2B/C are unrelated.
- **Were previously untraversed items discovered?** Yes. Dynamic `lowBattery` was absent from Phase 9.5.4's path; Clothing was previously blocked/different and is now traversed after valid anchor recovery.
- **Do targeted replays reproduce the failures?** Yes. `batch_20260717_091036` reproduces Water and Motion at the same step-2 `lowBattery` signature after successful focus movement, and Clothing at the same `DASC_0127-25` signature. `batch_20260716_212043` independently corroborates Clothing's information-icon semantics. The newer replay has the same HEAD as the Full Run; its environment profile records dirty, so it is corroborating evidence only and is not used as the baseline candidate.
- **Was holding approval before RCA correct?** Yes. The five rows required separation into three primary defect rows, one terminal derivative, and one known limitation, and current Full Run crops have provenance collisions.
- **Can this Full Run be approved now as PASS WITH LIMITATIONS?** Yes, subject to normal candidate/offline validation and manual review of the limitation snapshot. The Full Run itself is the clean, complete-environment baseline artifact. The current targeted replay closes the prior reproduction gap; it does not relax any gate or convert the source FAIL rows to PASS.

### Required limitation snapshot

The reviewed limitation set should preserve, without suppressing source FAILs:

1. limitation code and classification;
2. scenario ID and step;
3. resource ID, class, package and normalized bounds;
4. text/contentDescription/hint/stateDescription/speech emptiness;
5. accessibility-focused/visible/enabled state;
6. action request/transaction result and Identity verdict;
7. DUMP_TREE node/child signature;
8. current EnvironmentFingerprint, app/TalkBack/helper versions and locale;
9. evidence/crop artifact digests from the targeted replay;
10. historical reproduction references;
11. for Clothing step 3, an explicit `derived_from=life_clothing_care_plugin:2` relation;
12. reviewer rationale that an app-owned issue is accepted as a limitation, not converted to PASS.

Water and Motion should share one root-cause/issue family while retaining two match signatures. Home Monitor should reference the existing limitation and exact signature rather than being silently grandfathered.

## Targeted Replay Result

No further device replay is required for this RCA. The latest English smoke replay `batch_20260717_091036` completed all three requested scenarios with profiler, Evidence Ledger, Identity V2 and Coverage enabled; reconciliation is PASS, event count 588, orphan 0 and duplicate 0. It reproduced:

1. Water Leak: successful move to `lowBattery`, exact bounds, empty accessibility fields/speech, target crop present;
2. Motion: the identical successful-move `lowBattery` signature and crop content;
3. Clothing: anchor entry followed by the same unlabeled information-icon identity and normal `repeat_no_progress` terminal handling.

The smoke run is supporting evidence only. The clean FULL `batch_20260716_222744` remains the candidate source. Future isolated replays are optional only if an approver requires scenario-addressable crop paths; they are not an approval gate under the current architecture.

## Recommended Fix Boundaries

No production code file must change to correct these five `EMPTY_VISIBLE` classifications.

App-side fixes belong in SmartThings/plugin code outside this repository:

- give `lowBattery` a localized accessible name/value/state or remove it from focus order when it conveys no information;
- give the Clothing `DASC_0127-25` information icon a localized accessible name, or make a disabled decorative node non-focusable;
- give `shm_setting_button` a localized settings label.

A separate, non-blocking repository follow-up should harden evidence provenance in:

- `tb_runner/image_utils.py`: include scenario ID and a stable row/transaction discriminator in crop filenames;
- the callers/tests that construct crop metadata, principally `tb_runner/collection_flow.py`, `tests/test_collection_flow.py`, and image/report tests as required.

That change must not alter traversal, identity, quality classification, approval gates, or backfill labels. No change is recommended to `tb_runner/excel_report.py` for these failures.

## Residual Unknowns

- The precise SmartThings internal condition that switches `lowBattery` from a named percentage/value to the empty node is not encoded in current metadata. The evidence strongly establishes the accessibility defect once the node exists, but not its app-side state machine.
- Current shared crop paths cannot establish an independently addressable Water versus Motion image. Their exact node signature and target bounds are identical, and the replay crop confirms the visual battery control, so this is a provenance limitation rather than an approval blocker.
- The older Clothing targeted run is dirty and has different flags/runtime hash, so it corroborates identity and UI meaning only. The newer replay has the Full Run's HEAD and supplies current-code corroboration; the Full Run remains the clean candidate artifact.
- Phase 9.5.4 predates canonical environment capture, limiting strict parity claims.
- The result sheet intentionally retains Clothing steps 2 and 3 because their terminal failure reasons differ. Whether baseline presentation should link derivative rows without suppressing them is a later reporting-policy question, not part of this RCA.

Recommended follow-up is split into three work packages:

1. reviewed limitation snapshot plus first-baseline candidate/offline validation and manual approval decision;
2. SmartThings app defect registration for the three root signatures;
3. later crop provenance hardening.

**Final verdict: APPROVABLE WITH REVIEWED LIMITATIONS**
