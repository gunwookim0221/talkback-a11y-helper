# Device Plugin Audit V4 XML Coverage Design

## 한국어 요약 (Korean Summary)

### 목적
Audit V4는 기존의 **하드코딩된 예상 텍스트(Expected Content) 기반**으로 작동하던 Audit V3의 한계를 극복하기 위해 설계되었습니다. V4의 핵심 목표는 런타임에 수집된 **실제 단말의 XML UI 덤프**를 분모(Candidate)로 삼고, **실제로 TalkBack Focus가 이동한 노드**를 분자(Visited)로 삼아 **동적인 실제 순회 커버리지(Traversal Coverage)**를 산출하는 것입니다.

### 필요성
기존 V3에서는 특정 모델(예: Motion Sensor)에 온도나 진동 센서 텍스트가 기대(Expected Content)되더라도, 그것이 **순회 엔진(Runner)의 버그로 누락된 것**인지, **해당 단말/모델의 UI 자체에 렌더링되지 않은 것**인지 구분할 수 없어 억울한 `REVIEW` 판정이 발생했습니다. V4는 실제 화면에 존재하는 XML 데이터만을 기준으로 평가하므로 False Positive를 획기적으로 줄일 수 있습니다.

---

## 1. Overview

The Device Plugin Audit tool has evolved through several iterations to ensure robust TalkBack traversal coverage in SmartThings device plugins:

*   **Audit V1**: Initial concept verifying simply whether a scenario ran without crashing.
*   **Audit V2**: Introduced local tab discovery. Checked if all detected tabs within a device plugin were visited and if traversal exhausted the viewport.
*   **Audit V3**: Implemented `PLUGIN_EXPECTED_CONTENT` rules. Evaluated traversal by cross-referencing hardcoded expected strings (Required / Review Expected) with the actual text dumped in logs and `.xlsx` artifacts.
*   **Audit V4 (Current Design)**: Shifts the paradigm from "Expected Content" to "Actual Rendered Content." Uses Android UI Automator XML dumps to dynamically establish what is currently on the screen, comparing it directly to what the runner successfully focused on.

## 2. Problem Statement

The fundamental limitation of Audit V3 lies in its reliance on static expected lists.

**Example: Motion Sensor Plugin**
*   **Expected Content**: `Temperature`, `Vibration sensor`
*   **Limitation**: If a specific motion sensor model only supports motion and battery features, these elements are entirely absent from the UI.
*   **Outcome**: V3 incorrectly flags the traversal as `REVIEW` due to missing expected content, even though the runner perfectly traversed every visible node. We cannot programmatically verify if the missing content was due to a traversal bug or legitimate UI absence without looking at the raw XML. This leads to False Reviews.

## 3. Audit V4 Vision

The vision for Audit V4 is an automated gap analysis based purely on ground truth:

```text
XML Candidate (What is actually on the screen)
↓
Traversal Coverage (What was actually focused)
↓
Gap Analysis (What is visible but skipped)
↓
Verdict (PASS / REVIEW based on Coverage)
```

## 4. XML Data Source

To achieve this, Audit V4 relies on XML dumps generated during the runner execution.

*   **Current Origin**: XML dumps are created dynamically in `tb_runner/collection_flow.py` and `tb_runner/plugin_probe.py` using `uiautomator dump /sdcard/window_dump...xml`.
*   **Contained Data**:
    *   `text`: Visible string values.
    *   `content-desc`: Accessibility labels.
    *   `resource-id`: Component identifiers.
    *   `bounds`: Positional coordinates `[x1,y1][x2,y2]`.
    *   `focusable`, `clickable`, `scrollable`: Accessibility properties.

## 5. XML Capture Strategy

**Phase 1 Goal: Persistent XML Preservation by Runner**
Currently, dumps are stored in `.tmp/` and subsequently discarded. The runner must be modified to persist these files.

*   **Storage Path**: `output/<run_id>/<scenario_id>/xml_dumps/`
*   **File Naming Convention**:
    *   `step_000_entry.xml`
    *   `step_005_controls.xml`
    *   `step_012_routines.xml`
    *   `step_020_history.xml`
*   **Capture Triggers**:
    1. Immediately after entering the device detail page.
    2. Immediately after switching to a new local tab (Controls, Routines, etc.).
    3. After every scroll event.
    4. Upon hitting the `viewport_exhausted` boundary.

## 6. Candidate Extraction Strategy

The raw XML must be filtered to define the "Denominator" (the valid targets TalkBack should read).

**Include (Valid Targets):**
*   Nodes with non-empty `text` or `content-desc`.
*   Nodes with meaningful `resource-id`s that indicate actionable status.

**Exclude (Ignored Targets):**
*   Empty layout containers (e.g., `FrameLayout`, `LinearLayout` without text/description).
*   System UI (Status bar, Navigation bar).
*   Non-visible or off-screen nodes (bounds validation).
*   Duplicate nodes across multiple scroll steps (requires Node Merge/Deduplication logic based on stable IDs/bounds).

## 7. Coverage Calculation

Once candidates are extracted, V4 calculates the final coverage metric.

*   **Denominator (Candidate)**: Unique, valid accessibility targets derived from merged XML dumps.
*   **Numerator (Visited)**: Elements successfully focused during traversal, derived from `.normal.log` and `.xlsx` artifacts.

**Result Example**:
```text
Candidate: 20
Visited: 17
Coverage: 85% (3 Missing Nodes)
```

## 8. Phase Plan

*   **Phase 1**: XML Capture Only
    *   Modify `tb_runner` to persist XML dumps into `output/`. No changes to V3 Verdict logic.
*   **Phase 2**: Candidate Merge
    *   Develop an XML parsing module in `audit_device_plugins.py` to merge multiple XML dumps per tab and extract a unique node list.
*   **Phase 3**: Coverage Metric
    *   Map extracted XML candidates to actual `.xlsx` traversal logs and generate the percentage score.
*   **Phase 4**: Verdict Integration
    *   Replace V3's missing content rules with the new Coverage score threshold to determine PASS or REVIEW.

## 9. Risks

*   **XML Over-Detection (False Negatives)**: Including background layers, hidden elements, or containers that TalkBack ignores will artificially inflate the denominator, leading to false `REVIEW`s.
*   **Dynamic Loading**: XML capture timing might miss elements that load asynchronously.
*   **Duplicate Nodes**: Scrolling often captures overlapping elements. A robust deduplication mechanism using bounds and identifiers is strictly required.
*   **TalkBack Non-Targets**: Android sometimes presents elements in XML that are programmatically hidden from accessibility services (`importantForAccessibility="no"`).

## 10. Success Criteria

The ultimate success of V4 is measured by its accuracy in distinguishing UI gaps from traversal bugs, using the Motion Sensor as a benchmark:

**Case A (Single-Function Sensor):**
```text
Temperature text is absent in expected logic.
Temperature node is absent in XML dump.
Coverage is 100%.
Result: PASS
```

**Case B (Multi-Function Sensor with Traversal Bug):**
```text
Temperature node exists in XML dump.
Temperature text is absent from Traversal logs (.xlsx).
Coverage is <100%.
Result: REVIEW (with specific missing XML bounds/text reported)
```
