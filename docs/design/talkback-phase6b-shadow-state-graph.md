# TalkBack Phase 6B — Shadow State Graph

Phase 6B adds a versioned, observational graph projection. It does not schedule
actions or make production traversal decisions.

## Enablement and authority

`TB_STATE_GRAPH_MODE` accepts `OFF` or `SHADOW`. Missing or invalid values mean
`OFF`. In `SHADOW`, the runner reads only rows already collected by normal
traversal and writes a sibling `*.state_graph.json` artifact. It does not call
the device, request another hierarchy snapshot, issue an action, or mutate the
input rows. A graph error is logged and isolated from the traversal result.

Artifacts use `phase6-state-graph.v1`, identify the identity schema as
`phase6-state-identity.v1`, and include `authority=OBSERVATIONAL_SHADOW_ONLY`
and `decision_authority=NONE`.

## State identity

The state identity is a SHA-256 over a canonical JSON document containing:

- the verified Phase 3 logical context type and ID;
- observed package and activity;
- environment partition, when supplied;
- verified selected tab and persistent semantic markers;
- typed, non-unknown semantic substate values;
- observed overlay structure, when an overlay is present;
- a sorted structural viewport multiset using the existing `relative-grid32`
  layout buckets.

Viewport nodes retain resource ID, class, role, recognized semantic state,
selected/enabled/actionable flags, and relative layout bucket. Node multiplicity
is retained. Raw labels and speech, focus flags, dynamic observational text,
pixel offsets, timestamps, request IDs, attempt history, and visit history are
excluded. This deliberately favors a stable structural identity; when existing
context or viewport evidence is insufficient, the observation remains
unresolved instead of allocating a guessed state.

Candidate instance identity remains separate. Existing production
reconciliation supplies focus and visit facts; the graph does not reconstruct
focus identity or grant visits. State metadata aggregates observed focus IDs,
production visit IDs, observation counts, candidate count, and compact scroll
diagnostics without changing the state ID.

## Edges and replay

Edges support focus, targeted focus, directional scroll, activation, tab change,
back, recovery, scenario entry, and other observed actions. Each occurrence has
a stable opportunity key and a deterministic run-local occurrence ID. The
lifecycle records `PLANNED`, `ATTEMPTED`, `DISPATCHED`, `EFFECT_OBSERVED`,
`STATE_CHANGED`, and `VISIT_CREDIT` independently. A command ACK is retained as
evidence and never sets effect, state-change, or visit lifecycle by itself.
Self-edges are valid.

`tools.state_graph_replay` accepts an ordered, versioned offline manifest. No
volatile clock data is added to replay output. Graph limits mark graph-only
truncation; they do not stop traversal.

## C7 evidence boundary

The preserved Home Monitor summary proves 54 actual focus moves and 16 new
production visit credits, but it does not include enough paired raw state
observations to reconstruct C7 state identities. The test reuses those counts
with a clearly synthetic repeated-state input to verify that focus cursor
movement alone does not split a graph state. It does not claim a live C7 graph
state count or resolve the C7 scroll limitation.

## Phase boundary

No frontier, planner, starvation, plateau, termination, scroll capability,
safety, focus authority, or visit authority behavior is implemented here.
Phase 6C may review the passive graph model after the regression gates pass.
