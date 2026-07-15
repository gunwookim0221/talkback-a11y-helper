"""Semantic validators and parsers for EnvironmentProfile collection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tb_runner.environment_profile import FieldStatus


PACKAGE_NOT_FOUND_PATTERNS = (
    "unable to find package",
    "unknown package",
    "package not found",
    "can't find package",
    "cannot find package",
)
TALKBACK_PACKAGES = {
    "com.google.android.marvin.talkback",
    "com.samsung.android.accessibility.talkback",
}


@dataclass(frozen=True)
class ValidationResult:
    status: FieldStatus
    value: Any = None
    reason: str = ""


@dataclass(frozen=True)
class PackageMetadata:
    package: str
    version_name: str
    version_code: int


@dataclass(frozen=True)
class DisplaySizeMetadata:
    physical: dict[str, int] | None
    logical: dict[str, int] | None
    override: dict[str, int] | None


@dataclass(frozen=True)
class DisplayDensityMetadata:
    physical: int | None
    logical: int | None
    override: int | None


@dataclass(frozen=True)
class FoldMetadata:
    capability: bool | None
    posture: str | None
    supported_states: tuple[dict[str, Any], ...]


def missing_or_error_text(value: Any) -> tuple[bool, bool]:
    text = str(value or "").strip()
    lowered = text.casefold()
    missing = not text or lowered in {"null", "none", "unknown", "unavailable"}
    invalid = any(pattern in lowered for pattern in PACKAGE_NOT_FOUND_PATTERNS)
    invalid = invalid or lowered.startswith("error:") or lowered.startswith("exception:")
    return missing, invalid


def validate_nonempty_text(value: Any) -> ValidationResult:
    missing, invalid = missing_or_error_text(value)
    if missing:
        return ValidationResult(FieldStatus.MISSING, reason="empty_output")
    if invalid:
        return ValidationResult(FieldStatus.INVALID, reason="semantic_error_output")
    return ValidationResult(FieldStatus.AVAILABLE, str(value).strip())


def validate_int(value: Any, *, minimum: int = 0) -> ValidationResult:
    text_result = validate_nonempty_text(value)
    if text_result.status != FieldStatus.AVAILABLE:
        return text_result
    try:
        parsed = int(str(text_result.value))
    except (TypeError, ValueError):
        return ValidationResult(FieldStatus.INVALID, reason="not_an_integer")
    if parsed < minimum:
        return ValidationResult(FieldStatus.INVALID, reason="integer_out_of_range")
    return ValidationResult(FieldStatus.AVAILABLE, parsed)


def validate_git_commit(value: Any) -> ValidationResult:
    result = validate_nonempty_text(value)
    if result.status != FieldStatus.AVAILABLE:
        return result
    commit = str(result.value)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        return ValidationResult(FieldStatus.INVALID, reason="invalid_git_commit")
    return ValidationResult(FieldStatus.AVAILABLE, commit.lower())


def normalize_locale(value: Any) -> ValidationResult:
    result = validate_nonempty_text(value)
    if result.status != FieldStatus.AVAILABLE:
        return result
    raw = str(result.value).replace("_", "-")
    parts = raw.split("-")
    if not re.fullmatch(r"[A-Za-z]{2,3}", parts[0]):
        return ValidationResult(FieldStatus.INVALID, reason="invalid_locale")
    normalized = [parts[0].lower()]
    index = 1
    if index < len(parts) and re.fullmatch(r"[A-Za-z]{4}", parts[index]):
        normalized.append(parts[index].title())
        index += 1
    if index < len(parts) and re.fullmatch(r"(?:[A-Za-z]{2}|\d{3})", parts[index]):
        normalized.append(parts[index].upper())
        index += 1
    if index != len(parts):
        return ValidationResult(FieldStatus.INVALID, reason="invalid_locale")
    return ValidationResult(FieldStatus.AVAILABLE, "-".join(normalized))


def parse_package_metadata(package: str, output: Any) -> ValidationResult:
    result = validate_nonempty_text(output)
    if result.status != FieldStatus.AVAILABLE:
        return result
    text = str(result.value)
    package_pattern = re.compile(rf"(?<![\w.]){re.escape(package)}(?![\w.])")
    if not package_pattern.search(text):
        return ValidationResult(FieldStatus.INVALID, reason="package_identity_not_confirmed")
    version_name_match = re.search(r"(?m)^\s*versionName=([^\r\n]+?)\s*$", text)
    version_code_match = re.search(r"\bversionCode=(\d+)\b", text)
    if not version_name_match or not version_code_match:
        return ValidationResult(FieldStatus.INVALID, reason="package_version_unparseable")
    version_name = version_name_match.group(1).strip()
    if not version_name or version_name.casefold() in {"null", "none", "unknown"}:
        return ValidationResult(FieldStatus.INVALID, reason="package_version_unparseable")
    return ValidationResult(
        FieldStatus.AVAILABLE,
        PackageMetadata(package=package, version_name=version_name, version_code=int(version_code_match.group(1))),
    )


def select_active_talkback_package(enabled_services: Any) -> ValidationResult:
    result = validate_nonempty_text(enabled_services)
    if result.status != FieldStatus.AVAILABLE:
        return result
    packages: list[str] = []
    for component in str(result.value).split(":"):
        package = component.strip().split("/", 1)[0]
        if package in TALKBACK_PACKAGES and package not in packages:
            packages.append(package)
    if not packages:
        return ValidationResult(FieldStatus.MISSING, reason="active_talkback_service_not_found")
    if len(packages) > 1:
        return ValidationResult(FieldStatus.INVALID, reason="multiple_active_talkback_packages")
    return ValidationResult(FieldStatus.AVAILABLE, packages[0])


def parse_one_ui_version(value: Any) -> ValidationResult:
    result = validate_nonempty_text(value)
    if result.status != FieldStatus.AVAILABLE:
        return result
    text = str(result.value).strip()
    if re.fullmatch(r"\d{5,6}", text):
        encoded = int(text)
        major = encoded // 10000
        minor = (encoded // 100) % 100
        patch = encoded % 100
        if major <= 0 or major > 99:
            return ValidationResult(FieldStatus.INVALID, reason="one_ui_encoded_version_out_of_range")
        normalized = f"{major}.{minor}"
        if patch:
            normalized += f".{patch}"
        return ValidationResult(FieldStatus.AVAILABLE, normalized)
    if not re.fullmatch(r"\d+(?:\.\d+){0,2}", text):
        return ValidationResult(FieldStatus.INVALID, reason="one_ui_version_unparseable")
    parts = [str(int(part)) for part in text.split(".")]
    if int(parts[0]) <= 0:
        return ValidationResult(FieldStatus.INVALID, reason="one_ui_version_out_of_range")
    return ValidationResult(FieldStatus.AVAILABLE, ".".join(parts))


def _size_value(width: str, height: str) -> dict[str, int]:
    return {"width": int(width), "height": int(height)}


def parse_display_size(output: Any) -> ValidationResult:
    result = validate_nonempty_text(output)
    if result.status != FieldStatus.AVAILABLE:
        return result
    text = str(result.value)
    physical_match = re.search(r"(?im)^\s*Physical size:\s*(\d+)x(\d+)\s*$", text)
    override_match = re.search(r"(?im)^\s*Override size:\s*(\d+)x(\d+)\s*$", text)
    logical_match = re.search(r"(?im)^\s*Logical size:\s*(\d+)x(\d+)\s*$", text)
    if not physical_match and not logical_match:
        return ValidationResult(FieldStatus.INVALID, reason="display_size_unparseable")
    physical = _size_value(*physical_match.groups()) if physical_match else None
    override = _size_value(*override_match.groups()) if override_match else None
    explicit_logical = _size_value(*logical_match.groups()) if logical_match else None
    logical = explicit_logical or override or physical
    return ValidationResult(FieldStatus.AVAILABLE, DisplaySizeMetadata(physical, logical, override))


def parse_display_density(output: Any) -> ValidationResult:
    result = validate_nonempty_text(output)
    if result.status != FieldStatus.AVAILABLE:
        return result
    text = str(result.value)
    physical_match = re.search(r"(?im)^\s*Physical density:\s*(\d+)\s*$", text)
    override_match = re.search(r"(?im)^\s*Override density:\s*(\d+)\s*$", text)
    logical_match = re.search(r"(?im)^\s*Logical density:\s*(\d+)\s*$", text)
    simple_match = re.search(r"(?im)^\s*Density:\s*(\d+)\s*$", text)
    physical = int(physical_match.group(1)) if physical_match else None
    override = int(override_match.group(1)) if override_match else None
    explicit_logical = int(logical_match.group(1)) if logical_match else None
    if physical is None and simple_match:
        physical = int(simple_match.group(1))
    logical = explicit_logical or override or physical
    if logical is None:
        return ValidationResult(FieldStatus.INVALID, reason="display_density_unparseable")
    return ValidationResult(FieldStatus.AVAILABLE, DisplayDensityMetadata(physical, logical, override))


def parse_fold_state(current_output: Any, supported_output: Any) -> ValidationResult:
    current_result = validate_int(current_output, minimum=0)
    supported_result = validate_nonempty_text(supported_output)
    if supported_result.status != FieldStatus.AVAILABLE:
        return ValidationResult(supported_result.status, reason=supported_result.reason)
    states = tuple(
        {
            "identifier": int(identifier),
            "name": name.upper(),
        }
        for identifier, name in re.findall(
            r"identifier=(\d+),\s*name=['\"]([^'\"]+)['\"]",
            str(supported_result.value),
        )
    )
    if not states:
        return ValidationResult(FieldStatus.INVALID, reason="fold_supported_states_unparseable")
    fold_names = {"CLOSED", "TENT", "HALF_OPENED", "HALF_OPEN", "OPENED", "FOLDED", "UNFOLDED"}
    capability = len(states) > 1 and any(state["name"] in fold_names for state in states)
    posture = None
    if current_result.status == FieldStatus.AVAILABLE:
        current_id = int(current_result.value)
        posture = next((str(state["name"]) for state in states if state["identifier"] == current_id), None)
        if posture is None:
            return ValidationResult(FieldStatus.INVALID, reason="current_fold_state_not_supported")
    elif capability:
        return ValidationResult(current_result.status, reason=current_result.reason)
    return ValidationResult(
        FieldStatus.AVAILABLE,
        FoldMetadata(capability=capability, posture=posture, supported_states=states),
    )


def parse_active_display(output: Any) -> ValidationResult:
    result = validate_nonempty_text(output)
    if result.status != FieldStatus.AVAILABLE:
        return result
    text = str(result.value)
    starts = list(re.finditer(r"(?m)^\s*Display:\s*mDisplayId=(\d+).*$", text))
    focused: list[dict[str, Any]] = []
    current_focus_displays: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        section = text[start.start():end]
        focus_match = re.search(r"(?m)^\s*mFocusedApp=(.+?)\s*$", section)
        focus_value = focus_match.group(1).strip() if focus_match else ""
        current_focus_match = re.search(r"(?m)^\s*mCurrentFocus=(.+?)\s*$", section)
        current_focus_value = current_focus_match.group(1).strip() if current_focus_match else ""
        package_match = re.search(r"\b([A-Za-z][\w]*(?:\.[A-Za-z][\w]*){2,})/", focus_value)
        candidate = {
            "display_id": int(start.group(1)),
            "focused_package": package_match.group(1) if package_match else None,
            "role": "UNKNOWN",
        }
        if current_focus_value and current_focus_value.casefold() != "null":
            current_focus_displays.append(candidate)
        if not focus_value or focus_value.casefold() == "null":
            continue
        focused.append(candidate)
    if not starts:
        return ValidationResult(FieldStatus.INVALID, reason="window_display_output_unparseable")
    candidates = current_focus_displays or focused
    if not candidates:
        return ValidationResult(FieldStatus.MISSING, reason="active_display_focus_unavailable")
    if len(candidates) > 1:
        return ValidationResult(FieldStatus.INVALID, reason="multiple_active_displays")
    return ValidationResult(FieldStatus.AVAILABLE, candidates[0])


__all__ = [
    "DisplayDensityMetadata",
    "DisplaySizeMetadata",
    "FoldMetadata",
    "PACKAGE_NOT_FOUND_PATTERNS",
    "PackageMetadata",
    "TALKBACK_PACKAGES",
    "ValidationResult",
    "missing_or_error_text",
    "normalize_locale",
    "parse_display_density",
    "parse_display_size",
    "parse_active_display",
    "parse_fold_state",
    "parse_one_ui_version",
    "parse_package_metadata",
    "select_active_talkback_package",
    "validate_git_commit",
    "validate_int",
    "validate_nonempty_text",
]
