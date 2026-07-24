import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FocusContext:
    target: str
    target_source: str
    approximate_position: str
    center_relative: str
    description: str


def _text(value: object) -> str:
    return str(value or "").strip()


def _focus_node(value: object) -> dict[str, object]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_crop_text(crop_path: Path | None) -> str:
    if crop_path is None or not crop_path.is_file():
        return ""
    try:
        from PIL import Image
        import pytesseract

        with Image.open(crop_path) as image:
            lines = [line.strip() for line in pytesseract.image_to_string(image).splitlines() if line.strip()]
            return lines[0][:80] if lines else ""
    except (ImportError, OSError, RuntimeError):
        return ""


def _resource_label(resource_id: str) -> str:
    value = resource_id.rsplit("/", maxsplit=1)[-1].rsplit(":", maxsplit=1)[-1]
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", value.replace("_", " ").replace("-", " ")).split()
    prefixes = {"btn", "iv", "tv", "ll", "rv", "cl", "shm", "device"}
    button_prefix = bool(words and words[0].lower() == "btn")
    if words and words[0].lower() in prefixes:
        words = words[1:]
    normalized = {"setting": "Settings", "settings": "Settings", "button": "Button", "menu": "Menu", "sensor": "Sensor", "card": "Card"}
    labels = [normalized.get(word.lower(), word.title()) for word in words]
    if button_prefix and "Button" not in labels:
        labels.append("Button")
    if labels and labels[-1] == "Button" and len(labels) > 1:
        return " ".join(labels)
    return " ".join(labels)


def _target(content_description: str, visible_text: str, resource_id: str, crop_path: Path | None, parent_text: str, representative_text: str) -> tuple[str, str]:
    for target, source in ((content_description, "contentDescription"), (visible_text, "visibleText"), (_resource_label(resource_id), "resource id")):
        if target:
            return target, source
    ocr_text = extract_crop_text(crop_path)
    if ocr_text:
        return ocr_text, "OCR(crop)"
    if parent_text:
        return parent_text, "parent node"
    if representative_text:
        return representative_text, "representative node"
    return "Unknown", "Unknown"


def _coordinates(bounds: str) -> tuple[int, int, int, int] | None:
    parts = [part.strip() for part in bounds.split(",")]
    if len(parts) != 4:
        return None
    try:
        values = tuple(int(part) for part in parts)
    except ValueError:
        return None
    return values if values[2] >= values[0] and values[3] >= values[1] else None


def _position(bounds: str, width: int, height: int) -> tuple[str, str]:
    coordinates = _coordinates(bounds)
    if coordinates is None or width <= 0 or height <= 0:
        return "Unknown", ""
    left, top, right, bottom = coordinates
    x_percent = round(((left + right) / 2) / width * 100)
    y_percent = round(((top + bottom) / 2) / height * 100)
    vertical = "Top" if y_percent < 34 else "Center" if y_percent < 67 else "Bottom"
    horizontal = "Left" if x_percent < 34 else "Center" if x_percent < 67 else "Right"
    center_x = round((left + right) / 2)
    center_y = round((top + bottom) / 2)
    position = f"{vertical} {horizontal} ({x_percent}%, {y_percent}%)"
    return position, f"{center_x}, {center_y} ({x_percent}%, {y_percent}%)"


def focus_context(
    *,
    raw: dict[str, object],
    visible_text: str,
    speech: str,
    resource_id: str,
    parent_text: str,
    representative_text: str,
    screen: str,
    bounds: str,
    crop_path: Path | None,
    display_width: int,
    display_height: int,
) -> FocusContext:
    node = _focus_node(raw.get("focus_node"))
    content_description = _text(raw.get("focus_content_description")) or _text(node.get("contentDescription"))
    target, target_source = _target(content_description, visible_text, resource_id, crop_path, parent_text, representative_text)
    approximate_position, center_relative = _position(bounds, display_width, display_height)
    if target == "Unknown" and crop_path is not None:
        description = f"{screen} 화면에서 {approximate_position} 영역까지 TalkBack 포커스를 이동합니다. 표시된 Screenshot 근처의 새 Focus 항목에서 실제 TalkBack 발화와 화면 텍스트를 확인하세요."
    elif target == "Unknown":
        description = f"{screen} 화면에서 {approximate_position} 영역까지 TalkBack 포커스를 이동합니다. 새롭게 포커스되는 항목의 실제 TalkBack 발화와 화면 텍스트를 확인하세요."
    else:
        description = f"{approximate_position}의 {target}으로\nTalkBack 포커스를 이동하여\n실제 발화를 확인하세요."
    return FocusContext(target, target_source, approximate_position, center_relative, description)
