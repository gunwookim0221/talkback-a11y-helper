# Audit V4 Traversal Gap Analysis

## 1. Background

Audit V4 remains diagnostic-only. Phase 3.15 classified 60 coverage-relevant misses and identified 11 required misses. The required-miss breakdown was:

- MATCHING_GAP: 7
- TRAVERSAL_GAP: 4
- TAXONOMY_GAP: 0

Phase 3.16 showed that matching relaxation can improve required coverage from 63.3% to 76.7%, but it does not eliminate all required misses. This phase isolates the remaining traversal-related misses and tests whether they are true runner failures, inaccessible XML-only artifacts, or eligibility-definition problems.

This document is analysis only. It does not change traversal, matching, coverage policy, verdict logic, or subtype definitions.

## 2. Traversal Gap Inventory

Phase 3.15 classified the following required misses as `TRAVERSAL_GAP`.

| Plugin | Missing label | Expected role | Notes |
| --- | --- | --- | --- |
| `device_smoke_sensor_plugin` | `Controls` | local tab / actionable tab label | XML candidate exists, no traversal hit |
| `device_door_lock_plugin` | `Controls` | local tab / actionable tab label | XML candidate exists, no traversal hit |
| `life_family_care_plugin` | `Add family member` | CTA | XML candidate exists, no traversal hit |
| `life_family_care_plugin` | `View profile` | CTA | XML candidate exists, no traversal hit |

Inventory count:

- Total traversal-gap required misses: 4
- Device: 2
- Life: 2

## 3. Evidence Review

### 3.1 `device_smoke_sensor_plugin` / `Controls`

Observed evidence:

- XML candidate exists with `type=ACTIONABLE`, `subtype=UNKNOWN`, `resource_id=control`, `clickable=true`, `focusable=true`.
- Candidate tab associations include `Controls`, `Routines`, `History`, and `entry`.
- `detected_tabs` and `visited_tabs` both contain `Controls`, `Routines`, and `History`.
- Runtime log shows `local_tab_active='Controls'`, `local_tab_target_activate_success target='Controls'`, and `local_tab_commit active='Controls'`.
- After tab activation, traversal focuses content labels such as detector status/history labels, not the `Controls` tab label itself.
- No TalkBack focus hit for literal `Controls` was observed.

Assessment:

- XML presence: yes
- TalkBack focus evidence: no
- Traversal hit: no
- Lifecycle event: yes (`local_tab`)
- local tab: yes
- candidate type: actionable local-tab label

Judgment:

- Root cause: `LOCAL_TAB_MISSED`
- Evidence class: `A` and `C`
  - TalkBack does not appear to read the tab label itself after activation.
  - The candidate is present in XML, but it behaves like a structural tab token rather than a traversed spoken target.

### 3.2 `device_door_lock_plugin` / `Controls`

Observed evidence:

- XML candidate exists with `type=ACTIONABLE`, `subtype=UNKNOWN`, `resource_id=control`, `clickable=true`, `focusable=true`.
- Candidate tab associations include `Controls`, `Routines`, `History`, and `entry`.
- `detected_tabs` and `visited_tabs` both contain `Controls`, `Routines`, and `History`.
- Runtime log shows `local_tab_active='Controls'`, `local_tab_target_activate_success target='Controls'`, and `local_tab_commit active='Controls'`.
- After tab activation, traversal focuses device content such as `Lock state` and related content, not the literal `Controls` label.
- No TalkBack focus hit for literal `Controls` was observed.

Assessment:

- XML presence: yes
- TalkBack focus evidence: no
- Traversal hit: no
- Lifecycle event: yes (`local_tab`)
- local tab: yes
- candidate type: actionable local-tab label

Judgment:

- Root cause: `LOCAL_TAB_MISSED`
- Evidence class: `A` and `C`
  - The tab is operationally visited, but the tab label itself is not exposed as a focused spoken target.

### 3.3 `life_family_care_plugin` / `Add family member`

Observed evidence:

- XML candidate exists with `type=ACTIONABLE`, `subtype=CTA`, `resource_id=com.samsung.android.plugin.care:id/menu_main_invite_member`, `clickable=true`, `focusable=true`.
- Entry-state evidence shows the label in visible text near the top of the screen.
- Runtime log explicitly shows `chrome_penalty` / `chrome_excluded` entries that deprioritize `Add family member` during content traversal.
- Traversal continues through multiple downstream content items, so this is not an early-stop case.
- No TalkBack focus hit for `Add family member` was observed in the traversal sequence.

Assessment:

- XML presence: yes
- TalkBack focus evidence: not observed in collected traversal
- Traversal hit: no
- Lifecycle event: no direct lifecycle event
- local tab: no
- candidate type: CTA

Judgment:

- Root cause: `CTA_NOT_REACHED`
- Evidence class: `B`
  - The CTA is visible and actionable in XML, but the runner suppresses it as top chrome and never reaches it as a content target.

### 3.4 `life_family_care_plugin` / `View profile`

Observed evidence:

- XML candidate exists with `type=ACTIONABLE`, `subtype=CTA`, `resource_id=com.samsung.android.plugin.care:id/profile_icon`, `clickable=true`, `focusable=true`.
- Entry-state evidence shows `View profile` in visible/body text at the top region.
- Traversal proceeds into downstream content and other actionable elements.
- Unlike `Add family member`, there is no equally explicit log line showing direct exclusion of `View profile`, but it is also never focused.

Assessment:

- XML presence: yes
- TalkBack focus evidence: not observed in collected traversal
- Traversal hit: no
- Lifecycle event: no direct lifecycle event
- local tab: no
- candidate type: CTA

Judgment:

- Root cause: `CTA_NOT_REACHED`
- Evidence class: `D`
  - The candidate is visible in XML and screen text, but the collected evidence is weaker than `Add family member` for proving an explicit runner suppression path.

## 4. Root Cause Categories

Traversal-gap root cause distribution across the 4 required misses:

| Root cause | Count | Share | Items |
| --- | --- | --- | --- |
| `LOCAL_TAB_MISSED` | 2 | 50.0% | Smoke `Controls`, Door Lock `Controls` |
| `CTA_NOT_REACHED` | 2 | 50.0% | Family Care `Add family member`, `View profile` |

No traversal-gap items were supported as:

- `TAB_NOT_VISITED`
- `RUNNER_STOPPED_EARLY`
- `XML_ONLY_NON_ACCESSIBLE` as the sole explanation
- `FOCUS_CHAIN_BROKEN` with direct proof

Interpretation:

- Device-side traversal gaps are not unvisited tabs. They are local-tab labels that were activated operationally but never surfaced as spoken focus tokens.
- Life-side traversal gaps are top-of-screen CTAs that remained outside the effective traversal path.

## 5. Required Miss Impact

Starting point from Phase 3.15:

- Required miss = 11

After Phase 3.16 matching simulation D:

- Required miss = 7

If the 4 traversal-gap required misses are also removed hypothetically:

- Required miss = 3

Implications:

- Traversal-gap items account for 36.4% of original required misses (`4 / 11`).
- Traversal-gap items account for 57.1% of the post-matching residual required misses (`4 / 7`).

This means traversal is the dominant remaining blocker after matching relaxation, but the 4 items are not uniform:

- 2 items are local-tab label artifacts (`Controls`)
- 2 items are top CTA reachability artifacts (`Add family member`, `View profile`)

Therefore the remaining problem is not a single generic traversal defect. It is a mix of:

- coverage eligibility ambiguity for structural tab labels
- runner reachability gaps for top-of-screen CTA targets

## 6. Phase 4 Blockers

### 6.1 Blocker Re-evaluation

Phase 4 is not blocked by taxonomy expansion for these required misses. The traversal-gap evidence points elsewhere.

Blocker judgment:

- `device_smoke_sensor_plugin` / `Controls`: primarily coverage-target-definition ambiguity
- `device_door_lock_plugin` / `Controls`: primarily coverage-target-definition ambiguity
- `life_family_care_plugin` / `Add family member`: likely true runner traversal issue
- `life_family_care_plugin` / `View profile`: unresolved, but closer to runner reachability than taxonomy

Overall verdict:

- Best fit: `C` and `B` combined
  - `C`: some misses are better explained by coverage-target definition problems, especially local-tab labels that are activated but never spoken
  - `B`: at least one miss (`Add family member`) shows evidence of a real runner reachability problem

### 6.2 Net Conclusion

Traversal is still a real blocker, but not all traversal-gap items should be treated as runner bugs.

Priority by confidence:

1. Re-check coverage eligibility for structural local-tab labels such as `Controls`
2. Investigate runner behavior for top CTAs suppressed as chrome
3. Defer taxonomy work for these items because no traversal-gap item requires subtype expansion

## 7. Recommendation

Recommended next step:

- `Phase 3.18 - Traversal Remediation Design`

Reasoning:

- After matching relaxation, traversal explains most of the remaining required misses.
- The strongest runner-side evidence is on Family Care CTA reachability, especially `Add family member`.
- The device `Controls` misses should be handled as a design-input question before any runner fix, because the tabs are visited and activated already.

Recommended order:

1. Split traversal residuals into two tracks:
   - structural local-tab labels (`Controls`)
   - top CTA reachability (`Add family member`, `View profile`)
2. For local-tab labels, perform a focused eligibility re-check:
   - if TalkBack never focuses/speaks the tab token itself after activation, it should not remain a required coverage target
3. For Family Care CTAs, design traversal remediation without changing implementation in this phase:
   - review chrome-penalty behavior near top CTAs
   - review whether entry-region actionable CTAs should be revisited after content traversal begins
4. Delay `Phase 4.0 Shadow Verdict Design` until the above split is resolved, because the residual required misses are still materially sensitive to traversal interpretation

Bottom line:

- Matching is no longer the main blocker.
- Traversal-adjacent residual misses are now the main blocker.
- Within that blocker, the first distinction is not device vs life, but `eligibility ambiguity` vs `true runner reachability`.
