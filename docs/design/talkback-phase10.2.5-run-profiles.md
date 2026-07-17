# Phase 10.2.5 Run Profiles and Validation Readiness

## 1. Run Profiles

The Run screen provides three frontend-only profiles. A profile maps to the existing
Run start request fields; it does not add a new backend field or alter `RunSpec`.

| Profile | Launch | Mode | Coverage | Traversal | Evidence | Profiler | Identity V2 | Legacy shadow |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full Validation | Clean | Selected Full | On | On | On | On | On | Off |
| Quick Smoke | Clean | Selected Smoke | Off | On | On | On | On | Off |
| Custom / Debug | Preserved | Preserved | Editable | Editable | Editable | Editable | Editable | Dev-only editable |

Full Validation and Quick Smoke are read-only presets. Custom / Debug preserves
the current values and unlocks individual launch, mode, and diagnostic controls.
Language selection remains independent of the profile.

## 2. Default Strategy

Full Validation is the initial profile. Its defaults prevent a complete scenario
selection from being accidentally submitted with `mode=smoke`, which would make
the resulting run ineligible as a full baseline candidate.

Scenario selection remains a separate, explicit operator choice. The existing
initial `global_nav_main` selection and scenario presets are unchanged. Therefore,
the initial screen can correctly show `NOT READY` until All Scenarios is selected.

## 3. Validation Readiness

Validation Readiness is a pre-run operational indicator, not an approval decision
and not a replacement for offline candidate validation.

`READY` requires all candidate-impacting inputs that the Run screen can know:

- Mode is Full.
- The selected scenario count equals the current scenario registry count.
- Runtime Coverage Probe is enabled.
- Evidence Ledger is enabled.
- Runtime Profiler is enabled.
- Identity Shadow V2 is enabled.
- The production Traversal Engine is enabled.

`NOT READY` lists only failed conditions from this set. Launch mode, language,
Legacy Shadow Validation, device selection, and presentation-only settings are not
reported as candidate readiness reasons.

Repository cleanliness, EnvironmentFingerprint completeness, reconciliation,
artifact digests, terminal scenario state, and contract validity are only known
after or during collection. They remain authoritative offline validation gates and
are intentionally not predicted by this UI.

## 4. Smoke Confirmation

Every Run-button submission with `mode=smoke`, including Custom / Debug smoke
runs, opens a modal confirmation:

> Smoke Run은 빠른 확인을 위한 실행이며  
> 정식 검증 결과로 사용되지 않습니다.
>
> 계속 실행하시겠습니까?

`Cancel` closes the dialog without a request. `Run Smoke` continues through the
existing single-device or batch start path. No backend bypass is introduced.

## 5. Legacy Visibility Policy

Legacy Shadow Validation remains implemented and its request field is unchanged.
The control is hidden in production builds. It is visible when either:

- the Vite development environment is active (`import.meta.env.DEV`), or
- `VITE_SHOW_LEGACY_SHADOW_VALIDATION=true` is explicitly supplied.

Even when visible, it is editable only in Custom / Debug and only for Full mode.
Both preset profiles force it off.

## 6. Effective Locale

When the existing run status or runtime dashboard supplies `device_locale`, the
Current option is rendered as `Current (ko-KR)`, `Current (en-US)`, or the
reported normalized locale. Before a locale has been observed it remains
`Current`. No locale endpoint or request schema was added.

## 7. Compatibility

The implementation changes only frontend state orchestration and presentation.
The following contracts are unchanged:

- `/api/run/start` and `/api/batch/start` request payloads
- backend request models
- `RunSpec` and subprocess environment mapping
- runtime configuration
- traversal, evidence, coverage, identity, and recovery behavior
- candidate, comparison, baseline, and repository contracts

All profile and option controls, device selection, language selection, scenario
selection, and presets are disabled while a single run or batch run is active.
The existing Stop path remains available.

## 8. Migration

Operators now land on Full Validation instead of Selected Smoke. Existing debug
workflows should select Custom / Debug before changing Warm, mode, Coverage,
Profiler, Identity, Traversal, or Evidence options. Legacy Shadow users must run
the frontend in development mode or set the explicit Vite visibility flag.

No saved backend configuration requires migration. Existing clients that call the
Run APIs directly are unaffected.

## 9. Verification

Frontend unit coverage verifies profile mappings, Custom preservation behavior,
Quick Smoke readiness, individual readiness reasons, full READY state, and
effective locale labels. Source-level UI regression tests verify the modal text
and buttons, development-only Legacy visibility, default profile wiring, and
single/batch execution locks. Existing backend runner, device locale, shadow
validation, runtime selection, and `RunSpec` tests remain the contract regression
suite.
