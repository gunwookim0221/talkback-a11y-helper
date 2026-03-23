from __future__ import annotations

import importlib
import sys


class DummyClient:
    def __init__(self, helper_enabled=True, devices_output='List of devices attached\nSERIAL\tdevice\n'):
        self.helper_enabled = helper_enabled
        self.devices_output = devices_output
        self.calls = []

    def _run(self, args):
        self.calls.append(("_run", args))
        if args == ["devices"]:
            return self.devices_output
        raise AssertionError(args)

    def check_helper_status(self, dev_serial):
        self.calls.append(("check_helper_status", dev_serial))
        return self.helper_enabled

    def scrollFind(self, dev_serial, target_name, direction_="down"):
        self.calls.append(("scrollFind", dev_serial, target_name, direction_))
        return True

    def select(self, dev_serial, target_name):
        self.calls.append(("select", dev_serial, target_name))
        return True

    def verify_speech(self, dev_serial, expected_regex):
        self.calls.append(("verify_speech", dev_serial, expected_regex))
        return True


def _load_main_module(monkeypatch):
    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


def test_main_exits_when_helper_service_disabled(monkeypatch):
    main = _load_main_module(monkeypatch)
    dummy = DummyClient(helper_enabled=False)

    monkeypatch.setattr(main, "A11yAdbClient", lambda: dummy)

    with monkeypatch.context() as m:
        m.setattr(main.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))
        try:
            main.main()
            raised = None
        except SystemExit as exc:
            raised = exc

    assert raised is not None
    assert raised.code == 1
    assert dummy.calls == [
        ("_run", ["devices"]),
        ("check_helper_status", "SERIAL"),
    ]


def test_main_runs_focus_and_verify_flow(monkeypatch, capsys):
    main = _load_main_module(monkeypatch)
    dummy = DummyClient(helper_enabled=True)

    monkeypatch.setattr(main, "A11yAdbClient", lambda: dummy)

    main.main()

    assert dummy.calls == [
        ("_run", ["devices"]),
        ("check_helper_status", "SERIAL"),
        ("scrollFind", "SERIAL", "Pet.*", "down"),
        ("select", "SERIAL", "Pet.*"),
        ("verify_speech", "SERIAL", "Pet.*"),
    ]
    output = capsys.readouterr().out
    assert "[PASS] 발화 검증 성공: Pet.*" in output


def test_main_returns_when_no_connected_devices(monkeypatch, capsys):
    main = _load_main_module(monkeypatch)
    dummy = DummyClient(devices_output='List of devices attached\n\n')

    monkeypatch.setattr(main, "A11yAdbClient", lambda: dummy)

    main.main()

    assert dummy.calls == [("_run", ["devices"])]
    output = capsys.readouterr().out
    assert "연결된 안드로이드 단말기가 없습니다" in output
