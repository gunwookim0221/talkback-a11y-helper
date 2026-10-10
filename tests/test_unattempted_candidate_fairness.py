from types import SimpleNamespace

from tb_runner import local_tab_logic


def _candidate(label, rid, bounds):
    node = {
        "resourceId": rid,
        "boundsInScreen": bounds,
        "className": "android.widget.Button",
        "text": label,
        "focusable": True,
        "clickable": True,
    }
    return {"label": label, "rid": rid, "bounds": bounds, "node": node}


def _state(candidates, *, attempted=(), visited=(), semantic=(), stale=()):
    ids = [local_tab_logic._content_candidate_instance_id(item, "home_main") for item in candidates]
    tracker = SimpleNamespace(
        latest={"unseen_candidate_ids": ids},
        target_attempted_ids=set(attempted),
        visited=set(visited),
        semantic=set(semantic),
        lifecycle=SimpleNamespace(aliases={key: {} for key in stale}),
    )
    return SimpleNamespace(content_terminal=tracker)


def _select(candidates, state):
    return local_tab_logic._prioritize_unattempted_active_unseen_candidates(
        candidates,
        state=state,
        scenario_id="home_main",
    )


def test_attempted_top_ranked_candidate_cannot_starve_unattempted_candidates():
    attempted = _candidate("A", "id.a", "0,0,100,100")
    second = _candidate("B", "id.b", "0,120,100,220")
    third = _candidate("C", "id.c", "0,240,100,340")
    state = _state([attempted, second, third], attempted=[local_tab_logic._content_candidate_instance_id(attempted, "home_main")])

    selected, metadata = _select([attempted, second, third], state)

    assert selected == [second, third]
    assert metadata["prioritized"] is True
    assert selected[0] == second

    state.content_terminal.target_attempted_ids.add(local_tab_logic._content_candidate_instance_id(second, "home_main"))
    selected, _ = _select([attempted, second, third], state)
    assert selected == [third]


def test_ten_unattempted_candidates_are_selected_in_stable_order():
    candidates = [_candidate(f"item-{index}", f"id.{index}", f"0,{index * 120},100,{index * 120 + 100}") for index in range(10)]
    state = _state(candidates)
    offered = []

    for candidate in candidates:
        eligible, metadata = _select(candidates, state)
        assert metadata["prioritized"] is True
        offered.append(eligible[0])
        state.content_terminal.target_attempted_ids.add(
            local_tab_logic._content_candidate_instance_id(eligible[0], "home_main")
        )

    assert offered == candidates


def test_attempted_mismatch_stays_unvisited_and_loses_priority_to_never_attempted():
    mismatch = _candidate("Mismatch", "id.a", "0,0,100,100")
    never_attempted = _candidate("Never attempted", "id.b", "0,120,100,220")
    mismatch_id = local_tab_logic._content_candidate_instance_id(mismatch, "home_main")
    state = _state([mismatch, never_attempted], attempted=[mismatch_id])
    state.content_terminal.target_attempt_statuses = {mismatch_id: "FOCUS_MOVED_TO_OTHER_NODE"}

    selected, _ = _select([mismatch, never_attempted], state)

    assert mismatch_id not in state.content_terminal.visited
    assert selected == [never_attempted]


def test_visited_or_stale_ids_are_not_reintroduced_by_fairness_gate():
    visited = _candidate("Visited", "id.visited", "0,0,100,100")
    stale = _candidate("Stale", "id.stale", "0,120,100,220")
    remaining = _candidate("Remaining", "id.remaining", "0,240,100,340")
    visited_id = local_tab_logic._content_candidate_instance_id(visited, "home_main")
    stale_id = local_tab_logic._content_candidate_instance_id(stale, "home_main")
    state = _state([visited, stale, remaining], visited=[visited_id], stale=[stale_id])

    selected, _ = _select([visited, stale, remaining], state)

    assert selected == [remaining]


def test_disappeared_candidate_does_not_override_current_inventory():
    attempted = _candidate("Attempted", "id.a", "0,0,100,100")
    disappeared = _candidate("Disappeared", "id.b", "0,120,100,220")
    attempted_id = local_tab_logic._content_candidate_instance_id(attempted, "home_main")
    state = _state([attempted, disappeared], attempted=[attempted_id])

    selected, metadata = _select([attempted], state)

    assert selected == [attempted]
    assert metadata["prioritized"] is False
    assert metadata["unattempted_active_unseen"] == 1


def test_recreated_identity_persists_and_same_resource_bounds_remain_distinct():
    first = _candidate("Same resource", "id.shared", "0,0,100,100")
    recreated = _candidate("Same resource renamed", "id.shared", "0,0,100,100")
    second_instance = _candidate("Same resource", "id.shared", "0,120,100,220")
    first_id = local_tab_logic._content_candidate_instance_id(first, "home_main")
    second_id = local_tab_logic._content_candidate_instance_id(second_instance, "home_main")
    state = _state([first, second_instance], attempted=[first_id])

    assert local_tab_logic._content_candidate_instance_id(recreated, "home_main") == first_id
    assert first_id != second_id
    selected, _ = _select([recreated, second_instance], state)
    assert selected == [second_instance]


def test_fairness_inventory_includes_cluster_members_and_consumed_cluster_nodes():
    representative = _candidate("Card", "id.card", "0,0,300,300")
    first_member = _candidate("First child", "id.first", "0,20,100,80")
    second_member = _candidate("Second child", "id.second", "110,20,200,80")
    consumed_cluster_member = _candidate("Previously grouped child", "id.third", "0,320,100,380")
    passive = _candidate("Passive", "id.passive", "110,320,200,380")
    passive["passive_status"] = True
    representative["cluster_members"] = [first_member, second_member]

    inventory = local_tab_logic._current_valid_content_candidates(
        [representative],
        [consumed_cluster_member, passive],
        scenario_id="home_main",
    )

    assert [candidate["label"] for candidate in inventory] == [
        "First child",
        "Second child",
        "Card",
        "Previously grouped child",
    ]
