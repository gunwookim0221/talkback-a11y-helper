# Audit V4 Family Care Bottom Strip Root Cause

## 1. Background

Audit V4 remains diagnostic-only.

By Phase 3.20, the Family Care required-miss set had been reduced to a narrow
bottom-strip problem:

- `EventsButton`
- `LocationButton`

Evidence-corrected required coverage state:

- denominator: `25`
- matched: `23`
- missing: `2`
- coverage: `92.0%`

This phase is not policy review. It is runner-behavior analysis focused on why
the Family Care bottom strip does not stabilize the way other already-visited
content surfaces do.

## 2. Evidence Timeline

The important sequence in the Family Care run is:

1. Entry XML already contains the bottom strip:
   `ActivityButton`, `LocationButton`, `EventsButton`
2. Early traversal does **not** focus the bottom strip directly
3. Step 3 focuses `Activity`, but that is the content header
   `com.samsung.android.plugin.care:id/activity_toolbar`, not the strip tab
4. Step 14 directly focuses `Mobile usageButton` in body content
5. Step 16 emits a `local_tab` lifecycle event for `EventsButton`
6. Despite that, content traversal continues and the strip remains deferred
7. Step 19 exhausts content, then recovers strip state from dump-only evidence
8. Recovered active tab becomes `LocationButton Location`
9. Progression target becomes `EventsButton Events`
10. Step 20 activation attempts fail and no strip focus hit is produced

Condensed timeline:

```text
entry dump contains ActivityButton / LocationButton / EventsButton
↓
bottom_strip_policy deferred while content exists
↓
step 3: content header "Activity" hit, not strip hit
↓
step 14: Mobile usageButton hit in content body
↓
step 16: local_tab lifecycle sees EventsButton
↓
policy still prefers content candidate over strip focus
↓
step 19: content exhausted, strip state recovered from dump
↓
active=LocationButton Location, next=EventsButton Events
↓
step 20: EventsButton activation fail
```

## 3. Local Tab State Analysis

### 3.1 What The Runner Knows Early

The runner has strong bottom-strip evidence from the beginning:

- entry XML contains all three strip candidates
- `bottom_strip_policy` repeatedly logs:
  `content_present=true bottom_strip_deferred=true`

This means the runner knows the strip exists, but intentionally delays strip
handling while body content remains available.

### 3.2 Activity State

Important correction:

- step 3 `visible='Activity'` is **not** `ActivityButton`
- it comes from content header `activity_toolbar`

Evidence:

- log row fingerprint:
  `com.samsung.android.plugin.care:id/activity_toolbar|activity|activity`
- XML:
  `activity_toolbar` has `content-desc='Activity'`
- bottom-strip `ActivityButton` is a separate node at the bottom edge and is
  `clickable=false`, `focusable=true`, `selected=true`

Implication:

- the run never established a clean committed strip state through a direct
  bottom-strip focus hit on `ActivityButton`

### 3.3 Location State

`LocationButton` never gets a direct spoken hit.

What exists instead:

- step 19 recovery:
  `local_tab_recover ... candidates='LocationButton Location|EventsButton Events' active='LocationButton Location'`
- state resolution:
  `local_tab_active_resolved source='current_row' active='LocationButton Location'`

Implication:

- `LocationButton` becomes the active tab only through recovered dump-based
  inference, not through a committed focus history

### 3.4 Events State

`EventsButton` has the strongest strip-local signal:

- step 16:
  `LIFECYCLE kind='local_tab' source='bottom_strip_candidate' confidence='high' label='EventsButton'`

But the state machine still does not commit it as active. Later:

- `committed='none'`
- `pending='none'`
- strip state must be reconstructed from dump

Implication:

- a high-confidence strip signal is observed but not stabilized into durable
  local-tab state

### 3.5 State Summary

| Candidate | Direct strip focus committed? | Recovered from dump? | Durable local-tab state? |
| --- | --- | --- | --- |
| `ActivityButton` | no | implicit only | weak |
| `LocationButton` | no | yes | medium |
| `EventsButton` | lifecycle only | yes as target | weak |

Net reading:

- the Family Care bottom strip is being handled as a deferred/recovered
  structure, not as a first-class committed local-tab surface

## 4. Activation Failure Analysis

### 4.1 Failure Site

The decisive failure occurs at step 20:

- `local_tab_target_activate target='EventsButton Events' method='tap_bounds_center'`
- `local_tab_target_activate_no_match ... reason='focus_not_target_after_tap'`
- `local_tab_target_activate method='select_label'`
- `local_tab_target_activate_fail ... reason='no_match_after_all_methods'`

### 4.2 Candidate Existence

The candidate clearly exists.

XML evidence:

- `EventsButton`
- class: `android.widget.LinearLayout`
- clickable: `true`
- focusable: `true`
- bounds: `[710,2316][1050,2496]`

So the failure is not:

- candidate absent
- candidate non-focusable
- candidate non-clickable

### 4.3 Why Activation Fails

Most likely failure chain:

1. Strip handling is deferred until content exhaustion
2. Active strip state is reconstructed late from dump-only evidence
3. The runner chooses `EventsButton Events` as next target without a stable
   committed strip context
4. Tap-by-bounds does not produce a focus payload matching the expected target
5. Label selection also fails because the strip target is not materialized as a
   clean active focus object after the fallback methods

This is more consistent with a strip-state/policy problem than with raw bounds
or clickability failure.

### 4.4 Bounds Assessment

The bounds are valid and visible:

- `EventsButton` occupies the right third of the bottom strip
- tap point `880,2406` falls inside the candidate bounds

So this does **not** look like a simple invalid-bounds bug.

## 5. Chrome Penalty Analysis

`chrome_penalty` is present throughout the run, but it affects only top-header
items:

- `Navigate up`
- `Family Care`
- `Add family member`
- `More options`

There is no evidence that `chrome_penalty` directly suppresses:

- `ActivityButton`
- `LocationButton`
- `EventsButton`

Conclusion:

- `chrome_penalty` is not the root cause of the bottom-strip failure
- it is orthogonal header behavior

## 6. Focus Realign Analysis

### 6.1 Key Step: 16

At step 16, the runner has direct strip signal:

- current focus context is `EventsButton`
- lifecycle says `label='EventsButton'`

But candidate selection still prefers body content:

- `selected='Mobile usage'`
- `focus_force_realign target='Mobile usage'`

Then realignment resolves incorrectly:

- `focus_realign_success target='Mobile usage' resolved_focus='건우의 Z Flip6'`

And final candidate priority becomes:

- `selected='건우의 Z Flip6'`

### 6.2 Implication

This is a strong sign that focus realignment is contributing to the failure:

- strip focus arrives
- the policy rejects the strip because content is still present
- focus is forcibly realigned to a content candidate
- realignment itself resolves to a different object than the requested target

That means focus realignment is not the first cause, but it amplifies the
policy/state problem and helps erase the strip focus opportunity.

### 6.3 Same-Object / Confidence Reading

The run does not maintain a same-object relation between:

- `EventsButton`
- selected content candidate
- final resolved focus object

Instead it drifts:

```text
current_focus = EventsButton
selected = Mobile usage
resolved_focus = 건우의 Z Flip6
```

This is exactly the kind of context drift that makes later strip recovery more
fragile.

## 7. Root Cause Assessment

### 7.1 Primary Root Cause

Primary classification:

- `BOTTOM_STRIP_POLICY_BUG`

Reason:

- the runner repeatedly defers the bottom strip whenever content is present
- even when a direct strip lifecycle signal for `EventsButton` appears, the
  strip is not accepted as the active traversal target
- this causes late dump-based recovery instead of stable direct strip traversal

### 7.2 Secondary Contributing Factors

Secondary contributors:

- `LOCAL_TAB_STATE_BUG`
- `FOCUS_REALIGN_BUG`

`LOCAL_TAB_STATE_BUG`

- high-confidence strip evidence does not become committed local-tab state
- step 19 shows `committed='none'` and recovery from `current_row`

`FOCUS_REALIGN_BUG`

- step 16 force-realigns away from strip focus
- target `Mobile usage` resolves to `건우의 Z Flip6`, showing context drift

### 7.3 What It Is Not

The evidence does **not** support:

- `RUNNER_BUG` as a purely generic label without mechanism
- `PLUGIN_SPECIFIC_STRUCTURE` as the sole cause
- `INSUFFICIENT_EVIDENCE`

Family Care likely has plugin-specific complexity, but the observed failure
mechanism is concrete enough to classify more specifically than that.

## 8. Fix Difficulty

Estimated difficulty:

- `MEDIUM`

Expected scope:

- likely affects Life plugins with deferred bottom-strip / pseudo-local-tab
  structures
- not obviously all device local-tab plugins
- broader than Family Care only, but narrower than global traversal

Why not `LOW`:

- multiple subsystems interact:
  bottom-strip policy, local-tab state persistence, focus realign

Why not `HIGH`:

- the problem is localized and the failure sequence is reproducible
- there is a specific policy/state handoff to target

Practical scope statement:

- likely `Life plugins` with bottom-strip navigation patterns

## 9. Phase 4 Impact

Question:

- can Shadow Verdict proceed without fixing `EventsButton`?

Answer:

- `PARTIAL`

Reasoning:

- evidence-corrected coverage is already about `92%`
- denominator ambiguity has been mostly resolved
- the remaining miss is narrow and well-understood

Why not `YES` outright:

- `EventsButton` is still a high-confidence miss on a meaningful navigation
  surface
- if untracked, it can create false negative confidence in Family Care quality

Why not `NO`:

- this is too localized to justify blocking all shadow-verdict experimentation
- it should be carried as a known-risk item, not as a universal stop signal

## 10. Recommendation

Recommended conclusions:

1. Treat the Family Care bottom-strip problem primarily as a
   `BOTTOM_STRIP_POLICY_BUG`
2. Note `LOCAL_TAB_STATE_BUG` and `FOCUS_REALIGN_BUG` as secondary
   contributors
3. Keep `EventsButton` as the main unresolved high-confidence miss
4. Keep `LocationButton` as secondary until a direct strip focus path is
   confirmed or disproved
5. Use the evidence-corrected coverage baseline for future Phase 4 discussion:
   `25 / 23 / 2 = 92.0%`

Recommended next step:

- proceed to Shadow Verdict planning with an explicit Family Care known-risk
  note, and separately design bottom-strip remediation for Life plugins

Bottom line:

- `EventsButton` fails not because it is absent or non-focusable
- it fails because strip focus is deferred, state is recovered too late, and
  forced realignment pulls traversal back into content before strip activation
  can stabilize
