# Korean i18n Migration Runbook

This document summarizes the ko-KR TalkBack/UI migration for the Python runner.
The Android helper and SMART_NEXT behavior were intentionally left unchanged.

## Scope

The migration keeps the existing traversal flow and adds locale-aware matching in
small layers:

- `tb_runner/label_matcher.py` centralizes aliases, normalization, matcher modes,
  and canonicalization.
- Bottom navigation and selected tab verification use locale-neutral canonical
  tabs.
- Overlay matching recognizes scoped More options, Dismiss, and Navigate up
  labels without changing overlay traversal.
- Local tab matching has its own domain so plugin tabs do not collide with
  global bottom tabs.
- Entry/open verification remains scenario scoped and uses stable title/content
  evidence only.
- `tools/runtime_report_parser.py` supports semantic expected-label groups with
  English and Korean aliases.

## Alias Policy

Runner aliases must represent stable identity or stable scoped content evidence.

Allowed examples:

- Stable title or identity: `Home`, `홈`, `Life`, `라이프`, `Home Monitor`,
  `홈 모니터`, `Video`, `비디오`, `SmartThings settings`, `스마트싱스 설정`.
- Scoped content evidence: `Outdoor air quality`, `실외 공기질`,
  `Sync your lights with music`, `조명을 음악에 어울리도록 동기화`.

Do not use dynamic or stateful text as target, strict entry phrase, or verify
token:

- Time, count, status, usage, empty-state, or refresh text.
- Device-specific labels or user data.
- Generic CTA labels such as `Start`, `확인`, `닫기`, unless they are already
  constrained by a negative-verify or overlay-specific path.

Parser aliases can be broader than runner verify aliases only when they remain
scenario scoped and protected by the parser threshold. Parser-only aliases must
not be copied into runner target or verify fields without runtime evidence.

## Domains

Keep matcher domains separate:

- `bottom_tab`: global navigation only. For example, Korean `자동화` maps to the
  global Routines tab here.
- `local_tab`: plugin-local tab strips only. For example, Plant local-tab
  `자동화` is a local routines tab and must not be treated as the global bottom
  tab.
- Overlay: More options, Dismiss, and Navigate up recognition only. Overlay flow,
  fingerprinting, and recovery should remain unchanged.
- Entry verify: scenario-scoped plugin/open verification. Avoid broad global
  buckets.
- Parser: semantic expected-label groups for log baseline checks.

## Clean Start

Use the clean-start utility before runtime smoke runs:

```powershell
python tools/clean_start_smartthings.py
```

The utility is locale-independent and package-based. It sends HOME, force-stops
Play Store and SmartThings, launches `SCMainActivity`, re-cleans Play Store if
needed, and confirms SmartThings is foreground. This prevents Play Store
InAppReview focus contamination from causing false `no_bottom_nav_candidates`
or unrelated foreground failures.

## Smoke Tiers

Use small smoke tiers while editing, then full smoke before release.

1. Representative smoke: `global_nav_main`, `settings_entry_example`, and a few
   representative Life plugins such as Air, Energy, and Plant.
2. Expanded smoke: add plugin families likely to expose overlay, local tab, or
   verification gaps.
3. Remaining plugin smoke: run only plugins with unknown labels to collect real
   target/verify/parser evidence.
4. Full smoke: all main tabs, settings, and all Life plugins.

When adding a new plugin or locale alias, first collect real runtime labels from
the plugin card and opened screen. Add stable title/identity aliases only, run a
targeted smoke, then include the plugin in the next full smoke.

## Final Validation

The migration was validated with ko-KR and English full smoke runs:

- ko final full smoke:
  `output/i18n_pr18_ko_final_full_smoke_20260510_123600.normal.log`
- en final full smoke:
  `output/i18n_pr22_en_final_full_smoke_20260510_172435.normal.log`

Both runs reached plugin entry/open verification for the Life plugin set and
parser baselines were brought to pass. Global nav, settings, overlay recovery,
and local tab signals remained present.

## Known Issue

`life_music_sync_plugin` can stop with `repeat_no_progress` after entry/open
verification succeeds. The parser baseline also passes. Treat this as a separate
traversal quality issue, not a ko-KR i18n blocker.
