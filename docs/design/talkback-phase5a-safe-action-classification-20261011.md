# Phase 5A Safe Action Classification Foundation

Date: 2026-10-11

Scope: `integration/phase3-current-main`, starting at accepted Phase 4 commit
`16940815ccba5f00da04bb2171b19fbfa7da1343`. This dated integration result does
not enable production Smart Traversal or implement Phase 5B/5C navigation.

## Contract

Safety classifies an **action on a target**. Moving accessibility focus to an
Unlock or Delete control is read-only; activating that control is a different
action and may affect a device or user data. Focus retains target activation
risk signals for inspection without treating those effects as focus effects.

`tb_runner/action_safety.py` is a pure classifier, `safe_action_policy.py` is
the eligibility policy, and `phase5a_safety.py` composes those decisions around
the existing Phase 4 focus/scroll planner. None dispatches device commands or
writes attempt/visit ledgers.

| Class | Phase 5A policy |
|---|---|
| `SAFE` | Eligible for the existing Phase 4 gate at HIGH/MEDIUM confidence. |
| `CONDITIONALLY_SAFE` | Eligible only when every named condition is explicitly true. |
| `RISKY` | Block automatic controlled execution. |
| `FORBIDDEN` | Prohibit automatic controlled execution. |
| `UNKNOWN` | Block; retain the observation and allow existing read-only traversal fallback. |

LOW/unknown confidence never authorizes a SAFE action. Policy eligibility is
not execution authority. Fresh presence, actual accessibility focus, target
identity, destination/context, viewport, request correlation, budget and
recovery checks remain the responsibility of the unchanged Phase 4 gate and
production reconciliation.

## Identity, evidence, and risk

Action identity includes normalized action type, the existing target instance
identity, state, semantic substate, and destination. It does not include a
random UUID, wall time, attempt number, or volatile target label. Changing
target text alone does not change action identity. CLICK and FOCUS on the same
target are different actions. Existing candidate, focus, production instance,
attempt and visit identities remain unchanged.

The normalizer covers FOCUS, CLICK, LONG_CLICK, SCROLL_FORWARD,
SCROLL_BACKWARD, BACK, OPEN_MENU, SELECT_TAB, EXPAND, COLLAPSE, TOGGLE, CHECK,
UNCHECK, TEXT_INPUT, SUBMIT, CONFIRM, DISMISS, NAVIGATE, EXTERNAL_INTENT, and
UNKNOWN_ACTION. Existing discovery action kinds are mapped to these types.
Activating a switch/checkbox is a toggle, rather than an ordinary information
click. Scroll on a slider/SeekBar is classified as state adjustment rather
than a viewport-only scroll.

The result records reversibility, state mutation, external effects,
destructiveness, physical device effects, account/security effects,
payment/commerce effects, privacy effects, navigation scope, recovery
confidence, and semantic certainty. Unknown dimensions stay explicit.
Every result carries a deterministic action ID, target identity, class,
confidence, signals, reason, required conditions, and risk categories.

Lexical matches in labels/descriptions/resources nominate risk. Activation
capability corroborates a risky control; configured effects or verified
confirmation context provide stronger evidence. Static text matching Delete
without activation evidence remains unknown. The EN/KO lexicon and physical
context/command providers are in `config/safe_action_policy.json`. No scenario
ID or single locale is a classification authority. The metadata-rule selectors
are generic resource ID, class, role, and context kind; scenario selectors and
conflicting effects are rejected conservatively.

Only explicitly configured metadata can certify an informational effect.
Untrusted metadata attached to a hierarchy node cannot certify safety. The
default metadata-rule list is empty. Power usage, Payment history, and Remove
filter are eligible only with a corroborated information/UI-only effect and
the required scope/recovery conditions. Such a label alone is insufficient.

Unavailable/ambiguous target evidence fails closed. Explicit automation
prohibition dominates positive hints. Configured destructive/payment/account/
physical/external/privacy effects block, and verified risky confirmation
context inherits or increases risk. Corroborated read-only effects can
disambiguate weak lexical candidates; they cannot override a known mutation
effect. Unknown controls never fall through to SAFE.

## Confirmation, dismissal, and physical devices

Delete/Confirm/OK in a verified destructive confirmation inherits FORBIDDEN
risk. Payment/account/external confirmation inherits RISKY risk. Cancel and
Close are evaluated separately: eligibility requires a known non-committing
dismissal, verified modal context, current target, cancellation-only effect,
and within-app scope. A generic dismissal operation or a safe-sounding label
cannot authorize a destructive confirmation.

Power, unlock, start/stop, alarm/siren, camera privacy and similar commands
remain risky. A Start control in a tutorial with a configured read-only effect
differs from Start in a corroborated appliance context. Settings toggles,
checkbox mutations, editable input and external intents are not presumed safe.
Tests include Smoke Sensor siren, Door Lock unlock, TV power, Washer start/stop,
and Camera privacy. No real physical-device effect was triggered in validation.

## Integration and defaults

The generalized opt-in harness reads
`TB_PHASE5A_ACTION_SAFETY_MODE=off|shadow|enforce`. The default is **off**;
invalid modes fail before device I/O, and Phase 5A modes require the generalized
Phase 4C harness. The normal production runner has no new import or hook.
Production Smart Traversal and Safe Action Enforcement remain OFF.

Off/shadow return the original PlannerInput and recommendation. Shadow appends
observational evidence without changing any Phase 4 decision. Enforce computes
an immutable intersection of safety-eligible focus instance IDs with the
existing traversal domain, then calls the original planner. Relative ranking
is unchanged. If all visible focus targets are blocked, verified eligible
scroll remains available; otherwise existing fallback remains available.
Blocked actions are retained in `safety_blocked_candidates` and the session
record. They do not dominate later rankings, consume attempts, create visits,
or cause a new termination rule.

Classification precedes the Phase 4 gate. A final fresh safety check after
context/target rebinding prevents a rebound recommendation from evading it.
Existing Phase 4 denials retain their original reason. Production handles
actual focus reconciliation and any attempt/visit credit. No planner ranking,
scroll, loop/starvation, plugin ownership, recovery, modal, or termination
implementation changed.

Conditional information navigation requires independent recovery evidence.
The current adapter deliberately does not claim that evidence: its
`recovery_verified` value is false. Phase 5A has no new click, toggle, submit,
text-input or navigation dispatcher. A safe classification alone cannot make
those actions executable through the existing focus/scroll gate. Complete
navigation/back-stack recovery belongs to Phase 5B.

## Audit provenance

An optional `action_safety` field is attached to the existing step-action
provenance chain, carrying its original owner and `step_action_id`. It includes
the planner action, class, confidence, signals, policy result, required
conditions, original Phase 4 gate, fresh selected-target evidence, and copied
final outcome/request. It grants no credits. Existing chains remain identical
when the field is absent.

Validators reject missing safety provenance, foreign step/scenario ownership,
sidecar/audit mismatches, and an enforced executed action whose classification
or conditions do not pass policy. Existing request/primary/recovery/focus/audit
validation remains intact.

## Verification

| Suite | Result |
|---|---:|
| New classifier/policy/integration/audit matrix | 150 passed |
| Phase 3 focused | 58 passed |
| Production focused | 442 passed |
| Phase 4/context/modal focused | 306 passed |
| Full Python | **3964 passed, 1 skipped, 0 failed** |

Helper source was unchanged. Its prior accepted result is 408 passed; it was
not rerun. Content checks against the start commit prove 18 protected Phase 4
implementation/config files unchanged. Changes to the harness and provenance
are opt-in/additive and have explicit off/shadow equivalence tests.

Replays were rerun from immutable saved evidence:

- Historical Phase 3: 16 exact; six accepted baseline scenarios PASS.
- Phase 4A: 30 exact inputs; Phase 4B: 30 exact controlled records.
- Phase 4C: 57 exact pre-stop records and 67 exact later legacy decisions.
- Food audit: 97 prior chains complete; old step-11 mismatch reproduced and
  repaired chain complete.
- Family recovery: 10 exact old denied gates; 6 later safe authorizations;
  generated records exactly match the reference. Off and shadow are exact.
- Camera modal: old 20 recovery conflicts; 16 authorized and 4 still blocked,
  unchanged from the accepted modal replay.
- New safety provenance: 97 accepted chains complete with their original
  fields, production rows and credit facts unchanged.

## Representative shadow observation

Validation used saved device observations and 34 independently labelled
constructed cases. It issued **zero new device commands** and made zero
attempt/visit mutations. The saved populations include Home, Devices, Life,
Food, Family Care, Energy, Find, Smoke Sensor, Door Lock, TV, Washer and Camera.
Door Lock has only one legacy partial population; its recovery/focus context
cannot be inferred. Independent EN/KO physical-action cases supplement it.

There were 128 bounded saved observations, 4,836 classified candidate-action
observations, and 2,911 distinct action identities. Counts retain repeated
observations and constructed examples, rather than claiming unique live
controls or complete coverage.

| Class | Count |
|---|---:|
| SAFE | 2142 |
| CONDITIONALLY_SAFE | 296 |
| RISKY | 124 |
| FORBIDDEN | 3 |
| UNKNOWN | 2271 |

Confidence: HIGH 2455, MEDIUM 110, LOW 2271. All 116 recorded actual Phase 4
controlled focus/scroll dispatches remained eligible: `NO_CHANGE=116`,
`FALSE_POSITIVE_BLOCK=0`, no insufficient comparisons. The 34 independent
expectations all matched; no labelled destructive, payment, account mutation,
physical-device control, privacy mutation or external-send action was SAFE or
policy eligible. Population-wide false negatives cannot be estimated from
unlabelled legacy activation effects.

Per-scenario counts below include saved observations and associated constructed
cases. Would execute/block are **policy eligibility counts**, not dispatches;
all eligible actions still require the Phase 4 gate. Would scroll counts
eligible scroll opportunities; fallback counts saved snapshots whose safety
projection has no planner action.

| Scenario | Actions | SAFE | Conditional | Risky | Forbidden | Unknown | Would execute | Would block | Would scroll | Fallback |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Home | 548 | 281 | 72 | 3 | 2 | 190 | 283 | 265 | 0 | 0 |
| Devices | 670 | 339 | 72 | 4 | 1 | 254 | 349 | 321 | 10 | 0 |
| Life | 552 | 271 | 68 | 4 | 0 | 209 | 284 | 268 | 10 | 0 |
| Door Lock | 15 | 6 | 0 | 2 | 0 | 7 | 6 | 9 | 0 | 0 |
| Camera | 740 | 419 | 20 | 1 | 0 | 300 | 439 | 301 | 20 | 1 |
| Find | 180 | 90 | 0 | 0 | 0 | 90 | 90 | 90 | 0 | 0 |
| Smoke Sensor | 149 | 63 | 0 | 1 | 0 | 85 | 63 | 86 | 0 | 0 |
| TV | 371 | 140 | 0 | 1 | 0 | 230 | 140 | 231 | 0 | 0 |
| Washer | 382 | 130 | 10 | 2 | 0 | 240 | 140 | 242 | 10 | 0 |
| Energy | 321 | 120 | 11 | 0 | 0 | 190 | 131 | 190 | 10 | 0 |
| Food | 675 | 163 | 32 | 94 | 0 | 386 | 185 | 490 | 21 | 0 |
| Family Care | 233 | 120 | 11 | 12 | 0 | 90 | 131 | 102 | 10 | 0 |

Every replay safety/audit check passed. The eight accepted Phase 4 live-run
lifecycle/transport and safety/audit gates remained zero when revalidated.
This task adds no fresh lifecycle/transport device observation; those zero
values refer to immutable accepted records and replay checks.

## Limits and readiness

Many activation effects remain UNKNOWN and blocked. Lexical risk with observed
activation capability is a conservative MEDIUM-confidence candidate; it is
not proof of an actual dangerous effect. Reviewed configured effect contracts
are needed to distinguish additional benign controls. A misconfigured trusted
effect provider remains a risk for future activation rollout; the default has
no such broad rules. New unsafe or unknown controls never become SAFE through
absence of a lexical match.

Shadow validation establishes bounded behavior on the recorded populations and
independent cases, not complete dangerous-flow coverage. Live controlled
enforcement and complete safe-navigation recovery were not tested or added.
These limits do not prevent the classification foundation from closing.

```text
OVERALL_VERDICT=PHASE5A_SAFE_ACTION_CLASSIFICATION_PASS_WITH_LIMITATIONS
PHASE5A_COMPLETE=YES
READY_FOR_PHASE5B=YES
PHASE5B_IMPLEMENTED=NO
DEFAULT_PRODUCTION_SMART_TRAVERSAL=OFF
DEFAULT_SAFE_ACTION_ENFORCEMENT=OFF
```

Artifacts: `../phase5a_safe_action_20261011/` contains final report, source and
test manifests, every replay, shadow candidate records/step comparisons,
independent expectations, and safety-chain evidence. Phase 5B may use this
foundation for bounded safe-navigation execution work while preserving the
recorded conditions and default policy.
