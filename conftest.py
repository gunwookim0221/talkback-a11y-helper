from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


class _FakeImage:
    size = (200, 200)

    def convert(self, _mode):
        return self

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"fake")
        return None


def pytest_configure():
    if "PIL" in sys.modules:
        return

    fake_font = SimpleNamespace(truetype=lambda *args, **kwargs: object(), load_default=lambda: object())
    fake_draw = SimpleNamespace(
        Draw=lambda _img: SimpleNamespace(rectangle=lambda *a, **k: None, text=lambda *a, **k: None)
    )
    fake_image_module = SimpleNamespace(
        open=lambda _path: _FakeImage(),
        new=lambda *args, **kwargs: _FakeImage(),
        alpha_composite=lambda base, _overlay: base,
    )
    fake_pil = SimpleNamespace(Image=fake_image_module, ImageDraw=fake_draw, ImageFont=fake_font)

    sys.modules.setdefault("PIL", fake_pil)
    sys.modules.setdefault("PIL.Image", fake_image_module)
    sys.modules.setdefault("PIL.ImageDraw", fake_draw)
    sys.modules.setdefault("PIL.ImageFont", fake_font)
