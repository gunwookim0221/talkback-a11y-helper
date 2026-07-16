# Phase 10.2.2A WebView Anchor Evidence Recovery

## 1. Problem Summary

`life_home_care_plugin`과 `life_clothing_care_plugin`은 Life 카드 탐색, 카드 탭, 화면 전환까지 성공하지만 post-entry WebView root의 text/name이 비어 있었다. 기존 anchor 검증은 named anchor를 두 번 확인하지 못해 `insufficient_new_screen_evidence`로 순회 전에 중단했다. 이번 변경은 anchor threshold를 낮추지 않고, 같은 entry action에 귀속된 복수의 독립 evidence가 모두 확인될 때만 empty-name WebView landing을 인정한다.

## 2. Artifact Evidence

RCA artifact와 변경 전 targeted 재현에서 관찰한 경로는 다음과 같다.

| Case | Pre-entry candidate / tap | Post-entry root | Child or fallback identity | Correlation | Previous reject | Strong evidence after fix |
|---|---|---|---|---|---|---|
| Home Care EN | `Home Care`, bounds `42,1858,1038,2316`; transition confirmed | `android.webkit.WebView`, `com.samsung.android.oneconnect`, empty text/description, bounds `0,94,1080,2496` | stable `Home Care Home Care` | scenario-scoped correlation ID and confirmed transition | `insufficient_new_screen_evidence` | correlated focused WebView root + stable configured child + changed surface |
| Home Care KO | `홈 케어`, same card region; transition confirmed | same class/package, empty identity, stable full-screen bounds | stable `홈 케어 홈 케어` | same contract | same | same bundle with Korean configured identity |
| Clothing Care EN | `Clothing Care`, bounds `42,978,1038,1710`; transition confirmed | same class/package, empty identity, stable full-screen bounds | stable `Clothing Care Clothing Care` | same contract | same | same bundle with Clothing Care identity |
| Clothing Care KO | `클로딩 케어`, same card region; transition confirmed | same class/package, empty identity, stable full-screen bounds | stable `클로딩 케어 클로딩 케어` | same contract | same | same bundle with Korean configured identity |

The helper `FOCUS_RESULT` contains the WebView root before its truncated children. `DUMP_TREE` exposes the meaningful child nodes but not the WebView container. Therefore neither source is sufficient alone; the fix combines root-only focus metadata with stable dump-tree identity.

## 3. Previous Parser Fix와 차이

Phase 9.5.1 handled a truncated response whose complete named root fields could be trusted as the focus node. Here the root fields are complete enough to identify class/package/bounds/focus state, but root text, description, and resource ID are empty. The parser trust rule still rejects that payload as a standalone focus result. Phase 10.2.2A only preserves the root-only metadata as corroborating evidence for the anchor bundle.

## 4. Root Cause

The anchor path expected the same named candidate to be observable and stable through normal focus verification. On these WebView landings, the two evidence channels are split:

- truncated `FOCUS_RESULT`: focused WebView container metadata, but no usable identity;
- helper dump tree: configured plugin title/child identity, but no WebView container.

The old code did not correlate and combine them with the successful entry transition, so it conservatively aborted despite a valid landing.

## 5. Evidence Bundle Contract

`PostEntryLandingEvidence` is eligible only at `scenario_start` for `new_screen` + `anchor_only`. Acceptance requires all of the following:

1. a fresh scenario-matched correlation ID from the successful `xml_scroll_search_tap` action;
2. a confirmed transition signal and a pre-entry surface signature different from both post-entry observations;
3. two observations of the same accessibility-focused, visible, empty-name WebView root with stable package/class/bounds;
4. the same configured child identity or exact configured resource identity in two dump-tree observations;
5. no delayed change to a non-WebView focus node.

WebView class, bounds, helper/tap success, package sameness, empty root, generic text, or inferred transition alone never pass the contract. Correlation older than 120 seconds, scenario mismatch, unstable bounds, unchanged pre/post surface, missing configured identity, or changed delayed focus is rejected.

## 6. Fix

- Capture a bounded pre-entry surface signature and a fresh scenario correlation when the existing XML entry transition check succeeds.
- Preserve complete root-only boolean metadata (`accessibilityFocused`, `focused`, `visibleToUser`) from a truncated focus response.
- Keep that partial root rejected as a normal focus result, but copy it into the step trace as corroborating evidence.
- Evaluate the correlated landing bundle only after ordinary anchor stabilization fails.
- Log the decision as `[ANCHOR][post_entry_evidence]` and return `correlated_empty_webview_landing` only when the full contract passes.
- Keep the existing named-root, exact anchor, normal plugin, and conservative abort paths unchanged.

There is no production branch for Home Care or Clothing Care names and no global anchor score/threshold change.

## 7. Rejected Unsafe Alternatives

- trusting every empty WebView root;
- accepting class, package, bounds, tap success, or transition alone;
- treating an untrusted partial parse as the current focus;
- using stale fallback XML or a different scenario transaction;
- increasing sleep/retry values;
- changing Runtime Dashboard reporting to conceal the abort;
- scenario-name bypasses or global threshold relaxation.

## 8. Unit/Regression Tests

The targeted suite completed with `513 passed`.

Covered cases include named WebView compatibility, root-only focused WebView plus stable child evidence, exact resource evidence, English/Korean Home Care and Clothing Care fixtures, class-only rejection, tap-only rejection, stale evidence, correlation mismatch, delayed focus/bounds change, unchanged pre/post surface, parser truncation trust boundaries, trace propagation, normal named plugin entry, non-WebView entry, and generic WebView false positives.

## 9. Targeted Device Results

Device: `SM-F741N` / `R3CX40QFDBP`. Each run used smoke mode with one selected scenario, Evidence/Identity/Traversal V2 enabled, and Runtime Profiler enabled. No Full Run was executed.

| Case | Batch | Locale | Anchor result | Steps | Reconciliation | Ledger | Profiler |
|---|---|---|---|---:|---|---|---|
| Home Care EN | `batch_20260716_211802` | `en-US` | accepted, abort 0 | 8 | PASS / `TRAVERSAL_STOPPED` | orphan 0, duplicate 0, write failure 0 | `traversal-profiler-v1`, JSON present |
| Clothing Care EN | `batch_20260716_212043` | `en-US` | accepted, abort 0 | 4 | PASS / `TRAVERSAL_STOPPED` | orphan 0, duplicate 0, write failure 0 | `traversal-profiler-v1`, JSON present |
| Home Care KO | `batch_20260716_212546` | `ko-KR` | accepted, abort 0 | 8 | PASS / `TRAVERSAL_STOPPED` | orphan 0, duplicate 0, write failure 0 | `traversal-profiler-v1`, JSON present |
| Clothing Care KO | `batch_20260716_212810` | `ko-KR` | accepted, abort 0 | 4 | PASS / `TRAVERSAL_STOPPED` | orphan 0, duplicate 0, write failure 0 | `traversal-profiler-v1`, JSON present |

All four logs record `accepted=true`, reason `correlated_empty_webview_landing`, root package/class/bounds, configured child identity, and a scenario correlation ID. Evidence finalization is PASS in every run.

## 10. Residual Risk

- Validation is limited to four single-scenario smoke runs; the prohibited 32-scenario Full Run was not performed.
- An additional broad legacy sweep completed with 652 passes and 8 failures in unchanged `clear_logcat`, client-version, and announcement-trimming assertions. They are outside this patch and were not relaxed or fixed in this phase.
- The contract depends on the helper retaining complete root scalar fields before a truncated child array. If serialization order changes, the result remains a conservative abort.
- Clothing Care terminated after four observed steps under existing stop/recovery behavior. Reconciliation and profiler artifacts are valid, but this phase does not change traversal depth, Recovery, Stop Policy, Coverage, or Identity semantics.
- Runtime Dashboard may still map a genuine future anchor abort to `NO_TARGET_CANDIDATE`; that reporting issue is explicitly out of scope.

## 11. Rollback

Rollback consists of removing the entry transition evidence capture, root-only trace field, `PostEntryLandingEvidence` evaluator/integration, and their tests. No schema migration, database, baseline repository, candidate, or approved baseline rollback is required. With rollback, these empty-name WebView landings return to the previous conservative anchor abort.

## 12. Phase 10.2.2B 준비 상태

The Home Care/Clothing Care common blocker is cleared in English and Korean targeted validation. Phase 10.2.2B may proceed to its separately scoped work. Air Care summary, Pet Care Korean tokens, Runtime Dashboard, profiler propagation, Candidate approval, and Baseline Repository state were not modified here.
