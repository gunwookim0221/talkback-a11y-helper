# TalkBack Phase 10.2.1 — Device Classification Policy & Fingerprint Completion

상태: Implemented

범위: reviewed exact-model device-family/form-factor classification을 Environment Collector에
추가해 fresh Full Run 전 EnvironmentFingerprint completeness를 안전하게 만들기 위한 정책이다.
Comparator, Frontend, Candidate approval, baseline materialization, DB와 Full Run은 포함하지 않는다.

## 1. 목적

Phase 10.1A collector는 model과 fold/device-state evidence를 읽지만 `device_family`와
`form_factor`는 policy가 없어 MISSING이었다. 이 phase는 runtime model inference를 추가하지 않고,
versioned Git-tracked policy의 exact reviewed mapping과 ADB capability evidence를 교차 검증한다.

## 2. Capability와 Policy 책임 분리

ADB는 관측 사실만 담당한다.

- `ro.product.model`: exact model string
- `cmd device_state print-states`: supported state 목록과 foldable capability
- `cmd device_state print-state`: current posture
- `wm size`/`wm density`: physical/logical/override display evidence
- Android release/SDK 및 One UI property: platform evidence

Policy는 사람이 review한 semantic classification만 담당한다.

- exact model → stable `device_family`
- exact model → allowed `form_factor`
- expected foldable capability
- review status/reason/date

따라서 model name, prefix, substring 또는 marketing name으로 family/form factor를 추론하지 않는다.

## 3. Policy Schema

정책 파일은 [device_classification_policy.json](</D:/Python test/talkback-a11y-helper/config/device_classification_policy.json:1>)이며 schema는
`talkback-device-classification-policy-v1`이다.

```json
{
  "schema_version": "talkback-device-classification-policy-v1",
  "revision": 1,
  "devices": {
    "EXACT-MODEL": {
      "device_family": "stable-family-id",
      "form_factor": "foldable_phone",
      "expected_capabilities": {"foldable": true},
      "review": {
        "status": "REVIEWED",
        "reason": "review evidence",
        "reviewed_at": "YYYY-MM-DD"
      }
    }
  }
}
```

Loader는 duplicate JSON key, schema, positive integer revision, exact model-key format, family format,
allowed form factor, boolean expected capability, form/capability semantic agreement과 REVIEWED review를
검증한다. malformed/unreviewed policy는 INVALID이며 classification에 사용할 수 없다. Canonical JSON
SHA-256은 loader가 산출한다.

## 4. Exact Match 규칙

`devices[model]`의 dictionary key가 collector의 normalized exact `ro.product.model` value와 같을 때만
매칭한다. `SM-F741`, `SM-F741N-variant`, `xSM-F741N`은 모두 match가 아니며
`device_family`/`form_factor`를 MISSING으로 둔다. 현재 확인되지 않은 model은 policy에 추가하지
않는다.

## 5. Form Factor 판정

허용 enum은 `slab_phone`, `foldable_phone`, `tablet`, `wearable`, `tv`, `unknown`이다.
`unknown`은 policy schema에는 표현할 수 있지만 fingerprint COMPLETE를 위한 value로 사용하지 않으며
collector는 MISSING으로 처리한다.

정책 exact match만으로 device family는 AVAILABLE이 될 수 있다. Form factor는 ADB capability가
정책의 expected capability와 일치할 때만 AVAILABLE이다. Capability 자체가 MISSING이면 policy가
REVIEWED여도 form factor를 추정하지 않고 MISSING으로 유지한다.

## 6. Capability Cross-check

| Policy | ADB capability | device_family | form_factor |
|---|---|---|---|
| foldable policy | `true` | AVAILABLE | AVAILABLE |
| slab/non-foldable policy | `false` | AVAILABLE | AVAILABLE |
| foldable policy | `false` | AVAILABLE | INVALID |
| slab/non-foldable policy | `true` | AVAILABLE | INVALID |
| reviewed exact policy | MISSING | AVAILABLE | MISSING |
| invalid capability parser | AVAILABLE family | INVALID form factor |
| no exact policy match | MISSING | MISSING |

An INVALID form-factor critical family field makes EnvironmentFingerprint `UNUSABLE`; missing mapping or
unverified capability makes it `INCOMPLETE`.

## 7. Fingerprint 영향

`device_family`와 `form_factor` values는 existing fingerprint family source에 이미 포함되어 있다.
Policy source, revision, canonical policy hash, review reason과 capture time은 EnvironmentProfile
provenance/document digest에는 남지만 fingerprint source에는 포함하지 않는다. 따라서 policy revision
only 변경이 동일 classification을 계속 산출하면 EnvironmentFingerprint hash는 안정적이다. 실제 family
또는 form-factor value 변경은 fingerprint hash를 변경한다.

## 8. Unknown Model 처리

Unknown model은 error나 guessed family가 아니라 MISSING이다. Candidate builder는 이 상태를
INCOMPLETE fingerprint로 보고 NOT_ELIGIBLE로 만들며, manual baseline approval은 허용하지 않는다.
이것이 incorrect family sharing보다 안전하다.

## 9. Privacy

Policy provenance source는 schema/revision/canonical hash/exact-model marker만 포함한다. policy file의
absolute path, raw ADB serial 또는 raw device directory name은 source/reason에 저장하지 않는다.
Existing shared-profile redaction은 raw serial을 제거한다.

## 10. 현재 등록 모델

`SM-F741N`만 등록했다.

- family: `galaxy-z-flip6`
- form factor: `foldable_phone`
- 근거: 현재 project representative device에서 `cmd device_state`가 CLOSED/TENT/HALF_OPENED/OPENED
  states와 current OPENED state를 제공하는 local read-only smoke

확인되지 않은 `SM-S936B` 등은 등록하지 않았다.

## 11. Smoke 결과

2026-07-15 read-only smoke 결과:

- model: `SM-F741N`
- Android: 15 / SDK 35
- One UI: raw `70000`, normalized `7.0`
- fold capability: AVAILABLE `true`
- posture: AVAILABLE `OPENED`
- display: physical/logical 1080×2640, density 480
- device family: AVAILABLE `galaxy-z-flip6`
- form factor: AVAILABLE `foldable_phone`
- EnvironmentFingerprint: `COMPLETE`, missing/invalid field 없음

Full Run, Candidate build, approval 또는 baseline repository mutation은 수행하지 않았다.

## 12. Fresh Full Run 준비 상태

Environment capture 관점에서는 현재 device가 COMPLETE fingerprint를 만들 수 있다. Fresh Full Run
전에는 repository working tree를 clean commit 상태로 만들어야 한다. Commit SHA와 dirty=false는
Candidate approval eligibility의 별도 gate이며 fingerprint hash에는 들어가지 않는다.

## 13. Known Limitations

- device-state API가 없는 model은 reviewed mapping이 있어도 form factor를 AVAILABLE로 추정하지 않는다.
- policy hash chain은 reviewable provenance이며 signing/HMAC approval system은 아니다.
- active display role은 여전히 `UNKNOWN`이고 fold posture family splitting policy는 도입하지 않았다.
- HMAC serial token provider는 여전히 별도 future work다.
- policy는 online product database를 조회하지 않으며 수동 review Git diff가 필요하다.
