from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


class DummyClient:
    def __init__(self, announcements=None, select_result=True):
        self.announcements = announcements or []
        self.select_result = select_result
        self.calls = []

    def select(self, dev_serial, target_name):
        self.calls.append(("select", dev_serial, target_name))
        return self.select_result

    def get_announcements(self, dev_serial, wait_seconds=0.0):
        self.calls.append(("get_announcements", dev_serial, wait_seconds))
        return self.announcements


def _load_main_with_fake_pil(monkeypatch):
    fake_font = SimpleNamespace(truetype=lambda *args, **kwargs: object(), load_default=lambda: object())
    fake_draw = SimpleNamespace(
        Draw=lambda _img: SimpleNamespace(rectangle=lambda *a, **k: None, text=lambda *a, **k: None)
    )

    class FakeImage:
        size = (200, 200)

        def convert(self, _mode):
            return self

        def save(self, _path):
            Path(_path).parent.mkdir(parents=True, exist_ok=True)
            Path(_path).write_bytes(b"fake")
            return None

    fake_image_module = SimpleNamespace(
        open=lambda _path: FakeImage(),
        new=lambda *args, **kwargs: FakeImage(),
        alpha_composite=lambda base, _overlay: base,
    )

    fake_pil = SimpleNamespace(Image=fake_image_module, ImageDraw=fake_draw, ImageFont=fake_font)
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", fake_draw)
    monkeypatch.setitem(sys.modules, "PIL.ImageFont", fake_font)

    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


def test_take_snapshot_runs_screencap_and_pull(monkeypatch, tmp_path):
    main = _load_main_with_fake_pil(monkeypatch)
    called = []

    def fake_run(cmd, check, capture_output, text):
        called.append(cmd)
        return None

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    save_path = tmp_path / "snap" / "screen.png"
    main.take_snapshot("SERIAL", str(save_path))

    assert called == [
        ["adb", "-s", "SERIAL", "shell", "screencap", "-p", "/sdcard/temp.png"],
        ["adb", "-s", "SERIAL", "pull", "/sdcard/temp.png", str(save_path)],
    ]


def test_verify_talkback_speech_pass_removes_temp(monkeypatch, tmp_path):
    main = _load_main_with_fake_pil(monkeypatch)
    temp_file = tmp_path / "temp_수면 환경.png"
    temp_file.write_bytes(b"x")

    monkeypatch.setattr(main, "Path", lambda path: temp_file)
    monkeypatch.setattr(main, "take_snapshot", lambda dev_serial, save_path: None)

    removed = []
    monkeypatch.setattr(main.os, "remove", lambda path: removed.append(Path(path)))

    client = DummyClient(announcements=["다른 안내", "수면 환경 선택됨"])

    result = main.verify_talkback_speech("SERIAL", client, "수면 환경")

    assert result is True
    assert removed == [temp_file]
    assert client.calls == [
        ("select", "SERIAL", "수면 환경"),
        ("get_announcements", "SERIAL", 3.0),
    ]


def test_verify_talkback_speech_fail_creates_error_log(monkeypatch, tmp_path):
    main = _load_main_with_fake_pil(monkeypatch)
    monkeypatch.chdir(tmp_path)

    temp_file = tmp_path / "temp_수면 환경.png"
    temp_file.write_bytes(b"x")

    monkeypatch.setattr(main, "Path", lambda path: temp_file if str(path).startswith("temp_") else Path(path))
    monkeypatch.setattr(main, "take_snapshot", lambda dev_serial, save_path: None)

    client = DummyClient(announcements=["설정"])

    result = main.verify_talkback_speech("SERIAL", client, "수면 환경")

    assert result is False
    assert (Path("error_log") / "fail_수면 환경.png").exists()
