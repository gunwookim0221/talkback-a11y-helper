from pathlib import Path

from PIL import Image, ImageDraw


def pixel_bounds(bounds: str, *, logical_width: int, logical_height: int, pixel_width: int, pixel_height: int) -> tuple[int, int, int, int] | None:
    parts = [part.strip() for part in bounds.split(",")]
    if len(parts) != 4 or logical_width <= 0 or logical_height <= 0 or pixel_width <= 0 or pixel_height <= 0:
        return None
    try:
        left, top, right, bottom = (int(part) for part in parts)
    except ValueError:
        return None
    scale_x = pixel_width / logical_width
    scale_y = pixel_height / logical_height
    values = (round(left * scale_x), round(top * scale_y), round(right * scale_x), round(bottom * scale_y))
    clamped = (max(0, min(pixel_width, values[0])), max(0, min(pixel_height, values[1])), max(0, min(pixel_width, values[2])), max(0, min(pixel_height, values[3])))
    return clamped if clamped[2] > clamped[0] and clamped[3] > clamped[1] else None


def create_full_screen_annotation(screenshot_path: Path | None, *, bounds: str, logical_width: int, logical_height: int, target: str, run_root: Path) -> str:
    if screenshot_path is None or not screenshot_path.is_file():
        return ""
    output_dir = run_root / "review_annotations"
    output_path = output_dir / f"{screenshot_path.stem}.annotated.png"
    try:
        with Image.open(screenshot_path) as source:
            image = source.convert("RGB")
    except OSError:
        return ""
    try:
        rectangle = pixel_bounds(bounds, logical_width=logical_width, logical_height=logical_height, pixel_width=image.width, pixel_height=image.height)
        if rectangle is None:
            return ""
        left, top, right, bottom = rectangle
        stroke = max(3, min(image.width, image.height) // 160)
        draw = ImageDraw.Draw(image)
        draw.rectangle(rectangle, outline="red", width=stroke)
        center_x, center_y = (left + right) // 2, (top + bottom) // 2
        marker = max(5, stroke * 2)
        draw.line((center_x - marker, center_y, center_x + marker, center_y), fill="red", width=stroke)
        draw.line((center_x, center_y - marker, center_x, center_y + marker), fill="red", width=stroke)
        label = f"Focus: {target}" if target else "Focus target"
        label_x = min(max(0, left), max(0, image.width - len(label) * stroke * 2))
        label_y = top - (stroke * 5) if top >= stroke * 6 else min(image.height - stroke * 5, bottom + stroke)
        draw.rectangle((label_x, label_y, min(image.width, label_x + len(label) * stroke * 2), min(image.height, label_y + stroke * 4)), fill="white", outline="red", width=stroke)
        draw.text((label_x + stroke, label_y + stroke), label, fill="black")
        output_dir.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="PNG", optimize=True)
    except OSError:
        return ""
    finally:
        image.close()
    return output_path.relative_to(run_root).as_posix()


def create_focus_annotation(crop_path: Path | None, run_root: Path) -> str:
    if crop_path is None or not crop_path.is_file():
        return ""
    output_dir = run_root / "review_annotations"
    output_path = output_dir / f"{crop_path.stem}.focus.png"
    try:
        source = Image.open(crop_path)
        image = source.convert("RGB")
    except OSError:
        return ""
    try:
        width, height = getattr(image, "size", (0, 0))
        center_x, center_y = width // 2, height // 2
        radius = max(12, min(width, height) // 5)
        stroke = max(3, min(width, height) // 40)
        draw = ImageDraw.Draw(image)
        ellipse = getattr(draw, "ellipse", None)
        line = getattr(draw, "line", None)
        if callable(ellipse):
            ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), outline="red", width=stroke)
        if callable(line):
            line((center_x - radius, center_y, center_x + radius, center_y), fill="red", width=stroke)
            line((center_x, center_y - radius, center_x, center_y + radius), fill="red", width=stroke)
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            image.save(output_path, format="PNG", optimize=True)
        except TypeError:
            image.save(output_path)
    except OSError:
        return ""
    finally:
        close = getattr(image, "close", None)
        if callable(close):
            close()
    return output_path.relative_to(run_root).as_posix()
