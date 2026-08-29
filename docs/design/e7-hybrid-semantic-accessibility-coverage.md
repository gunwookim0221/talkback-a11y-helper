# E7 Hybrid Semantic Accessibility Coverage Closure

상태: E7 engineering closure with a known evidence limitation

범위: `device_washer_plugin` / Set temperature
기준 commit: `65e297c8f91aea363c5f04c27bf04e08e1d6843e`

## Approved policy

The **semantic target** is the primary coverage unit. A runtime accessibility
node is the evidence unit, while each traversal step and its order are
diagnostic units. Benign traversal-order differences do not fail semantic
coverage. Traversal remains a defect when it creates a focus trap, makes
required content unreachable, becomes pathological or cyclic, leaks across
cards, performs invalid navigation, performs a destructive action before its
context, or produces materially incorrect reading/focus ordering.

Evidence levels are:

- **Level A — DIRECT_RUNTIME_COVERAGE:** production traversal supplies
  strongly correlated real accessibility focus and/or announcement evidence.
- **Level B — DIRECT_ACCESSIBILITY_PROBE_COVERAGE:** an existing accessibility
  mechanism directly targets a real node and actual accessibility focus is
  confirmed.
- **Level C — COMPOUND_SEMANTIC_COVERAGE:** a focused compound representation
  exposes the target through strong same-runtime correlation, such as
  parent/child identity, bounds, transaction, event, or announcement.
- **Level D — STRUCTURAL_ONLY:** XML, Helper snapshots, candidates,
  representatives, resource IDs, class names, visual proximity, and
  same-card membership alone.

Structural-only evidence is not coverage. Compound coverage also requires
strong correlation; same-card membership or visual proximity alone is not
semantic correlation.

## Washer disposition

The Set temperature region was reached successfully.

| Semantic target | Final status | Evidence |
|---|---|---|
| `Set temperature` header | `COVERED` | Level A; production focus and announcement observed |
| Adjustable control | `COVERED` | Level B; real `android.widget.SeekBar` directly focused and post-focus identity matched |
| Current value / adjustable-state association (`95.0 ℉`) | `UNVERIFIED` | `KNOWN_EVIDENCE_LIMITATION` |

The directly focused `SeekBar` exposed no current value through its text,
content description, state description, range value, same-focus accessibility
event, or announcement. The visible `95.0 ℉` value is a separate card view.
It is therefore not independently required to receive focus, but its semantic
association with the adjustable node is not proven by this evidence.

This is not classified as a product accessibility defect or an automation
traversal defect. It is an explicit evidence limitation: the adjustable
control is proven accessible, while the current-value association is not.
The previous dynamic-value representative selection is excluded from E7
coverage proof and must not be treated as accessibility evidence. Further
slider/value instrumentation or another exact TalkBack identity investigation
is intentionally deferred because its engineering cost is disproportionate
to Full Validation readiness.

E7 is closed under this policy. No exact human TalkBack traversal order or
independent value focus is required for normal semantic coverage.
