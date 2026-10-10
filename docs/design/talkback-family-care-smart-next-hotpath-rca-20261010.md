# Family Care SMART_NEXT deep performance RCA — 2026-10-10

> Latest result: **PARENT_CHILD_CACHE_FIX_PASS_WITH_LIMITATIONS**. Same-fixture semantic diff NONE; matched-instrumentation ACTIVE 10 before / 10 after. Runtime-state average reduced 88.99%; actual parent calls reduced 99.35%. Earlier conclusions below are historical.

## Previous WAITING-only decision and scope

**OVERALL_VERDICT=SMART_NEXT_HOT_PATH_NOT_PROVEN**

The available WAITING evidence proves the runtime-state collection region dominates latency. It does not yet identify a single internal function responsible for the majority of the 30–60 seconds. No new optimization was implemented; no commit, push, merge, or Full32 was performed.

Fresh Family Care profiling stopped at the preflight state gate: the service hierarchy reported `profile_status_text=지금 활동 중` (ACTIVE), rather than the required `활동 없음` (WAITING). This happened naturally before any new Family Care SMART_NEXT. Fresh Family Care requests: **0**, including **0 ACTIVE requests**. The user explicitly selected **WAITING 범위 유지** after being informed of the state change. The required fresh WAITING sample set of at least ten remains pending.

The result consists of opt-in instrumentation, 47 archived WAITING request correlations, and six successful live control requests. Archive samples do not substitute for the missing fresh T0–T12 Family Care measurements. No raw unique coverage comparison, coverage>=32 gate, termination change, camera change, English run, Phase 4 change, or lifecycle architecture change was used.

## Source safety and preservation

```text
START_HEAD=cd5e8048a7cf0d795c2bddcec46ab7047d26fcdb
FINAL_HEAD=cd5e8048a7cf0d795c2bddcec46ab7047d26fcdb
ORIGIN_MAIN=cd5e8048a7cf0d795c2bddcec46ab7047d26fcdb
WORK_BRANCH=fix/family-care-smart-next-latency
TRACKED_DIRTY=YES
HEAD_ORIGIN_MAIN_MATCH=YES
```

The starting experiment modified A11yNavigator.kt, A11yTraversalAnalyzer.kt, and SmartNextDispatcherTest.kt (72 insertions, 7 deletions). It was preserved in `family_care_hotpath_20261010/start_experiment.patch` and per-file `before_*.kt` copies. It was not reset or treated as an accepted optimization. Existing RCA files, out/, tests/out/, and QA run artifacts were preserved.

This task adds profiling hooks in A11yCommandReceiver.kt, A11yFocusExecutor.kt, A11yHelperService.kt, A11yNavigator.kt, A11yNodeUtils.kt, A11yPostScrollScanner.kt, A11yTraversalAnalyzer.kt, and SmartNextDispatcher.kt, plus the new untracked SmartNextPerf.kt. The existing dispatcher test modification remains. All additions and documentation remain uncommitted; nothing was staged or generated into a production commit.

## Evidence and reproducibility

- Primary archive: `C:\Users\smani\AppData\Local\Temp\talkback-full32-20261009-monitor-output\qa_frontend_runs\batch_20261010_020042\device_SM-F741N_R3CX40QFDBP`, its Family Care evidence.jsonl and logcat.txt. This task only analyzed the existing Full32; it did not launch one.
- State gate: `family_care_hotpath_20261010/waiting_before/before_hierarchy.json` and waiting_before_console.log.
- Control Menu: `family_care_hotpath_20261010/control_menu/{before_hierarchy.json,after_hierarchy.json,start.json,end.json,requests.json,logcat.txt}`.
- Control Motion Sensor: corresponding files in `family_care_hotpath_20261010/control_motion/`.
- Joined results: profile_analysis.json; extraction script: analyze_profile.py. Final bounded runtime audit: final_audit.json.
- Archive requests are joined by request_id and helper_event_id. Helper event timestamps are used for execution, not buffered evidence receipt timestamps. Nine earlier overlay requests at duplicated step indexes 2–10 are excluded; the 47 main traversal requests remain. Original run phase/state provenance is retained in the earlier state-controlled RCA and archive.
- p50 is the median; p95 is nearest rank (`ceil(0.95*n)`). Correlations are Pearson correlations across all 47 paired request observations. These nested region correlations localize time; they do not prove causal IPC or algorithm behavior.

## Timing model

Profiling is enabled only by `profileSmartNext=true` on a SMART_NEXT broadcast. A request-scoped ThreadLocal is established on the existing dedicated dispatcher worker; the worker and focus-action scheduling are unchanged. Counters are not consumed by navigation. Original getChild/getParent/refresh/findFocus/performAction operations are wrapped once, with no extra diagnostic hierarchy walks or memoization. New diagnostic logs contain bounded timing summaries and counters, not full hierarchy payloads. Existing result/evidence transport remains present.

Each marker carries request_id, wall timestamp, and elapsed monotonic milliseconds. End-of-request spans carry call count, summed inclusive duration, and exclusive duration. Request counters are emitted in the summary. Node/candidate counts are summary counters, not separate full payloads at each marker. Multiple actions/iterations can emit a stage more than once. T labels identify semantic milestones, **not a guaranteed numerical chronological ordering**: metadata is computed during enumeration, candidate construction precedes current-position identification, and branches may omit milestones. Do not subtract successive numbered markers as exclusive costs.

| Marker | Location / interpretation |
| --- | --- |
| T0 | Existing dispatcher worker starts the profiled request; excludes receiver/queue delay. |
| T1 | First service root getter returns; a second original root getter is also timed in root_acquisition. |
| T2 | Recursive candidate enumeration unwinds at depth zero. |
| T3 | Runtime current/next-position identification completes. |
| T4 | Descendant metadata needed by candidate collection is complete. |
| T5 | Candidate collector, filtering, and spatial sorting complete. |
| T6 | Policy ranking completes. |
| T7/T8 | Original wrapped node action is issued/returns, including focus clear/commit and wrapped scrolling; not proof of the later accessibility event. |
| T9 | Existing immediate post-action focus evidence capture completes; not a new full hierarchy dump. |
| T10 | Service resolved-focus check completes; snapshot/result assembly can remain outside this span. |
| T11 | Existing chunk result serialization completes. |
| T12 | Existing final result log chunks are emitted; optional reply broadcast follows. |

Measured subregions also include normalize_aliases, alias_representative, settings_alias_check, wrapper_alias_check, interactive_descendants, recover_label, root_bounds, descendant_metadata, policy_ranking, event_poll, event_wait, retarget_verify, and the node API wrappers. Recursive enumeration inclusive sums double-count nested descendants; the table below uses its **exclusive** time. Candidate_build and metadata rows are inclusive and overlap. All API wrapper timings include possible local cache hits as well as IPC; the prefix `ipc_` does not prove a remote transaction occurred.

New live profile total runs from worker begin until the callback (including result log emission/reply work) returns, before diagnostic summary log emission. Archive Helper API total runs from the earliest ACTION_EXECUTION_STARTED timestamp to ACTION_API_RESULT. Archive runner total runs TRANSACTION_OPENED to the first populated ACK. These clocks/boundaries are not interchangeable.

## Archived WAITING timing result

No archived request has the new root/enumeration/metadata/ranking/action/event/post/verification/serialization separation. These fine-grained Family Care fields are **UNMEASURED**, not zero. The older focus_node_collection region covers the entire candidate collector; it is not a pure enumeration or descendant-metadata timer. runtime_remainder is arithmetic runtime-state time minus that collector, and is not a timer for normalizeNodes alone.


| Region (ms) | n | Average | p50 | p95 | Max |
| --- | --- | --- | --- | --- | --- |
| total_ms | 47.00 | 33348.51 | 36376.00 | 55087.00 | 67221.00 |
| runner_total_ms | 47.00 | 34137.45 | 37248.78 | 56263.73 | 68464.28 |
| focus_node_collection_ms | 47.00 | 6931.15 | 7997.00 | 12205.00 | 14948.00 |
| runtime_state_ms | 47.00 | 28642.70 | 31356.00 | 46099.00 | 65706.00 |
| runtime_remainder_ms | 47.00 | 21711.55 | 23122.00 | 36068.00 | 50758.00 |


Runtime-state collection accounts for 85.89% of mean Helper API time; candidate collection 20.78%; the runtime remainder 65.11%. The mean remainder is 21711.55 ms.


| Region correlated with total | Pearson r |
| --- | --- |
| focus_node_collection_ms | 0.78 |
| runtime_state_ms | 0.98 |
| runtime_remainder_ms | 0.96 |


The strongest localized evidence is **collectSmartNextRuntimeState**, particularly the work outside collectFocusNodes: average 21.71 seconds, correlation r=0.965. This region still contains normalization, focus/current-index resolution, logging, state copying, and API calls. The correlation is partly expected because these times are included in total; it cannot rank the individual internal functions.

### Fast / medium / slow

Bins: FAST <20,000 ms; MEDIUM 20,000–<45,000 ms; SLOW >=45,000 ms. Thresholds are descriptive, not acceptance gates.


| Bin | n | Avg total | Avg collector | Avg runtime state | Avg remainder | p95 total | Max total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FAST | 10.00 | 8419.40 | 2334.70 | 6761.10 | 4426.40 | 17396.00 | 17396.00 |
| MEDIUM | 25.00 | 34124.08 | 7165.32 | 29289.28 | 22123.96 | 44523.00 | 44808.00 |
| SLOW | 12.00 | 52507.00 | 10273.67 | 45530.33 | 35256.67 | 67221.00 | 67221.00 |


Both candidate collection and the remainder grow in the slow bin. The remainder rises from 4.43 seconds (fast) to 35.26 seconds (slow). Twelve slow-tail samples are available in the archive; none is a new deep-profile request. One archived request, `09fbacca66cd4cf1adc057c2ed70d6ba`, has collector 14,948 ms and runtime state 65,706 ms, leaving 50,758 ms outside the collector.

### Per-request archived WAITING evidence

VIS is the old visible-node **visit count**, not the new unique tree count. MD is old descendant-metadata scan calls. New TREE_NODE_COUNT, unique VISIBLE_NODE_COUNT, total descendant visits, actionable checks, unique subtree counts, max depth, and the requested fine stage durations are unavailable for every archived row. CO is normalized candidate_count; FN is focus_nodes. Duration columns are milliseconds.


| Request ID | Step | Helper API | Runner ACK | Collector | Runtime | Remainder | VIS | FN | MD | CO |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 09fbacca66cd4cf1adc057c2ed70d6ba | 1 | 67221.00 | 68464.28 | 14948.00 | 65706.00 | 50758.00 | 43 | 35 | 37 | 24 |
| 03331d2ac9ed40db9700f9bfa6fc1a9b | 2 | 30379.00 | 30692.95 | 7152.00 | 29132.00 | 21980.00 | 43 | 35 | 37 | 24 |
| 006eb79cf1fe4b419af7c384594615b4 | 3 | 43004.00 | 43444.28 | 9405.00 | 39318.00 | 29913.00 | 43 | 35 | 37 | 24 |
| 897f73d840de44fd8fe85ca3b10f3fd2 | 4 | 41817.00 | 42780.33 | 7512.00 | 38237.00 | 30725.00 | 43 | 35 | 37 | 24 |
| af7682bae7e3483e97c1afd264523d5c | 5 | 29244.00 | 29929.08 | 8010.00 | 26255.00 | 18245.00 | 43 | 35 | 37 | 24 |
| 42129f3f610f4020a251133c58521484 | 6 | 10450.00 | 11732.66 | 2132.00 | 4999.00 | 2867.00 | 43 | 35 | 37 | 24 |
| c1f5146a58f04e428d7d68ff8cb7c622 | 7 | 30118.00 | 30710.26 | 5656.00 | 20361.00 | 14705.00 | 43 | 35 | 37 | 24 |
| 5f1cc7ed79a24b39b5010d9bfb982898 | 8 | 28654.00 | 29781.54 | 6700.00 | 26653.00 | 19953.00 | 43 | 35 | 37 | 24 |
| 4ce33e2b39fd4b599e283c6778953437 | 9 | 36376.00 | 37248.78 | 9456.00 | 31644.00 | 22188.00 | 43 | 35 | 37 | 24 |
| f6788b32eb7c4db98e2f9c2b1bd01c2e | 10 | 2743.00 | 3677.98 | 769.00 | 1868.00 | 1099.00 | 43 | 35 | 37 | 24 |
| 0a819739a2ab46acbaa539de5be7a121 | 11 | 38477.00 | 39407.25 | 8826.00 | 34352.00 | 25526.00 | 43 | 35 | 37 | 24 |
| 333c7863f5a649fe9cf9d52d3d8561da | 12 | 2882.00 | 3046.33 | 673.00 | 1665.00 | 992.00 | 43 | 35 | 37 | 24 |
| 3955d69c8f834f3fa621bc9026f2616c | 13 | 31653.00 | 32810.07 | 8125.00 | 29744.00 | 21619.00 | 43 | 35 | 37 | 24 |
| cb2c6abd57074eff950b7afd34ba3f7e | 14 | 23207.00 | 24211.03 | 8202.00 | 19681.00 | 11479.00 | 43 | 35 | 37 | 24 |
| 7f9e4926ab674aa3b118258737f91506 | 15 | 52111.00 | 52348.80 | 10160.00 | 46094.00 | 35934.00 | 43 | 35 | 38 | 17 |
| 4643b709359642e99fac8ed2c3b6ba97 | 16 | 10348.00 | 11409.81 | 2794.00 | 8130.00 | 5336.00 | 43 | 35 | 38 | 17 |
| babb6693d35841f7939cff41928c1805 | 17 | 28307.00 | 29430.67 | 9996.00 | 24276.00 | 14280.00 | 43 | 35 | 38 | 17 |
| af7c71c9fa5e4acb8c0e86da61829c16 | 18 | 23138.00 | 24039.87 | 535.00 | 13232.00 | 12697.00 | 43 | 35 | 38 | 17 |
| be26be37eda14f4ebd03384006f342b3 | 19 | 46590.00 | 46799.87 | 12205.00 | 43478.00 | 31273.00 | 43 | 35 | 38 | 17 |
| 948aeaefdfe449579d55c6d990811067 | 20 | 39512.00 | 40343.26 | 10458.00 | 36854.00 | 26396.00 | 43 | 35 | 38 | 17 |
| 7fece277425e4de7a990a0bac2ded249 | 21 | 6908.00 | 7822.12 | 2233.00 | 6628.00 | 4395.00 | 43 | 35 | 38 | 17 |
| ad1a54d5fd8b44199b5606fa0335090b | 22 | 51095.00 | 51318.35 | 7872.00 | 46099.00 | 38227.00 | 43 | 35 | 38 | 17 |
| 5f95267b6a1b472587f2975deb296dad | 23 | 50420.00 | 51436.72 | 7375.00 | 40396.00 | 33021.00 | 43 | 35 | 38 | 17 |
| f9420fa700d34f4e98a5069faeafd932 | 24 | 55087.00 | 56263.73 | 10825.00 | 44842.00 | 34017.00 | 43 | 35 | 38 | 17 |
| 2bbba3b1343747ca82f808acefef7bc0 | 25 | 50147.00 | 50587.21 | 10075.00 | 40684.00 | 30609.00 | 43 | 35 | 38 | 17 |
| f4780cf6fa7e4efc87ed427849f6788a | 26 | 25103.00 | 25383.40 | 7619.00 | 20906.00 | 13287.00 | 43 | 35 | 38 | 17 |
| da5b7087f86842b697577f12fcf870e8 | 27 | 44808.00 | 45714.14 | 12627.00 | 42762.00 | 30135.00 | 43 | 35 | 38 | 17 |
| 161a02ddd7dd46efbd8beccc87fa7b2a | 28 | 49929.00 | 51050.53 | 10998.00 | 47066.00 | 36068.00 | 43 | 35 | 38 | 17 |
| 1d7798b51d4d41abad43ea7e8249ccd8 | 29 | 45571.00 | 46528.34 | 10376.00 | 43579.00 | 33203.00 | 43 | 35 | 38 | 17 |
| 9bb30c8a956e4ead858b47ea18f5963d | 30 | 7792.00 | 7987.06 | 1831.00 | 7481.00 | 5650.00 | 43 | 35 | 38 | 17 |
| 5ddceb83e485451b824ce0dd62cfc3ac | 31 | 17396.00 | 18356.67 | 8339.00 | 13743.00 | 5404.00 | 43 | 35 | 38 | 17 |
| 9f4085a15c61427884535175b8116ec7 | 32 | 63318.00 | 63625.78 | 10710.00 | 45478.00 | 34768.00 | 43 | 35 | 38 | 17 |
| 82f87f419bbd4f9ea7f65f92fb4fc00f | 33 | 3832.00 | 4914.48 | 704.00 | 2304.00 | 1600.00 | 43 | 35 | 38 | 17 |
| 1eb616f17ab44dcd90d696bafc08aed1 | 34 | 29977.00 | 30152.04 | 1150.00 | 27467.00 | 26317.00 | 43 | 35 | 38 | 17 |
| 6f8e16e5381e4a38926c67264dab5d87 | 35 | 8380.00 | 9356.52 | 2637.00 | 8042.00 | 5405.00 | 43 | 35 | 38 | 17 |
| 69299e6384c84c6195aa992db53a3a85 | 36 | 32556.00 | 32963.08 | 2740.00 | 31356.00 | 28616.00 | 43 | 35 | 38 | 17 |
| 944ffd8209804bcdb476259ad05d1b82 | 37 | 46349.00 | 47614.52 | 8040.00 | 40091.00 | 32051.00 | 43 | 35 | 38 | 17 |
| 65275f8e19874f5b8cf887636446e242 | 38 | 44523.00 | 45790.69 | 7119.00 | 35483.00 | 28364.00 | 43 | 35 | 38 | 17 |
| 84ccd6630f494c38b8ac352058d48f9f | 39 | 40424.00 | 41594.07 | 9704.00 | 31602.00 | 21898.00 | 43 | 35 | 38 | 17 |
| 025c24f2093a413fb62202b50000b99a | 40 | 40377.00 | 41586.72 | 2115.00 | 30882.00 | 28767.00 | 43 | 35 | 38 | 17 |
| 0a57ec06772e438fa587ff67a8f86105 | 41 | 52246.00 | 53418.89 | 9700.00 | 42851.00 | 33151.00 | 43 | 35 | 38 | 17 |
| e090d81e6da047b7875995563dfad95b | 42 | 40801.00 | 41950.40 | 9578.00 | 32700.00 | 23122.00 | 43 | 35 | 38 | 17 |
| 8aee37e4edbf495eaf529338a686e7af | 43 | 25677.00 | 26087.52 | 2047.00 | 17501.00 | 15454.00 | 43 | 35 | 38 | 17 |
| 3f85f5f8d63b47ba90bbdc00f7779cf0 | 44 | 43006.00 | 43409.53 | 6660.00 | 32974.00 | 26314.00 | 43 | 35 | 38 | 17 |
| ab184ec544334a1b83ea8298e6b1b53f | 45 | 39360.00 | 40518.63 | 7997.00 | 37687.00 | 29690.00 | 43 | 35 | 38 | 17 |
| 9fd5da17ae974c70811e40a5b378af20 | 46 | 22604.00 | 22825.20 | 9744.00 | 21173.00 | 11429.00 | 43 | 35 | 38 | 17 |
| 71c6942caaa6433fbfc1fd54bd286a95 | 47 | 13463.00 | 13894.95 | 1235.00 | 12751.00 | 11516.00 | 43 | 35 | 38 | 17 |


Archived count means: visible_node_visits=43.00, focus_nodes=35.00, descendant_metadata_scans=37.70, merged_text_scans=17.30, candidate_count=19.09.



## Live healthy controls and profiler smoke

Three requests each were collected on Korean Menu and Motion Sensor screens. All six result payloads report `success=true`, `detail=moved`; each has one execution-start event and one profile summary. This is a bounded profiler smoke, not a complete scenario verdict. Control setup FOCUS_TARGET returned false on attempted anchors; those results were retained, not reclassified as successful anchors. Actual screens are corroborated by service hierarchy and resulting focus snapshots. Control samples therefore reflect observed current focus rather than a standardized successful anchor reset.

The Home Monitor setup was attempted with bounded navigation but no Home Monitor SMART_NEXT was executed. No extra control scenario was completed.

### Control work per request


| Control | Request ID | Total ms | TREE | VISIBLE | Depth | MD calls/unique | MD visits | Actionable checks | Candidates | Focusable | Interactive calls/unique | Parent calls | Child calls | Refresh |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control_menu | 2635ad4b031142989a8cf43a52c8f83a | 1238.24 | 63 | 51 | 6 | 41/41 | 149 | 87 | 18 | 38 | 524/38 | 13596 | 1847 | 20 |
| control_menu | 43a20c6176334d44946bf415a921b28b | 423.42 | 63 | 51 | 6 | 41/41 | 149 | 87 | 18 | 38 | 524/38 | 13591 | 1897 | 7 |
| control_menu | e3dc3552b5ea4104b43b9961ebf70fc2 | 396.55 | 63 | 51 | 6 | 41/41 | 149 | 87 | 18 | 38 | 524/38 | 13593 | 2074 | 7 |
| control_motion | f768a37dc70744e8be2124845b59aabe | 298.67 | 43 | 41 | 19 | 15/15 | 105 | 86 | 8 | 8 | 46/37 | 2744 | 1014 | 7 |
| control_motion | 3a9246ad67434494bcb86d7755f05b45 | 199.74 | 43 | 41 | 19 | 15/15 | 105 | 86 | 8 | 8 | 46/37 | 2764 | 1180 | 7 |
| control_motion | d663f13ae6804af0bc4c3cf79c075de0 | 178.07 | 43 | 41 | 19 | 15/15 | 105 | 86 | 8 | 8 | 46/37 | 2765 | 1148 | 7 |


TREE/visible/depth cover the nodes encountered by the existing candidate enumeration, which prunes invisible descendants; they are not a separate complete active-window hierarchy walk. Unique identities use the Android node's local source/window hash and are approximate due to possible hash collisions. Descendant visits count actionable-metadata BFS dequeues only, not every label/interactive scan. Android source confirms node.hashCode uses local source/window identity arithmetic, with no extra IPC. Focusable count is the collector's emitted FocusedNode count, not every node with isFocusable=true. Metadata subtrees are unique at the entry roots but their descendants overlap: Menu 149 visits/70 unique visited nodes; Motion 105/41. Interactive/recover-label calls also repeat subtree roots.

### Control stage timings (ms)

Enum-X is recursive enumeration **exclusive**; metadata and candidate build are inclusive; Rank is policy_ranking only. Norm is alias normalization, a separate part of runtime state. Verify is service_verification only, not summed overlapping executor verification regions. Post is the existing immediate focus evidence, not a full post hierarchy. Serialization includes encode plus final chunk log emission. These are diagnostic spans and must not be added into a fake nonoverlapping total.


| Control / request | Root | Enum-X | Metadata | Candidate build | Norm | Rank | Focus action | Event wait | Post | Verify | Serialize+emit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control_menu / 2635ad4b031142989a8cf43a52c8f83a | 7.83 | 11.44 | 6.80 | 47.54 | 313.28 | 5.39 | 71.71 | 572.03 | 1.92 | 3.51 | 1.87 |
| control_menu / 43a20c6176334d44946bf415a921b28b | 5.89 | 11.54 | 19.63 | 50.00 | 219.54 | 3.33 | 5.04 | 75.18 | 2.21 | 3.79 | 1.86 |
| control_menu / e3dc3552b5ea4104b43b9961ebf70fc2 | 6.39 | 6.51 | 18.89 | 42.89 | 192.41 | 4.61 | 6.72 | 75.21 | 2.29 | 2.10 | 1.94 |
| control_motion / f768a37dc70744e8be2124845b59aabe | 13.41 | 4.66 | 5.79 | 46.02 | 30.30 | 6.60 | 30.73 | 75.59 | 1.54 | 1.53 | 1.26 |
| control_motion / 3a9246ad67434494bcb86d7755f05b45 | 5.39 | 2.19 | 2.86 | 17.30 | 25.22 | 3.60 | 10.98 | 75.14 | 2.11 | 4.63 | 2.89 |
| control_motion / d663f13ae6804af0bc4c3cf79c075de0 | 7.04 | 2.36 | 3.88 | 19.39 | 28.58 | 4.75 | 6.77 | 75.14 | 2.15 | 4.65 | 1.06 |


| Control | n | Avg total ms | p50 | Max | Avg runtime-state ms | Avg normalization ms | Avg parent API ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control_menu | 3.00 | 686.07 | 423.42 | 1238.24 | 293.25 | 241.75 | 47.11 |
| control_motion | 3.00 | 225.49 | 199.74 | 298.67 | 74.68 | 28.03 | 20.45 |


Menu repeats interactive descendant scans 524 times over 38 unique roots and performs about 13,593 parent API calls per request, yet averages 686.07 ms total; Motion averages 225.49 ms. Repeated work is concretely present in controls, but its existence/count alone does not explain Family Care's 30–60 seconds. Candidate counts are comparable in magnitude (archive Family 17–24, Menu 18, Motion 8), which weakens a candidate-count-only explanation. The archive's visible visit count cannot be treated as a complete unique hierarchy-size ratio.

**FAMILY_CARE_TREE_SIZE_RATIO=UNMEASURED**, **FAMILY_CARE_DESCENDANT_SCAN_RATIO=UNPROVEN_WITH_EQUIVALENT_INSTRUMENTATION**, **FAMILY_CARE_HOT_STAGE_RATIO=UNMEASURED**. Family Care lacks matching new stage/work counters. Do not calculate a claimed deep hot-function ratio from different timer boundaries, different focus states, or crossdate snapshots. The control timing contrasts are descriptive only.

## Algorithm inspection and smallest candidate regions

| Function / region | Concrete work | Evidence status |
| --- | --- | --- |
| A11yNavigator.collectSmartNextRuntimeState | collect inputs, normalize alias groups, find focus, resolve indexes, history/state assembly | Proven coarse dominant region: 28.64 seconds average. |
| A11yNavigator.normalizeNodes / selectAliasGroupRepresentative | For each candidate, searches existing groups; repeatedly recomputes the group representative and settings/wrapper checks. Representative selection can repeat parent context and descendant scans. | Strong source hypothesis for the 21.71-second remainder; no new Family Care timer to prove individual dominance. |
| A11yNavigator.nearestMenuLikeContainer / row and wrapper ancestor lookups | Repeated walks over at most six ancestors in menu context checks; other ancestor checks can walk deeper. | Repeated parent access measured in controls; Family latency/cost per call unknown. |
| A11yTraversalAnalyzer.collectFocusNodes / collectDescendantActionableMetadata / countClickableOrFocusableDescendants | Candidate enumeration and overlapping per-candidate subtree scans; interactive descendant checks can recur for the same source/window node. | Coarse collector proven at 6.93 seconds average; metadata versus IPC versus other filtering not separated for Family. |
| AccessibilityNodeInfo getParent/getChild/refresh/findFocus | Local cache hits and potentially remote service calls. Repeated counts may become expensive if cache/remote view state differs. | Healthy controls show API calls are usually cheap there; slow Family IPC is unproven. |
| A11yTraversalAnalyzer.sortNodesSpatially | Existing IdentityHashMap caches TraversalSortKey per FocusedNode within sorting. | Already cached; do not propose a redundant new sort-key cache. |
| A11yFocusExecutor event polling and verification | Existing bounded waits and retries; API calls inside waits could themselves stall. | No Family deep measurement to exclude this entirely; controls are fast. Runtime-state coarse timing points first to earlier state construction. |

Overall empirical complexity is **UNKNOWN**. Source alias-group search admits at least a quadratic candidate-pair comparison component when groups are singletons, with additional ancestor/subtree work; growing groups may make representative rescanning worse. A six-ancestor check is bounded, while other descendant/ancestor paths vary with structure. These source bounds are not an observed O(N²) growth curve for total SMART_NEXT. A moderate sampled visit count does not prove the entire hierarchy is moderate. Primary performance class is **UNPROVEN (B/C/E remain plausible)**; A alone and D dominance are not established either.

REPEATED_SUBTREE_WORK_PRESENT=YES_IN_CONTROLS; FAMILY_CARE_DEEP_COUNT_UNMEASURED.

## Optimization and semantic safety

OPTIMIZATION_IMPLEMENTED=NO. No memoization, node skipping, eligibility change, focus verification weakening, timeout increase, max_steps change, repeat_no_progress change, or concurrent focus actions were added. The pre-existing lazy metadata experiment remains recorded and unaccepted. The opt-in profiler adds measurement overhead and is not a production performance improvement.

SEMANTIC_DIFF=NOT_APPLICABLE_NO_NEW_OPTIMIZATION. Existing fixture/transport tests pass and the six controls moved successfully, but this is not the requested same-state before/after candidate-set/order/focus/terminal equivalence proof for an optimization. No after-fix Family Care performance distribution or >=30% hot-stage reduction can be claimed. The profiler itself has not been run on a fresh slow WAITING request; its overhead on that path remains unquantified.

## Device, lifecycle, build, and tests

Device: SM-F741N / R3CX40QFDBP. Service-preserving hierarchy only; no suppressing UIAutomation/XML acquisition was introduced.

Original installed APK was retained at family_care_hotpath_20261010/pre_profile_installed.apk, SHA256 D91CB392DA1A2FCE99AD6A38EFFD5C7DE16FE193A6264A8AE2E6EA561353AE75.

The instrumentation build was installed with adb install -r. Artifact and installed base.apk SHA256 both equal DE00BAAFD161A21F7A5C4B0D81B8E75C43235B8AB696F7EA4AD6D03EE0F34A9F. The instrumentation APK remains installed; profiling is disabled unless the opt-in extra is supplied. Installation intentionally changed Helper PID 27068 -> 28475; TalkBack remained 17467. That one deployment restart is separate from request-runtime stability. Both live control sets start/end with TalkBack=17467, Helper=28475; final readback confirms those PIDs.

Live runtime PID change counts below exclude the intentional APK installation. Fresh log audit uses each capture's UTC start/end mapped to device Asia/Seoul threadtime. Historical buffered log lines are excluded. Only captured A11Y_HELPER/AndroidRuntime/ActivityManager/WindowManager logs are audited; no claim is made about unobserved time or a long lifecycle stress run. Transient read-only hierarchy captures during navigation failed closed with child_unavailable / NO_ACTIVE_WINDOW; no runtime workaround was introduced.


| Control | Fresh lines | Fatal/ANR candidate lines | Timeouts | Duplicate executions | TalkBack PID changes | Helper PID changes |
| --- | --- | --- | --- | --- | --- | --- |
| control_menu | 7783 | 0 | 0 | 0 | 0 | 0 |
| control_motion | 1369 | 0 | 0 | 0 | 0 | 0 |


Archive Family 47-request correlation reports timeout=0, duplicate executions=0. No new Family Care runtime validation exists. No fresh captured control window fatal / BadToken / ANR marker was found (see final_audit.json); this is a bounded observation, not a Family Care lifecycle acceptance verdict.

- Helper unit tests: 390 tests, 0 failures, 0 errors, 0 skipped. Gradle :app:testDebugUnitTest :app:assembleDebug --offline --no-daemon: BUILD SUCCESSFUL. Log: instrument_build.log. Kotlin daemon connection warnings fell back to compilation; the final successful build is the result.
- Python transport/candidate/focus targeted tests: 92 passed, log python_targeted.log.
- Python full suite: 3159 passed, 1 skipped in 97.33 seconds, log python_full_suite.log.

## Remaining limitation and next action

The actionable measurement gap is fresh **WAITING** Family Care per-request spans and node/API work counts. Once the same profile is naturally WAITING or the user supplies another confirmed WAITING profile, capture a service hierarchy preflight and collect >=10 opt-in SMART_NEXT requests with the existing 75-second timeout and no retries. Include naturally occurring fast/medium/slow requests; do not force ACTIVE or alter termination. Compare exclusive costs and API call cost with the two controls. Optimize one function only if it accounts for the majority of latency, then prove same-state fixture equivalence and >=10 after-fix WAITING samples before publication.

Until then the result remains SMART_NEXT_HOT_PATH_NOT_PROVEN. No commit/push/merge is authorized by a passing performance gate in this task, and none was performed. All prior changes, added diagnostic code, and artifacts remain locally available for the next WAITING measurement.

## ACTIVE follow-up — 2026-10-10

### Updated verdict

**OVERALL_VERDICT=HOT_FUNCTION_PROVEN** for the measured ACTIVE request set: the concrete Android node-access functions **AccessibilityNodeInfo.getChild** and **AccessibilityNodeInfo.getParent** collectively dominate wall time. This does not prove a remote Binder transaction or a particular per-subtree memoization fix is safe. **OPTIMIZATION_IMPLEMENTED=NO**. Prior WAITING-only conclusion remains historical; the internal WAITING functions remain unresolved because that archive lacks these deep counters.

Fresh profile: exactly **10 ACTIVE SMART_NEXT requests**, no full scenario or extra control requests. Nine moved successfully; request 10 returned **failed_single_target**. It is included in timing statistics and preserved, not retried or reclassified as a transport timeout. Collection stopped at that result. No before/after optimization PASS or production publication is claimed.

Source branch and HEAD/origin/main remain fix/family-care-smart-next-latency / cd5e8048a7cf0d795c2bddcec46ab7047d26fcdb. Existing production instrumentation and experiment were preserved without code changes in this follow-up. New files are bounded capture/analysis scripts and artifacts under family_care_active_hotpath_20261010/, plus this documentation update. Source snapshot: start_git_status.txt and start_diff_stat.txt.

### State and installed instrumentation

Start verified ACTIVE (`지금 활동 중`) immediately before request 1. Foreground: topResumedActivity=ActivityRecord{f61d43f u0 com.samsung.android.oneconnect/com.samsung.android.plugin.care.MainActivity t1331}. Active window metadata/root identity and focus are in before_state.json; raw service hierarchy in before_hierarchy.json. Active application window is id 25111, type 1, active/focused true; root package com.samsung.android.oneconnect, class android.widget.FrameLayout, no resource ID. Viewport SHA256: 37862bfa6c03243089fbd36beee52fda58ff331bae883140ce76f3c33079d575.

Start/end state are ACTIVE; the sampled visible viewport signature remains unchanged (37862bfa6c03243089fbd36beee52fda58ff331bae883140ce76f3c33079d575). The changing focus is captured in each request evidence. This identifies the sampled viewport; it does not imply a complete ACTIVE scenario or all viewports were exercised. No WAITING state forcing/navigation was attempted, and no application navigation was needed before profiling.

The already-installed opt-in instrumentation was used with profileSmartNext=true, distinct request IDs, the existing serial worker and 75-second result wait, no action retries. No new APK install or production-code edit was required. T0–T12 marker meanings, inclusive/exclusive nesting, tree/counter limitations, and result boundary definitions from the earlier timing-model section still apply.

### ACTIVE timings

All-row distribution includes the failed tenth request. p95 is nearest-rank: with ten observations it equals the maximum. API total uses ACTION_EXECUTION_STARTED to ACTION_API_RESULT, matching the archive's Helper event boundary. Profile total uses the existing worker/callback profile boundary. Do not use the difference between ACTIVE and WAITING as a measured optimization reduction.


| Stage / ms | n | Average | p50 | p95 | Max | r with profile total |
| --- | --- | --- | --- | --- | --- | --- |
| total_ms | 10 | 7494.44 | 4128.57 | 35502.93 | 35502.93 | N/A |
| api_total_ms | 10 | 7470.20 | 4106.50 | 35482 | 35482 | N/A |
| runtime_state | 10 | 6202.93 | 2920.44 | 33698.81 | 33698.81 | 1.00 |
| normalize_aliases | 10 | 3146.12 | 1396.43 | 18194.69 | 18194.69 | 0.99 |
| descendant_metadata | 10 | 455.42 | 294.73 | 2094.30 | 2094.30 | 0.98 |
| candidate_build | 10 | 1932.01 | 895.34 | 10664.61 | 10664.61 | 0.99 |
| event_wait | 10 | 86.40 | 0.00 | 531.52 | 531.52 | 0.85 |
| post_state | 10 | 7.33 | 5.90 | 17.76 | 17.76 | -0.32 |


Sensitivity: excluding the first request (descriptive warm subset, not proof of a cache mechanism) total distribution is {"n": 9, "avg": 4382.380773777778, "p50": 3890.301873, "p95": 7314.912549, "max": 7314.912549}.


| Stage | r all 10 | r moved 9 | r excluding first 9 |
| --- | --- | --- | --- |
| runtime_state | 1.00 | 1.00 | 0.77 |
| normalize_aliases | 0.99 | 0.99 | 0.45 |
| descendant_metadata | 0.98 | 0.98 | 0.45 |
| candidate_build | 0.99 | 1.00 | 0.49 |
| event_wait | 0.85 | 0.99 | 0.32 |
| post_state | -0.32 | -0.36 | 0.06 |


The all-row correlations are strongly influenced by the first 35.50-second request. The nine-request sensitivity series is shown to avoid claiming a general growth curve from one tail sample. A zero event_wait span means that measured function was not called; polling/stabilization and API work can still occur in other measured executor spans.

### Per-request ACTIVE stage table

Enum-X uses exclusive recursive enumeration time. Focus lookup is the sum of measured findFocus API calls across the request (not only the initial lookup); current identification/index spans remain separately available in analysis.json. Verification is service_verification, with executor verification spans separately retained. Post state is the existing immediate focus-evidence snapshot, not a new full hierarchy or a complete runtime-state rebuild. Stage rows overlap and are not additive.


| Request ID | Result | Total | Root | Enum-X | Focus lookup | Runtime | normalizeNodes | Metadata | Candidate build | Rank | Action | Event wait | Post | Verify | Serialize+emit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 80b3a68b9a19497fb080750e55fc7757 | moved | 35502.93 | 56.06 | 38.01 | 269.01 | 33698.81 | 18194.69 | 2094.30 | 10664.61 | 53.49 | 71.62 | 531.52 | 3.13 | 9.97 | 3.21 |
| e3b6daae75264e6eaa023d2a376b1a3c | moved | 3475.81 | 15.17 | 19.44 | 55.20 | 2844.50 | 1221.53 | 107.81 | 869.50 | 27.65 | 30.54 | 0 | 4.05 | 4.15 | 1.82 |
| 1e75b1ba592944f4b01f95c3d7f7a304 | moved | 3563.81 | 12.94 | 11.61 | 81.85 | 2675.23 | 1449.24 | 90.87 | 570.14 | 19.96 | 35.15 | 0 | 17.76 | 13.80 | 2.28 |
| 5aa76237d28d4fe28f1ca52df750ceb1 | moved | 4366.84 | 18.77 | 21.08 | 95.60 | 3713.38 | 1898.29 | 401.86 | 1172.54 | 11.13 | 23.92 | 0 | 4.70 | 17.56 | 1.68 |
| 0316fd57cb0a4a4eab36af8741b21421 | moved | 3208.56 | 13.45 | 13.80 | 50.41 | 2361.54 | 838.61 | 183.32 | 921.19 | 6.94 | 40.48 | 0 | 6.13 | 12.50 | 1.77 |
| 8f22e098829e46ecac9f8ae17442aea1 | moved | 3890.30 | 20.05 | 14.41 | 101.57 | 2996.38 | 1343.62 | 233.32 | 755.45 | 128.19 | 34.16 | 0 | 5.67 | 13.83 | 1.41 |
| f82618f48ad7454f8194cab31af0649b | moved | 3320.74 | 17.70 | 22.97 | 78.26 | 2521.56 | 706.02 | 457.00 | 1254.52 | 136.26 | 25.79 | 0 | 8.85 | 5.89 | 3.91 |
| bb091d4aa3644d88894cfd3696aac196 | moved | 7314.91 | 16.27 | 12.05 | 121.30 | 4965.75 | 2020.41 | 396.23 | 1407.40 | 1445.56 | 44.82 | 0 | 11.39 | 8.94 | 5.05 |
| ae9be2325cc24798b368f377220d9b0f | moved | 4780.93 | 12.81 | 18.47 | 52.31 | 3808.88 | 2903.37 | 287.85 | 844.83 | 4.00 | 36.63 | 0 | 8.00 | 8.99 | 3.23 |
| a87eec01dd0749588e1b4ec012e71282 | failed_single_target | 5519.54 | 17.76 | 15.75 | 139.72 | 2443.31 | 885.38 | 301.62 | 859.93 | 1517.32 | 41.88 | 332.50 | 3.64 | 7.06 | 1.69 |


### Per-request work counts


| Request ID | Tree | Visible | Candidates | Focusable | Depth | Parent | Child | Metadata calls/unique | Interactive calls/unique | MD visits | Actionable checks | Refresh |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 80b3a68b9a19497fb080750e55fc7757 | 51 | 46 | 27 | 38 | 6 | 17249 | 645 | 238/40 | 348/38 | 302 | 50 | 20 |
| e3b6daae75264e6eaa023d2a376b1a3c | 51 | 46 | 27 | 38 | 6 | 17389 | 645 | 238/40 | 348/38 | 302 | 50 | 5 |
| 1e75b1ba592944f4b01f95c3d7f7a304 | 51 | 46 | 27 | 38 | 6 | 17243 | 645 | 238/40 | 349/38 | 302 | 50 | 5 |
| 5aa76237d28d4fe28f1ca52df750ceb1 | 51 | 46 | 27 | 38 | 6 | 17249 | 645 | 238/40 | 348/38 | 302 | 50 | 5 |
| 0316fd57cb0a4a4eab36af8741b21421 | 51 | 46 | 27 | 38 | 6 | 17262 | 645 | 238/40 | 349/38 | 302 | 50 | 5 |
| 8f22e098829e46ecac9f8ae17442aea1 | 51 | 46 | 27 | 38 | 6 | 17261 | 652 | 238/40 | 348/38 | 302 | 50 | 5 |
| f82618f48ad7454f8194cab31af0649b | 51 | 46 | 27 | 38 | 6 | 17309 | 655 | 238/40 | 348/38 | 302 | 50 | 5 |
| bb091d4aa3644d88894cfd3696aac196 | 51 | 46 | 27 | 38 | 6 | 17308 | 733 | 238/40 | 349/38 | 302 | 50 | 5 |
| ae9be2325cc24798b368f377220d9b0f | 51 | 46 | 27 | 38 | 6 | 17276 | 738 | 238/40 | 348/38 | 302 | 50 | 5 |
| a87eec01dd0749588e1b4ec012e71282 | 51 | 46 | 27 | 38 | 6 | 17300 | 880 | 238/40 | 347/38 | 302 | 50 | 15 |


### Function breakdown

Summed inclusive duration and call count across the ten requests; average per call is duration/calls. Max individual call is **UNMEASURED**: the existing installed profiler does not retain individual maxima. Max request aggregate is provided explicitly and must not be represented as max call. Recursive/parent inclusive rows overlap; exclusive columns support separate attribution. Full function listing is in analysis.json.


| Function / span | Calls | Total inclusive ms | Avg call ms | Max call | Max request aggregate ms | Total exclusive ms |
| --- | --- | --- | --- | --- | --- | --- |
| runtime_state | 10 | 62029.35 | 6202.93 | UNMEASURED | 33698.81 | 54.22 |
| normalize_aliases | 10 | 31461.16 | 3146.12 | UNMEASURED | 18194.69 | 99.70 |
| alias_representative | 5920 | 13178.91 | 2.23 | UNMEASURED | 6999.67 | 329.78 |
| isOverlayMenuLikeContext | 15090 | 2600.28 | 0.17 | UNMEASURED | 923.00 | 605.34 |
| selectOneConnectSettingsRowRepresentative | 5920 | 9023.05 | 1.52 | UNMEASURED | 5232.07 | 850.48 |
| settings_alias_check | 5650 | 7772.38 | 1.38 | UNMEASURED | 5506.47 | 910.70 |
| wrapper_alias_check | 5650 | 9816.80 | 1.74 | UNMEASURED | 5500.38 | 737.37 |
| candidate_build | 10 | 19320.09 | 1932.01 | UNMEASURED | 10664.61 | 159.36 |
| descendant_metadata | 2380 | 4554.16 | 1.91 | UNMEASURED | 2094.30 | 116.16 |
| interactive_descendants | 3482 | 2133.55 | 0.61 | UNMEASURED | 1313.69 | 90.49 |
| recover_label | 408 | 5445.89 | 13.35 | UNMEASURED | 1738.21 | 47.32 |
| ipc_get_child | 6883 | 40067.29 | 5.82 | UNMEASURED | 15867.65 | 40067.29 |
| ipc_get_parent | 172846 | 25969.54 | 0.15 | UNMEASURED | 17252.46 | 25969.54 |
| ipc_refresh | 75 | 609.65 | 8.13 | UNMEASURED | 171.72 | 609.65 |
| ipc_find_focus | 145 | 1045.22 | 7.21 | UNMEASURED | 269.01 | 1045.22 |
| event_poll | 21 | 1562.49 | 74.40 | UNMEASURED | 635.80 | 26.20 |
| event_wait | 12 | 864.02 | 72.00 | UNMEASURED | 531.52 | 864.02 |
| post_state | 10 | 73.32 | 7.33 | UNMEASURED | 17.76 | 73.32 |


### Dominant node-access cost, without double counting


| Request ID | Parent ms | Child ms | Parent+child ms | % of total | Guaranteed minimum inside runtime % |
| --- | --- | --- | --- | --- | --- |
| 80b3a68b9a19497fb080750e55fc7757 | 17252.46 | 15867.65 | 33120.11 | 93.29 | 92.93 |
| e3b6daae75264e6eaa023d2a376b1a3c | 644.09 | 2155.68 | 2799.77 | 80.55 | 76.23 |
| 1e75b1ba592944f4b01f95c3d7f7a304 | 822.66 | 2034.18 | 2856.84 | 80.16 | 73.57 |
| 5aa76237d28d4fe28f1ca52df750ceb1 | 926.89 | 2708.26 | 3635.16 | 83.24 | 80.30 |
| 0316fd57cb0a4a4eab36af8741b21421 | 560.47 | 2044.03 | 2604.50 | 81.17 | 74.42 |
| 8f22e098829e46ecac9f8ae17442aea1 | 754.29 | 2455.34 | 3209.63 | 82.50 | 77.28 |
| f82618f48ad7454f8194cab31af0649b | 515.33 | 2156.81 | 2672.15 | 80.47 | 74.28 |
| bb091d4aa3644d88894cfd3696aac196 | 1367.28 | 5144.69 | 6511.97 | 89.02 | 83.83 |
| ae9be2325cc24798b368f377220d9b0f | 2435.15 | 1755.18 | 4190.33 | 87.65 | 84.49 |
| a87eec01dd0749588e1b4ec012e71282 | 690.92 | 3745.46 | 4436.38 | 80.38 | 55.67 |


Parent/child wrappers are nonrecursive leaf spans on the same worker. Their summed wall time is 88.11% of all-row profile total. Because summary API counters span the whole request, exact runtime-only API allocation is unavailable. A conservative bound avoids inventing it: **runtime API minimum = max(0, parent+child wall time − (total − runtime time))**. This assigns every millisecond outside runtime to those APIs before attributing the remainder inside runtime. The minimum runtime share across these ten requests is 55.67%. It establishes joint API dominance inside runtime across multiple requests without adding normalizeNodes/metadata parent rows again.

The exact caller allocation of API time is not stored by the current summary format. normalizeNodes is independently measured, but API wall time cannot be split exactly between nearestMenuLikeContainer, row lookup, equality checks, or alias representatives. Therefore the concrete proven hot functions are getChild/getParent; memoizing any single high-level caller as the definitive remedy is not yet proven.

### ACTIVE vs archived WAITING


| Metric | ACTIVE fresh 10 | WAITING archived 47 |
| --- | --- | --- |
| Worker/callback profile total avg ms | 7494.44 | UNMEASURED |
| Same-boundary Helper API total avg ms | 7470.20 | 33348.51 |
| Same-boundary Helper API total p95 ms | 35482 | 55087 |
| Runtime-state avg ms | 6202.93 | 28642.70 |
| Collector/candidate build avg ms | 1932.01 | 6931.15 |
| Tree enumerated unique nodes avg | 51 | UNMEASURED |
| Normalized candidates avg | 27 | 19.09 |
| Runtime correlation r with matched API total | 1.00 | 0.98 |


**ACTIVE_VS_WAITING_CLASSIFICATION=FAMILY_CARE_COMMON_BOTTLENECK**, restricted to the common **runtime-state region**: both states exhibit dominant work there, and ACTIVE includes a 35.50-second request. Persistent 30–60-second latency is not shown for all ACTIVE requests. The duration distribution differs greatly, and the archive lacks deep API timings, so a common getChild/getParent cause in WAITING is **not proven**. Fresh ACTIVE and archived WAITING differ in sample size, profile start/history, source instrumentation overhead, cache state, and date. No claim of WAITING-only/ACTIVE-only causality or fair state-controlled performance delta is justified. State labels alone do not isolate cache/network/UI-thread effects.

### Healthy controls reused

No extra control device request was executed. These are the existing opt-in instrumentation samples from the same local Helper build, with the previously documented current-focus setup limitations.


| Profile | n | Avg total ms | Avg runtime ms | Tree | Candidates | Parent calls | Child calls | Parent wall ms | Child wall ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ACTIVE | 10 | 7494.44 | 6202.93 | 51 | 27 | 17284.60 | 688.30 | 2596.95 | 4006.73 |
| control_menu | 3 | 686.07 | 293.25 | 63 | 18 | 13593.33 | 1939.33 | 47.11 | 17.80 |
| control_motion | 3 | 225.49 | 74.68 | 43 | 8 | 2757.67 | 1114 | 20.45 | 10.14 |


A much larger enumerated hierarchy is not the observed explanation: ACTIVE has 51 encountered nodes versus Menu 63 and Motion 43. ACTIVE's parent count is higher than controls but only modestly higher than Menu; its child access count is lower than both controls. Large ACTIVE wall time per access rather than call count alone is the distinguishing measured fact. API wrappers can return cache hits, prefetch, perform platform computation, wait on locks, or transact remotely. Thus wall timing proves **ACCESSIBILITY_API_DOMINATED** behavior, but **PERFORMANCE_CLASS=UNPROVEN** for the requested pure compute versus remote IPC distinction. No thread CPU/Binder trace was captured.

### Repeated work, complexity, and safe next fix

Repeated metadata/interactive scan roots are proven by call-minus-unique counts in analysis.json. These counts use Android local source/window hashes and retain the prior hash-collision caveat. MAX_REPEAT_COUNT_PER_SUBTREE is **UNMEASURED** because existing instrumentation stores sets, not frequency maps. A lower bound is ceil(calls/unique roots); it is not the maximum observed repeat count. DUPLICATE_PARENT_LOOKUPS is **UNMEASURED** by source identity: parent calls are counted but individual parent-access source IDs are not retained. DUPLICATE_DESCENDANT_SCANS reports metadata and interactive excess calls over unique roots separately, not a sum of overlapping nested categories.

Source inspection still confirms a quadratic candidate-pair comparison component in normalizeNodes when candidates form singleton groups; representative rescans and ancestor walks add work. **LIKELY_COMPLEXITY=UNKNOWN** for empirical full SMART_NEXT scaling. **PROVEN_QUADRATIC_REGION=normalizeNodes candidate-versus-existing-groups comparison (source structure only)**. Fixed node counts with large latency variation do not demonstrate quadratic latency growth.

Recommended optimization, not implemented: first isolate expensive repeated node-access calls by caller and source/window identity, then consider memoizing parent/container resolution only within a verified immutable request snapshot. Parent lookups can change as accessibility cache/window state changes; request-level caching of live AccessibilityNodeInfo without proving the snapshot boundary is not obviously semantics-preserving. Metadata memoization alone is not shown to explain most latency. Any later fix must preserve candidate set/order/eligibility/target/terminal classification, preserve focus verification and timeouts, and receive same-state before/after samples. RCA-only is the safe result of this task; the failed tenth navigation result must also be considered before an optimization can be accepted.

CPU_COMPUTE_MS=UNMEASURED (no CPU clock). ACCESSIBILITY_API_MS is the sum of nonoverlapping leaf API wrapper/root/action wall spans, including diagnostic counter/marker overhead. UNKNOWN_MS is total minus that measured sum; it includes pure computation, unwrapped property/API operations, logging/serialization and scheduling, and is **not** a CPU time estimate.


| Metric | Mean per request ms |
| --- | --- |
| Measured wrapped API wall | 6827.77 |
| Unknown/non-API wall residual | 666.67 |


### Validation, safety, and publication

Requests: 10, moved: 9, failed_single_target: 1, transport retries: 0, duplicate execution events: 0. Start/end TalkBack PID 17467 and Helper PID 28475 are stable in every stored request. Fresh bounded log audit (device Asia/Seoul timestamp interval, excluding historical buffered lines) found 0 fatal/BadToken/window/ANR candidate lines. This is a bounded profile result, not a complete scenario acceptance result.

Helper :app:testDebugUnitTest --offline --no-daemon: BUILD SUCCESSFUL; XML totals {'tests': 390, 'failures': 0, 'errors': 0, 'skipped': 0}. Focused Python SMART_NEXT transport, metadata fixture, focus reconciliation: 41 passed (python_targeted.log). Full Python run result is recorded in python_full_suite.log and the final report. No test suite regression has been accepted.

Artifacts: family_care_active_hotpath_20261010/{before_hierarchy.json,before_state.json,after_hierarchy.json,after_state.json,start.json,end.json,requests.json,logcat.txt,analysis.json}; profile_console.log preserves the exact failed tenth response. Installed profiler remains opt-in. No optimization, semantic-equivalence claim, post-fix profile, >=30% reduction claim, commit, push, or merge. Full32=NO; WAITING reproduction attempted=NO; coverage32 gate=NO; termination/camera/English/Phase4 changes=NO.

NEXT_STEP: caller/source-aware node-access profiling and a snapshot-safe cache design; validate same-state candidate semantics before any implementation/publication. Do not infer a safe fix from the API dominance alone.

## Parent/child relationship cache follow-up — 2026-10-10

### Decision and limits

**OVERALL_VERDICT=PARENT_CHILD_CACHE_FIX_PASS_WITH_LIMITATIONS**. **SEMANTIC_DIFF=NONE** in the offline same-graph / same-resolver-history oracle. Runtime-state average fell from 11446.46 to 1260.80 ms (**88.99%**); full profiled request average fell **47.48%**. Before results were **9 moved, 1 failed_single_target (request 5)**; after results were **10 moved**. The prior ACTIVE set's separate request-10 failure is historical. No failure was retried or counted as a successful move.

Limitations: Family Care still averages 9189.80 ms versus historical Menu 686.07 ms and Motion 225.49 ms controls. Controls were not rerun. This is a ten-request ACTIVE comparison, not full scenario/coverage or WAITING acceptance. One pre-action service hierarchy read lost its terminal marker; the read-only preflight was repeated once, with both attempts preserved. SMART_NEXT timeout count remains zero. This cache is inactive in hierarchy serialization; no transport fix was added. Device sequences have different outcomes and existing resolver history; timing comparisons are observational, while the actual lookup reduction and offline identical-input oracle directly test the optimization. No native immutable-snapshot contract or Binder trace was obtained.

### Source safety and evidence

START_HEAD=ORIGIN_MAIN=cd5e8048a7cf0d795c2bddcec46ab7047d26fcdb; WORK_BRANCH=fix/family-care-smart-next-latency. Existing uncommitted instrumentation and the lazy descendant-metadata experiment were preserved. The latter is covered by the eager/lazy metadata oracle and unchanged across this task's before/after APKs. Only one new optimization was applied: collection-scoped relationship lookup memoization. max_steps, repeat_no_progress, eligibility, termination, timeouts, concurrency, focus verification, scenario logic, camera, English and Phase 4 were unchanged.

Artifacts remain local under `family_care_relationship_rca_20261010/`: before/after requests.json, service snapshots, logcat, caller binaries, relationship_analysis.json, comparison.json, source checkpoints/diffs, builds and test logs. Original QA artifacts and out/tests/out were preserved. Generated QA artifacts are excluded from publication. The committed fixture copies contain selected node fields and a redacted device display name; raw captured snapshots remain local.

Before attribution APK SHA-256 E244F33FEC49CD9B8F0ABE583595DFF4933E0C2F16836B38DE3DCDD09A0D6752. After cache APK SHA-256 817995CBD09DDE5B3A702B2C521699FC394791A01235767BB8FF124EA628E14D. Installed hashes match. Intentional installs changed Helper PID 28475→8653→12034, outside measured request windows. TalkBack stayed 17467. Each measured window has zero unexpected Helper/TalkBack PID changes.

### Caller instrumentation and snapshot identity

Opt-in `profileSmartNext=true` plus `profileRelationships=true` records each worker-thread application getParent/getChild call with request ID, snapshot ordinal, exact logical node key (Android source/window equals, not hash alone), operation, child index, direct static semantic caller, phase and API-only nanoseconds. API timing excludes identity assignment and binary append. The binary header retains all caller/phase/snapshot identities; records are 49 bytes. No full stacks or extra diagnostic relationship walks were added. Result callback/total timing ends before binary export. API counters and binaries count actual Android reads; logical cache hits have separate counters. Main-thread asynchronous event reads and Android internal/framework lookups are outside this worker trace boundary.

SNAPSHOT_SCOPE_DEFINITION: new ordinal at root acquisition, runtime-state collection, post-state/service verification, original root access, refresh/action, or an observed structural-event epoch change. Epoch increments for window content/windows/state changes and scroll events. Uniqueness is `(request, snapshot, node)` for parent and `(request, snapshot, node, childIndex)` for child. It never pools requests or snapshots. The before traces observed no generation change within a read and **0 different returned relationships for any repeated same-snapshot key**. Dominant repeats occur inside the same runtime-state normalization collection; post-action/root boundaries are separate. **SAME_SNAPSHOT_REPETITION_CLASS=SAME_SNAPSHOT_REPETITION_DOMINANT**.

### Exact before duplication totals

| Operation | Actual calls | Unique scoped lookups | Duplicate scoped lookups | Duplication % | Max repeat per key | API wall ms | Duplicate API wall ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| parent | 173024 | 599 | 172425 | 99.654 | 3047 | 58709.815 | 56254.428 |
| child | 7713 | 2224 | 5489 | 71.166 | 41 | 98678.040 | 63247.342 |

### Direct callers, sorted by API wall time


**parent**

| Caller | Calls | Caller-local unique | Caller-local duplicates | API ms | Average ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| A11yNavigator.findOneConnectSettingsRowContainer | 73870 | 460 | 73410 | 34257.878 | 0.464 | 53.171 |
| A11yTraversalAnalyzer.shouldTreatAsAliasWrapperDuplicate.parentOf | 59730 | 460 | 59270 | 10462.697 | 0.175 | 52.098 |
| A11yNavigator.nearestMenuLikeContainer | 32866 | 420 | 32446 | 5700.494 | 0.173 | 58.670 |
| A11yTraversalAnalyzer.resolveRootBounds | 3522 | 522 | 3000 | 4003.654 | 1.137 | 45.749 |
| A11yNodeUtils.isFixedSystemUI.parentOf | 137 | 137 | 0 | 1173.867 | 8.568 | 44.812 |
| A11yTraversalAnalyzer.keyOf.parentOf | 2130 | 460 | 1670 | 926.121 | 0.435 | 42.497 |
| A11yNavigator.findOneConnectNotificationsRowContainer | 77 | 77 | 0 | 587.444 | 7.629 | 43.449 |
| A11yNavigator.isNodeInsideAncestor | 272 | 168 | 104 | 512.475 | 1.884 | 43.000 |
| A11yNavigator.resolveCurrentTraversalNode.parentOf | 112 | 56 | 56 | 365.637 | 3.265 | 41.783 |
| A11yNavigator.findScrollableForwardAncestorCandidate.parentOf | 20 | 20 | 0 | 327.367 | 16.368 | 41.741 |
| A11yTraversalAnalyzer.canTreatAsActionControlWrapperDuplicate.parentOf | 190 | 190 | 0 | 143.829 | 0.757 | 33.252 |
| A11yPostScrollScanner.tryFocusCandidate | 18 | 18 | 0 | 119.605 | 6.645 | 42.398 |
| A11yNavigator.findOverlayRepeatSalvageIndex | 50 | 50 | 0 | 95.313 | 1.906 | 40.674 |
| A11yNavigator.findOverlayRowContainer | 30 | 30 | 0 | 33.436 | 1.115 | 32.780 |

**child**

| Caller | Calls | Caller-local unique | Caller-local duplicates | API ms | Average ms | Max ms |
| --- | --- | --- | --- | --- | --- | --- |
| A11yNodeUtils.findBestScrollableContainer | 1080 | 1080 | 0 | 23541.130 | 21.797 | 77.283 |
| A11yTraversalAnalyzer.collectDescendantReadableText | 1810 | 380 | 1430 | 23313.393 | 12.880 | 75.485 |
| A11yNavigator.findDescendantByViewId | 858 | 429 | 429 | 18235.531 | 21.254 | 50.655 |
| A11yNavigator.findMainScrollContainer | 1080 | 1080 | 0 | 16991.648 | 15.733 | 47.747 |
| A11yTraversalAnalyzer.hasDistinctInteractiveDescendant | 610 | 190 | 420 | 4754.579 | 7.794 | 47.314 |
| A11yTraversalAnalyzer.collectActionableDescendantMetadata.childAt | 640 | 460 | 180 | 4586.393 | 7.166 | 45.874 |
| A11yTraversalAnalyzer.countClickableOrFocusableDescendants | 635 | 195 | 440 | 3925.175 | 6.181 | 44.873 |
| A11yTraversalAnalyzer.collectFocusableNodes | 500 | 500 | 0 | 1700.428 | 3.401 | 44.283 |
| A11yTraversalAnalyzer.projectNestedAdjustableDescendants | 290 | 290 | 0 | 1005.849 | 3.468 | 43.434 |
| A11yTraversalAnalyzer.countDirectInteractiveChildren | 195 | 195 | 0 | 623.832 | 3.199 | 42.814 |
| A11yModels.fromNode | 15 | 15 | 0 | 0.082 | 0.005 | 0.012 |


Caller-local duplicates use each caller's own scoped first touch. Duplicate **time** in the analysis JSON instead uses global first touch across callers; these are distinct quantities. Before parent+child Android API wall = **157387.86 ms**, of which same-snapshot duplicate wall = **119501.77 ms**, remaining first-touch wall = **37886.09 ms**. Profiled total wall sum = **174966.79 ms**. Non-parent/child residual = **17578.93 ms** and includes other APIs, event waiting, computation and diagnostics; PURE_COMPUTE_TIME_MS=UNMEASURED. API wall includes Android local accessibility cache and possible IPC; remote Binder time was not separately measured. **PRIMARY_CAUSE=EXCESSIVE_REPEAT_LOOKUPS**, with additional accessibility-API first-touch cost observed, intrinsic IPC cause unproven.

Hot caller 1, `A11yNavigator.findOneConnectSettingsRowContainer`, repeatedly walks ancestors during pairwise alias/row normalization. Stable parent relationships are reread across those comparisons. Hot caller 2, `A11yNodeUtils.findBestScrollableContainer`, performs a full breadth-first walk once per collection; its caller-local child duplicates are zero, but it revisits edges already read by candidate/other scans. Hot caller 3, `A11yTraversalAnalyzer.collectDescendantReadableText`, scans overlapping subtrees while recovering merged/readable labels. Only the parent/child relationship lookup is cached; all three algorithms, node metadata consumers and candidate/row predicates are unchanged.

### Cache design and lifecycle

`SnapshotRelationshipAccess.collect` creates fresh parent and child maps only inside `collectSmartNextRuntimeState`, on its existing collecting worker. Key equality is Android source/window identity, with child index included for children. Positive and null relationships are cached. No cross-request/global relationship map or derived descendant-result cache was added. No action, post-action or verification scope reuses these maps. Maps are cleared in finally, including exception paths.

Each new collection/root, original refresh/action, or observed structural generation change invalidates both maps. A generation change during a miss prevents installation; a change during copy-on-hit forces an actual reread. Android nodes are private copies on store, and every hit returns a fresh caller-owned `AccessibilityNodeInfo.obtain` copy. This preserves the original object-identity behavior used by IdentityHashMap candidate algorithms. References remain only for this collection; no caller-owned node is explicitly recycled or retained across collections. Cache lifetime is bounded by the same recorded snapshot/generation. It relies on delivered structural events; it is not a frozen Android-native graph guarantee.

### Offline semantic proof and test results

The original ACTIVE capture, its redacted committed equivalent and the Menu fixture are reconstructed as sealed SDK-34 node graphs in Robolectric. Production `collectSmartNextRuntimeState`, `decideNextAction` and execution policy are invoked with cache disabled/enabled against the same graph, explicit current-focus cases (null and every normalized candidate), and identical saved resolver signature/history. Full runtime-state equality covers candidate metadata/order, ancestor/alias relations, descendant metadata, current/fallback/next indexes, screen/end and eligibility inputs; target decision and execution-policy/result-classification inputs are equal. Existing eager/lazy metadata tests also pass. This proves the covered offline inputs, not every possible future device state or actual action outcome; actual moved/focus evidence is checked separately on device.

14 new cache tests cover positive/null parent and indexed child hits, structural epoch changes, new-root invalidation, independent collections/requests, change during miss/copy, hash collisions, cleanup on exception, caller-owned copies, refresh/action boundaries and ACTIVE/Menu differential semantics. Earlier fixture setup failures (unsealed findFocus and un-restored resolver history) were fixed in the tests, with failed logs preserved. No production semantics were adjusted to make the oracle pass.

Helper: **404 passed, 0 failures/errors/skipped**. APK debug build: PASS. Python full suite: **3159 passed, 1 skipped** (python_full_suite.log). Existing dispatcher single-worker/correlation behavior remains covered. **SEMANTIC_DIFF=NONE**.

### Matched-instrumentation ACTIVE before / after

Both measurement windows and end captures remain ACTIVE (`지금 활동 중`) in care.MainActivity. Service-owned viewport signature matches `37862bfa6c03243089fbd36beee52fda58ff331bae883140ce76f3c33079d575`. After install, one exact resource-ID FOCUS_TARGET restored the original `device_info` start focus at [468,1368][510,1410]; successful result and subsequent service focused-node capture were both required. Setup is outside the SMART_NEXT profile. Exactly ten distinct SMART_NEXT commands per arm; no retries, full scenario, forced ACTIVE/WAITING, extra control or Full32.

| Metric | Before (10) | After (10) |
| --- | --- | --- |
| Mean total ms | 17496.679 | 9189.797 |
| p95 total ms | 37410.469 | 12326.054 |
| Mean runtime-state ms | 11446.456 | 1260.804 |
| Actual parent API calls | 173024 | 1121 |
| Actual child API calls | 7713 | 3284 |
| Candidate count each request | [27, 27, 27, 27, 27, 27, 27, 27, 27, 27] | [27, 27, 27, 27, 27, 27, 27, 27, 27, 27] |
| Results | ['moved', 'moved', 'moved', 'moved', 'failed_single_target', 'moved', 'moved', 'moved', 'moved', 'moved'] | ['moved', 'moved', 'moved', 'moved', 'moved', 'moved', 'moved', 'moved', 'moved', 'moved'] |

p95 uses nearest rank (for n=10, maximum). Parent cache hits/misses = 171851/460; ratio **99.7330%**. Child hits/misses = 4320/1080; ratio **80.0000%**. Descendant cache = NOT_IMPLEMENTED / N/A. Total actual reads include uncached reads outside runtime collection, so cache misses are not total API calls. Actual parent/child call reductions = 99.35% / 57.42%; scoped duplicate reductions = 99.69% / 80.12%. No coverage was removed to obtain these gains.

### Targeted safety and publication gate

Across both windows: SMART_NEXT timeout=0, duplicate action=0 (unique execution event IDs per request), TalkBack PID change=0, unexpected Helper PID change=0. Timestamp-bounded filtered logcat contains no FATAL EXCEPTION, fatal signal, BadTokenException, window-count fatal or ANR record. Before 9/10 successful moves, after 10/10; all candidate counts stay 27. One hierarchy preflight transport-marker failure is explicitly retained as a limitation, not counted as a SMART_NEXT timeout or hidden. No lifecycle architecture or transport changes were made.

Publication gate is PASS_WITH_LIMITATIONS based on identical covered semantic inputs, proven same-snapshot repetition, material call/runtime reductions and clean targeted action/lifecycle gates. Publish only intended Helper code, Helper tests, curated fixtures and this document. Exclude generated binaries/APKs/logs and all unrelated untracked RCA files. Publication verification is recorded separately in local publish artifacts and the final report to avoid a self-referential commit hash.

FULL32_RUN=NO; COVERAGE_GATE_32_USED=NO; TERMINATION_CHANGED=NO; CAMERA_CHANGED=NO; ENGLISH_RUN=NO; PHASE4_CHANGED=NO. NEXT_STEP: separately authorize broader scenario/WAITING acceptance if needed; this task stops after publication verification.
