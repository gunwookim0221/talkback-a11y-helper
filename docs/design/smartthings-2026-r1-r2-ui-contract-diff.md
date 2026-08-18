# SmartThings 2026 r1/r2 UI Contract Diff

## 1. Purpose

This document records the evidence-backed SmartThings Home UI contract used by the TalkBack runner for the 2026 r1-to-r2 transition. It separates observed UI facts from compatibility strategy and from items that remain unknown.

This is a historical design record. It was produced from repository source, Git history, and completed historical Run artifacts only. It is not a live-device validation report.

## 2. Scope and provenance

The comparison uses the following completed artifacts:

- r1 reference: `qa_frontend_runs/batch_20260608_233133`, device `SM-F741N`, serial token `R3CX40QFDBP`.
- r2 reference: `qa_frontend_runs/batch_20260817_102013`, device `SM-F741N`, serial token `R3CX40QFDBP`.
- r2 transition context: `qa_frontend_runs/batch_20260817_021109`, used for completed-run status and environment metadata where useful.

The r2 environment profile directly records SmartThings `1.8.51.14` / version code `185114010`, package `com.samsung.android.oneconnect`, locale `ko-KR`, Android 15, One UI 7.0, and TalkBack `15.1.01.1`. The r1 artifacts do not contain a target-app release/version field; the r1 SmartThings version is therefore `UNKNOWN`.

The latest repository source is `ab7f03092b4b5baa2f1ca9ddcb35a4dbd7bf74c2`. The r2 historical environment profile was captured at `ad442c02ed047a90000bff40ecae4562fd48ae46`; this explains why the historical r2 run still contains the pre-final settings target attempt. No current or in-progress Run artifact was read.

## 3. Executive summary

The r1 Home UI exposes five bottom-navigation controls through stable resource IDs. The r2 Home UI retains the same five logical destinations but exposes the actionable tab items as resource-id-free `android.widget.LinearLayout` nodes. Their Korean semantic labels and common bottom-row geometry are the stable r2 contract.

The r2 selected state is not always preserved in the helper's flattened accessibility dump. The contract is therefore layered: use the helper semantic candidate after a successful touch when available, then verify raw UIAutomator XML `selected="true"` for the expected bottom-tab label. A TalkBack announcement containing `Selected`/`선택됨` remains valid when present.

Devices also keeps semantic matching at the boundary: the selected location is `모든 기기`, the alternate location is `어디서나 사용`, and device cards are actionable `FrameLayout` containers with stable card IDs and descendant names/statuses. Device names must be normalized independently of state suffixes and update metadata.

Menu settings changed from the r1 `setting_button_layout` target to an r2 actionable `badge_container` with a `settings_image` child and the stable label `설정`. The legacy ID remains a compatibility-first path, but stable-label resolution must promote a matching non-actionable child to its actionable parent.

## 4. Resource-ID changes

### UNCHANGED

- `com.samsung.android.oneconnect:id/device_card` and `device_card_camera`: present in the pre-r2 source contract and directly observed in the r2 Devices XML as clickable/focusable `android.widget.FrameLayout` cards.
- `com.samsung.android.oneconnect:id/tab_title`: remains a header control, not a bottom-navigation contract. It is intentionally excluded from broad `menu`/`more` navigation matching.
- The logical destination order remains Home, Devices, Life, Routines, Menu.

### REMOVED_IN_R2

- `com.samsung.android.oneconnect:id/menu_favorites`
- `com.samsung.android.oneconnect:id/menu_devices`
- `com.samsung.android.oneconnect:id/menu_services`
- `com.samsung.android.oneconnect:id/menu_automations`
- `com.samsung.android.oneconnect:id/menu_more`
- `com.samsung.android.oneconnect:id/setting_button_layout` as the directly observed r2 Settings node.

These IDs are removed from the observed r2 actionable Home/Menu surface, not from the shared compatibility configuration. The r1 resource-ID path remains available for r1 devices and older UI surfaces.

### CHANGED_IN_R2

- Bottom-navigation addressing changes from resource-ID matching to semantic item matching when no known bottom-navigation resource ID is present.
- Bottom-navigation item class changes from the r1 resource-addressable button surface observed in logs to r2 resource-id-free `android.widget.LinearLayout` items. The r2 item contains a `ViewGroup`, icon `ImageView`, and title `TextView`; Menu may also contain `sesl_badge_dot`.
- Settings targeting changes from direct `setting_button_layout` focus/click to stable-label lookup that resolves the actionable `badge_container` parent.
- Selected-state verification changes from TalkBack announcement/resource selection alone to a layered helper/semantic/raw-XML contract.

### NEW_IN_R2

- `com.samsung.android.oneconnect:id/badge_container`: actionable r2 Settings parent, `android.widget.ImageButton`, content description `설정` in the retained raw XML.
- `com.samsung.android.oneconnect:id/settings_image`: r2 Settings child, `android.widget.ImageButton`, content description `설정`; it is not the preferred parent target when the parent is actionable.
- `com.samsung.android.oneconnect:id/sesl_badge_dot`: non-actionable Menu badge node with content description `새 콘텐츠 사용 가능`.
- `com.samsung.android.oneconnect:id/subheader_card`: r2 Devices section node observed with `펼쳐짐 어디서나 사용`; it is a section/filter surface, not a device-card entry target.

### SEMANTIC_ONLY_IN_R2

- Bottom-navigation item labels observed in the r2 XML are `홈`, `기기`, `라이프`, `자동화`, and `메뉴, 새 콘텐츠 사용 가능`.
- The r2 item row is identifiable by five same-row semantic candidates, `android.widget.LinearLayout`, non-empty label, focusability, visibility, and common bounds. A fixed resource ID is not required.
- `모든 기기`, `어디서나 사용`, `연기`, `누수`, and state-bearing labels such as `연기 감지됨` are semantic device-surface inputs.

## 5. Bottom navigation: Home, Devices, Life, Routines, Menu

| Destination | r1 observed contract | r2 observed contract | Selected-state evidence | Automation strategy |
|---|---|---|---|---|
| Home | `menu_favorites`; resource-addressable button path; `Selected, Home, Tab 1 of 5.` | No item resource ID; `LinearLayout`, label `홈`, bottom row | r1 TalkBack `Selected`; r2 raw XML parent/descendant `selected=true` when Home is selected, otherwise semantic verification | Resource ID first; otherwise semantic bottom-row candidate and label alias |
| Devices | `menu_devices`; `Devices, Tab 2 of 5.` | No item resource ID; `LinearLayout`, label `기기` | r1 announcement; r2 Devices XML parent/descendant `selected=true` | Same dual path |
| Life | `menu_services`; `Life, Tab 3 of 5.` | No item resource ID; `LinearLayout`, label `라이프` | r1 announcement; r2 raw XML `selected=true` is used by Life reset verification | Resource ID first; semantic selection; raw XML selected fallback |
| Routines | `menu_automations`; `Routines, Tab 4 of 5.` | No item resource ID; `LinearLayout`, label `자동화` | r1 announcement; r2 semantic match plus raw XML selected fallback | Same dual path |
| Menu | `menu_more`; `Menu, Tab 5 of 5., New content available` | No item resource ID; `LinearLayout`, label `메뉴, 새 콘텐츠 사용 가능`, with optional `sesl_badge_dot` | r1 announcement; r2 Menu XML parent/descendant `selected=true` | Semantic label must win over the badge child and the header `tab_title` |

The r1 logs show the bottom resource IDs and `android.widget.Button` action targets. The r2 raw XML shows a bottom row around y=2316 to y=2460 with five `android.widget.LinearLayout` items and no item resource ID. The source implementation reflects this split in `tb_runner/bottom_nav.py`, `tb_runner/tab_logic.py`, and `tb_runner/context_verifier.py`.

## 6. Selected-state contract

The selected-state verification order is:

1. Preserve the r1 resource-ID and TalkBack announcement path when it is available.
2. For r2, annotate a same-row semantic bottom-navigation group using class, bounds, focusability, visibility, label, and expected count.
3. Select the semantic item by bounds or semantic accessibility selection.
4. Verify the expected destination from the selected semantic candidate or focus payload.
5. If the helper dump has no reliable selected marker, call the raw UIAutomator XML fallback and accept only a node with `selected="true"` whose label canonicalizes to the expected destination.

The XML fallback parses `text`, `content-desc`, class, resource ID, bounds, `clickable`, `focusable`, `selected`, and `visible-to-user`. It removes its temporary remote dump after reading. The fallback is verification-only; it does not broaden a candidate into an arbitrary header or content node.

## 7. Devices contract

### Location/filter surface

The r2 Devices entry XML directly shows:

- `모든 기기`: no item resource ID, `android.widget.LinearLayout`, focusable, `selected=true` in the captured Devices state.
- `어디서나 사용`: no item resource ID, `android.widget.LinearLayout`, clickable and focusable, `selected=false` in the same capture.
- `com.samsung.android.oneconnect:id/subheader_card`: `android.view.ViewGroup`, content description `펼쳐짐 어디서나 사용`, representing a section/filter header rather than a device card.

The matcher must prefer explicit `selected`, `checked`, or selected state-description signals. It may use the non-clickable selected chip or the only candidate as a conservative fallback, but it must not infer selection from a device card.

### Device cards and entry targets

The r2 XML directly shows `device_card` and `device_card_camera` as clickable/focusable `android.widget.FrameLayout` containers. The first visible card sample contains `device_name` text `연기` and `device_status` text `연기 감지됨`; another contains `device_name` text `누수`. The parent card is the entry target. A descendant match may be promoted to its containing actionable card.

Stable labels are produced by removing duplicated merged words, state suffixes (`감지됨`, `연기 감지됨`, `offline`, `last updated`, and similar observed forms), and update metadata. The card's state and metadata are not part of the identity key. The source contract is in `tb_runner/device_tab_logic.py` and the entry/tap promotion path is in `tb_runner/collection_flow.py`.

Observed English device-surface labels include `Smoke`, `Leaks`, and `거실 홈카메라 360 Offline` in the r1 historical logs/crops. Observed Korean labels include `연기`, `연기 감지됨`, `누수`, `모든 기기`, and `어디서나 사용` in the r2 raw XML/logs. English strings in the runtime config remain compatibility aliases; they are not claims about the r2 rendered locale.

## 8. Life tab and Life-card hierarchy

The global Life tab follows the same r1/r2 bottom-navigation contract and is reset before plugin traversal. The r2 completed-run logs record successful Life re-selection and fresh verification with `life_selected_source='window_xml_selected'`.

Direct r2 XML samples show that Life service screens do not have one universal card resource ID. Examples include:

- `android.view.View` roots such as `DynamicSummaryCard`, `DynamicSummaryCardView`, and `DynamicSummaryCardViewList` with actionable descendants.
- `android.widget.LinearLayout` `llCard` or service-specific `dashboard_*_unit` roots with descendant title TextViews.
- An actionable parent can be a layout while the visible service name is a descendant TextView, so semantic title plus actionable-parent promotion is required.

The completed r2 artifacts directly contain labels `에어 케어` and `파인드` on a Life-related screen, but they do not establish a stable standalone `life_air_care_plugin` or `life_find_plugin` entry contract. `life_pet_care_plugin` has no direct target-card XML contract in the selected completed artifact. Those three plugin-specific contracts remain UNKNOWN beyond the observed labels and scenario availability results.

Life reset must verify that the global navigation is visible, the Life tab is selected, and the fresh screen is a Life list. A missing plugin card list is a soft condition in the current policy when the selected Life tab and list structure are verified; it is not permission to treat an unrelated screen as Life.

## 9. Settings/Menu contract

### r1

The r1 Settings path targets `com.samsung.android.oneconnect:id/setting_button_layout`, observed as `android.widget.RelativeLayout`, focusable, with TalkBack announcement `Settings, New content available, Button Settings`. The historical log shows resource focus followed by click/fallback tap and verified entry.

### r2

The r2 Menu XML has no `setting_button_layout`. It has:

```text
badge_container  android.widget.ImageButton  clickable=true  focusable=true  content-desc="설정"
└── settings_image android.widget.ImageButton clickable=true focusable=false content-desc="설정"
```

The current configuration keeps the r1 target as the first compatibility path and adds `target_stable_labels: ["Settings", "설정"]`. The current resolver searches a fresh tree, matches a stable label, promotes a non-actionable matching child to an actionable parent, prefers a resource-addressable parent when available, and taps the resolved bounds. It also parses both normal bounds and UIAutomator bracket bounds.

### Legacy header false positive

The r2 UI still contains `com.samsung.android.oneconnect:id/tab_title`, an `android.widget.Spinner` with content description `talkback test room, , Double tap to open menu`. A broad `.*menu.*` matcher can select this header instead of the bottom Menu item. The current tab matcher rejects a candidate for an expected bottom tab unless it is a known bottom-navigation resource, an explicitly matching resource, or an annotated semantic bottom-row item. This preserves the header as content chrome and prevents a legacy header touch.

## 10. Hierarchy comparison

| Surface | r1 | r2 | Contract consequence |
|---|---|---|---|
| Bottom row | Resource-addressable button targets observed in logs; complete parent hierarchy not retained | Root bottom row `LinearLayout`; five item `LinearLayout`s; each has `ViewGroup`, icon, title; Menu may add badge dot | Use resource ID first, semantic same-row annotation second |
| Selected tab | TalkBack `Selected`/tab announcement and resource action | Helper dump may omit selected; raw XML exposes `selected=true` on expected item/descendants | Use raw XML as selected-state verification fallback |
| Devices location | Historical r1 raw hierarchy not retained; shared config used English target aliases | `LinearLayout` location chips without item IDs; selected state is explicit | Match normalized labels and selection signals |
| Device card | Pre-r2 source contract contains `device_card`/`device_card_camera`; historical r1 raw hierarchy not retained | Actionable `FrameLayout` card IDs with descendant names/status | Tap/promote actionable card parent; strip state text |
| Settings | `setting_button_layout` `RelativeLayout` | `badge_container` `ImageButton` with `settings_image` child | Stable-label parent resolution with legacy ID first |
| Header | `tab_title` is shell/chrome | `tab_title` remains a clickable `Spinner` with menu wording | Exclude from generic bottom-nav matching |

## 11. Semantic labels observed

| Meaning | r1 observed | r2 observed | Notes |
|---|---|---|---|
| Home | `Home`, `Selected, Home, Tab 1 of 5.` | `홈` | English is also a configured alias for compatibility |
| Devices | `Devices`, `Devices, Tab 2 of 5.` | `기기` | Same logical destination |
| Life | `Life`, `Life, Tab 3 of 5.` | `라이프` | Same logical destination |
| Routines | `Routines`, `Routines, Tab 4 of 5.` | `자동화` | Same logical destination |
| Menu | `Menu, Tab 5 of 5., New content available` | `메뉴, 새 콘텐츠 사용 가능` | Badge announcement is part of the r2 label |
| Settings | `Settings, New content available, Button Settings` | `설정` | Stable-label lookup uses `Settings` and `설정` aliases |
| All devices | `UNKNOWN` in retained r1 raw evidence | `모든 기기` | Source matcher supports `all devices` as an alias |
| Anywhere use | `UNKNOWN` in retained r1 raw evidence | `어디서나 사용` | Section/header and location semantic surface |
| Device smoke | `Smoke` | `연기`, `연기 감지됨` | State suffix is removed from identity |
| Device leak | `Leaks` | `누수` | State-bearing variants are normalized |

## 12. Automation compatibility matrix

| Automation operation | r1 path | r2 path | Required verification |
|---|---|---|---|
| Select Home/Devices/Life/Routines/Menu | `resource_id` first | semantic bottom-row item; no fixed item ID | expected canonical destination; raw XML selected fallback when needed |
| Verify selected tab | TalkBack announcement/resource focus | semantic candidate, focus payload, then `selected=true` XML | expected label must match selected item |
| Enter Devices | global tab selection | global tab selection | location surface must be detected after entry |
| Select `모든 기기` | configured English/legacy aliases | semantic label plus explicit selection signal | never use device-card selection as location selection |
| Enter device card | known card ID/bounds | known card ID/bounds, descendant promotion | actionable parent and safe tap point |
| Reset to Life before Life/plugin work | resource-ID Life reselect | resource-ID first, semantic Life fallback, fresh XML verification | global nav visible and Life list state verified |
| Enter Settings | `setting_button_layout` | legacy ID first, then `Settings`/`설정` stable-label parent resolver | post-click screen transition confirmation |
| Select Menu | `menu_more` | semantic `메뉴` item | reject `tab_title` header false positive |

## 13. r1 compatibility preservation

The compatibility design is intentionally dual-path:

- Known r1 bottom-navigation resource IDs remain the highest-priority match and action path.
- The semantic path activates only for a known bottom-row shape or an explicit matching resource. A generic content/header node cannot trigger legacy bottom-tab touch.
- The r1 Settings resource target remains in runtime configuration. Stable-label resolution is additive and is used when the legacy target is absent or not matched.
- Existing crash and traversal policies are outside this UI-contract document and were not changed by this documentation task.

## 14. Known non-UI and evidence limitations

- The r1 SmartThings app version, Android version, One UI version, TalkBack version, and raw r1 XML snapshots are not present in the selected r1 artifact. They are `UNKNOWN`, not inferred from the calendar date.
- The r2 `life_air_care_plugin`, `life_pet_care_plugin`, and `life_find_plugin` entries do not have a complete stable target-card contract in the selected completed artifact. Observed labels do not prove plugin-specific entry identity.
- Historical r2 batch `batch_20260817_021109` has a scenario-level failed status in its device summary even though its batch/device lifecycle completed; it is used only as transition context, not as sole pass evidence.
- Artifact labels and current source contracts describe tested surfaces, not all future SmartThings cards or locales.
- No current Full Run state, artifact contents, device state, or live helper state was inspected.

## 15. r3 lessons and evidence confidence

For a future UI revision, capture raw XML together with the helper dump for every navigation/settings/filter boundary, record the target-app version in every Run, and keep the actionable parent and semantic child relationship explicit. A five-item same-row semantic contract is more durable than a guessed resource ID, but it must remain bounded by geometry, class, visibility, focusability, and post-action context.

Confidence labels used here:

- `CONFIRMED`: directly present in raw XML, an artifact log payload, or current source plus matching historical evidence.
- `SUPPORTED`: supported by source history and multiple indirect historical observations, but a raw snapshot for one side is absent.
- `INFERRED`: a narrow interpretation explicitly marked as such; no critical automation target relies on it.
- `UNKNOWN`: evidence is absent or insufficient; no replacement value is guessed.

The machine-readable version of this contract is [smartthings-2026-r1-r2-resource-map.json](smartthings-2026-r1-r2-resource-map.json).
