# Phase 4C Camera popup and modal RCA

Date: 2026-10-11
Branch: `integration/phase3-current-main`

## Finding

The Camera PIP controls were falsely treated as modal because the old detector
promoted a resource-name substring into modal evidence. This caused a normal
inline PIP control to mark the diagnostic overlay as observed, kept recovery
active, and denied controlled execution with `RECOVERY_CONFLICT`.

The RCA is proven by the old detector path and the saved rejected Camera trace.
The new live capture supports `INLINE_PIP_CONTROL` for 19 steps and leaves one
focus-inside-PIP observation `AMBIGUOUS_OVERLAY`; it does not claim that every
Camera overlay state is always non-modal.

## Old behavior

The old flow was:

```text
hierarchy capture
  -> detect_popup_candidate
  -> _modal_evidence sees "popup" in a resource ID
  -> popup_resource / modal_container_seen
  -> title_body_with_actions can be synthesized
  -> state fingerprint says overlay observed
  -> recovery ownership enters RECOVERY_ACTIVE
  -> controlled execution gate returns RECOVERY_CONFLICT
  -> production fallback
```

The matched Camera resources were `btn_popup_play_parent`,
`btn_popup_play_frame`, and `btn_popup_play`. The old detector did not require a
dialog window, dialog root, substantial blocking region, inaccessible
background, focus trap, or required dismissal before the resource token could
contribute to modal evidence. That is the false-positive root cause.

## Camera hierarchy and window evidence

The live nodes are nested under `live_overlay_layout` in Camera's
`MainActivity`:

| Node | Class | Bounds | Semantic evidence |
|---|---|---|---|
| `btn_popup_play_parent` | `LinearLayout` | `[634,721][821,853]` | PIP wrapper |
| `btn_popup_play_frame` | `FrameLayout` | `[679,739][775,835]` | PIP frame |
| `btn_popup_play` | `ImageButton` | `[694,754][760,820]` | description `PIP` |

The device display was 1080×2640. The candidate union occupied about 0.8657%
of display area. Window Manager evidence showed the active Camera
`MainActivity` in a `BASE_APPLICATION` window; 22 windows were summarized. The
background remained accessible. For 19 steps, TalkBack accessibility focus
was outside the PIP. On step 19, the actual `accessibilityFocused` node was
inside the PIP. The latter observation is intentionally ambiguous and retains
the production recovery block. No dialog/modal root or required dismissal was
observed in the live run.

## Generic classification contract

`tb_runner/popup_handler.py::classify_modal_state` combines hierarchy,
Window Manager, display geometry, background accessibility, and actual
accessibility-focus evidence. Resource ID, text, or description containing
`popup` appears only in `candidate_evidence`.

| Result | Meaning and execution effect |
|---|---|
| `VERIFIED_MODAL` | Dialog window, dialog root with explicitly inaccessible background, or substantial explicitly blocking region with background inaccessible. Preserve recovery block. |
| `LIKELY_MODAL` | Dialog hierarchy or substantial overlay/blocking region without evidence that the background remains accessible. Preserve conservative block. |
| `NON_MODAL_CONTROL` | Small candidate, same active application activity/window, accessible background, and actual accessibility focus outside the candidate. Must not create modal recovery conflict by itself. |
| `AMBIGUOUS_OVERLAY` | Missing or contradictory evidence, including focus inside a candidate or mismatched window ownership. Remain conservative. |

The non-modal conclusion requires positive corroboration; absence of a popup
token does not establish a clear screen when Window Manager context is
suspicious. `inputFocused` is not used as accessibility-focus evidence.
Dismissal candidates are accepted only for `VERIFIED_MODAL` or
`LIKELY_MODAL`. The production recovery/authority gate was not loosened; its
input now receives semantically classified overlay evidence.

## Change scope

- `tb_runner/popup_handler.py`: candidate-only popup strings, generic modal
  classification, and modal-only dismissal eligibility.
- `tools/state_fingerprint_diagnostic.py`: capture bounded window identity,
  focused window type, focus owner, and explicit overlay classification. On the
  foldable device, select the last concrete `mCurrentFocus=Window{...}` line
  when an earlier display reports `mCurrentFocus=null`.
- `tests/test_popup_handler.py`,
  `tests/test_state_fingerprint_diagnostic.py`, and
  `tests/test_window_evidence.py`: candidate-only names, PIP/background
  behavior, dialog and blocking-overlay preservation, ambiguous focus/window
  evidence, input-focus separation, and foldable focus-line selection.

Planner ranking, candidate and focus identity, visit authority, attempts,
scroll, starvation, Camera limits, and Camera termination were unchanged.
There is no Camera scenario or `btn_popup_play` special case.

## Verification

- Focused dynamic-context: 50 passed.
- Audit focused: 87 passed.
- Phase 3 focused: 58 passed.
- Production focused: 442 passed.
- Phase 4 focused: 267 passed.
- Popup/modal and window evidence focused: 27 passed.
- Full Python: **3814 passed, 1 skipped, 0 failed**.
- Helper source did not change; prior accepted Helper suite: 408 passed.
- Historical Phase 3, Phase 4A, Phase 4B, accepted baseline, Phase 4C,
  Food audit, Family recovery reference, and rejected Camera replays passed
  their recorded semantic gates. The Family recovery reference is revalidated
  as stored; live Stage C Family Care independently passed.

The Camera live acceptance entered normally and finished all 20 bounded steps:

| Metric | Result |
|---|---:|
| Candidate steps | 20 |
| `VERIFIED_MODAL` / `LIKELY_MODAL` | 0 / 0 |
| `NON_MODAL_CONTROL` / `AMBIGUOUS_OVERLAY` | 19 / 1 |
| Planner recommendation / authorized / executed | 19 / 19 / 19 |
| Recovery conflict / fallback | 1 / 1 |
| Confirmed focus moves / native visits | 20 / 19 |
| Audit chain incomplete | 0 |
| Safety, lifecycle, and transport hard gates | 0 |
| Termination | `INCOMPLETE_SAFETY_LIMIT` / `safety_limit` |

The other seven shared-infrastructure scenarios passed live: Stage B 4/4 and
Stage C 3/3. All audit and planner safety keys were zero. Across all eight live
scenarios, lifecycle and transport keys were zero. The default Smart Traversal
feature flags remain off.

The old Camera replay changed from 20/20 `RECOVERY_CONFLICT` decisions to 16
authorized and 4 conservatively blocked decisions. It executes no actions and
awards no visits. No true modal appeared live; true-modal blocking is verified
with focused constructed tests. Camera coverage improved from 15 to 19 native
primary visits. Food is `ACCEPTABLE_VARIANCE` (16 native visits against a 19
reference prefix) in a state-sensitive bounded run: 20 steps, all three scrolls
executed, 21 unique visited instances, and no failed/indeterminate focus moves
or safety/audit violations. It is not called equivalent.

## Verdict

```text
OVERALL_VERDICT=PHASE4_CAMERA_MODAL_RECOVERY_PASS_WITH_LIMITATIONS
PHASE4_COMPLETE=YES
READY_FOR_PHASE5=YES
PHASE5_IMPLEMENTED=NO
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF
```

Limitations: a real modal was not encountered on-device; its preserved block
behavior is covered by constructed tests. Camera step 19 remains ambiguous and
was safely blocked. The safety-limit run does not prove complete Camera
coverage. Per-step and gate artifacts are in
`../phase4c_camera_modal_closure_retry_20261011/`.
