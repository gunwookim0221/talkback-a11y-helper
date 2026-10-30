from tb_runner.phase5b_navigation import SafeNavigationSession


def command(operation, **values):
    result = ["shell", "am", "broadcast", "-a",
              "com.iotpart.sqe.talkbackhelper.HIERARCHY_TRANSFER_" + operation,
              "-p", "com.iotpart.sqe.talkbackhelper"]
    for key, value in values.items():
        result.extend(["--es", key, value])
    return result


def test_phase5_cleanup_binding_is_paired_and_legacy_stays_parseable():
    base = dict(requestId="a" * 32, clientNonce="b" * 32, queryNonce="c" * 32)
    parse = SafeNavigationSession._hierarchy_broadcast_extras
    assert parse(command("CANCEL", **base))["valid"] is True
    assert parse(command("CANCEL", **base, expectedProcessEpoch="epoch-1"))["valid"] is False
    assert parse(command("CANCEL", **base, expectedProcessEpoch="epoch-1", expectedGeneration="0"))["valid"] is False
    assert parse(command("CANCEL", **base, expectedProcessEpoch="epoch-1", expectedGeneration="1"))["valid"] is True


def test_phase5_rejects_wrong_bound_ack_before_dispatch_without_action_authority():
    session = SafeNavigationSession("synthetic", lambda *_: None)
    req, nonce, query = "a" * 32, "b" * 32, "c" * 32
    assert session._phase5_hierarchy_command(command("CAPABILITIES", queryNonce=query), commit=True)["valid"]
    start = command("START", requestId=req, clientNonce=nonce, queryNonce=query,
                    expectedBuildId="d" * 64, expectedGitCommit="e" * 40,
                    expectedServiceInstanceId="service-1")
    assert session._phase5_hierarchy_command(start, commit=True)["valid"]
    state = session._phase5_hierarchy_request
    state.update(payload_read=True, payload_sha256="f" * 64,
                 payload_generation=2, payload_process_epoch="epoch-2")
    base = dict(requestId=req, clientNonce=nonce, queryNonce=query, payloadSha256="f" * 64)
    wrong = command("ACK", **base, expectedProcessEpoch="epoch-1", expectedGeneration="1")
    assert session._phase5_hierarchy_command(wrong, commit=True)["valid"] is False
    assert state["ack_sent"] is False
    wrong_cancel = command("CANCEL", requestId=req, clientNonce=nonce, queryNonce=query,
                           expectedProcessEpoch="epoch-1", expectedGeneration="1")
    assert session._phase5_hierarchy_command(wrong_cancel, commit=True)["valid"] is False
    assert state["cancel_sent"] is False
    right = command("ACK", **base, expectedProcessEpoch="epoch-2", expectedGeneration="2")
    assert session._phase5_hierarchy_command(right, commit=False)["valid"] is True
    assert session.permit is None
    assert session.dispatch_authorizations == []


def test_cancel_response_wrong_generation_never_reports_cleanup_success():
    from talkback_lib import A11yAdbClient

    client = A11yAdbClient.__new__(A11yAdbClient)
    client._hierarchy_nonce = lambda: "c" * 32
    client._hierarchy_transfer_control = lambda *_args, **_kwargs: {
        "query_nonce": "c" * 32, "request_id": "a" * 32,
        "client_nonce": "b" * 32, "process_epoch": "epoch-1",
        "generation": 8, "status": "CANCELLED", "completed": True,
    }
    client._cancel_hierarchy_transfer(None, "a" * 32, "b" * 32, 1.0,
                                      expected_process_epoch="epoch-1", expected_generation=7)
    assert client.last_hierarchy_cleanup_diagnostic["status"] == "FAILED"
    assert client.last_hierarchy_cleanup_diagnostic["error_code"] == "CANCEL_CORRELATION_MISMATCH"
