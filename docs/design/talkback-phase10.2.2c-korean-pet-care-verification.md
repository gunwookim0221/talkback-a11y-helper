# Phase 10.2.2C: Korean Pet Care verification

## Problem

Korean Pet Care reaches the selected card and Pet Care screen, but the
post-open verification vocabulary contained only English Pet Care terms plus
`반려` and `펫 케어`.  The current Korean screen can expose neither of those
terms in the post-open snapshot, causing `post_open_verify_miss` before
traversal.

## Artifact Evidence

In `batch_20260716_082517`, the card transition succeeds and the post-open
snapshot contains `프로필 추가` and `산책 시작`; the same log records
`verify_hit=false` and `entry_contract failed ... post_open_verify_miss`.
Historical Korean Pet Care traversal artifacts also record the exact
`산책 시작` CTA as a focused actionable control.

## Token Comparison

| Surface | Evidence | Verification result before fix |
| --- | --- | --- |
| English Pet Care | `PetCare Service Plugin`, `Pet Care`, `Add profile` | matched existing English tokens |
| Korean Pet Care | `프로필 추가`, `산책 시작`, `활동`, `케어` | no existing token matched |

## Verification Contract

Post-open verification lowercases and checks configured tokens against focus
fields and post-open visible text.  It remains an OR contract; this change adds
only one Pet Care-specific Korean control label and changes neither traversal
nor the verification implementation.

## Fix

Add the exact observed Korean Pet Care CTA `산책 시작` to
`life_pet_care_plugin.verify_tokens`.

## False Positive Analysis

`산책 시작` is present in the Korean Pet Care artifact as an actionable status
control.  Searches of retained Home, Settings, Air Care, Home Care, and
Clothing Care normal logs found no occurrence associated with those scenarios.
`프로필 추가` was intentionally excluded because profile vocabulary is less
specific; `시작`, `설정`, `추가`, and other generic controls are also excluded.

## Tests

Tests cover Korean success with the actual text, English Pet Care regression,
missing token, partial `산책` rejection, and representative Home/Settings/Air/
Home Care/Clothing/generic-start false positives.  Existing Pet Care and
post-open verification tests remain unchanged.

## Targeted Result

Korean targeted smoke `batch_20260716_215933` passed on SM-F741N (`ko-KR`).
The log records a successful XML transition, `verify_hit=true`,
`entry_contract success`, and 13 total steps.  Evidence reconciliation is
`PASS` with orphan count `0` and duplicate count `0`; the Pet Care profiler
JSON was written.  Coverage was disabled and profiler, evidence ledger,
identity shadow, and traversal identity were enabled.

The attempted English smoke `batch_20260716_220406` did not start: Samsung
locale preflight wrote `system_locales=en-US`, but effective locale remained
`ko-KR` and correctly required a manual language change.  It is a device
locale setup limitation, not a verification regression.

## Remaining Risk

The Korean UI may change its Pet Care CTA wording.  A future vocabulary change
must be supported by newly captured UI evidence and the same false-positive
review; no locale bypass is used.

## Full Run Readiness

Korean targeted entry, traversal, evidence reconciliation, profiler, and
terminal checks pass.  A manually switched English device smoke remains
required before a Full Run can be considered fully ready.  This phase does not
run a Full Run or create a Candidate.
