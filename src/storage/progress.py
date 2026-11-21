"""Общий прогресс прохождений и даты первых открытий концовок."""

from datetime import datetime
import json
from pathlib import Path
import re

from story.parser import ENDING_STATE_KEYS, normalize_script_state
from storage.json_files import write_user_json


TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})")


def ending_unlock_time() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_ending_dates(data: dict, state: dict | None = None) -> dict[str, str]:
    if not isinstance(data, dict):
        raise ValueError("Ending dates must be a dictionary")
    result = {}
    for flag, value in data.items():
        if flag not in ENDING_STATE_KEYS:
            raise ValueError(f"Unknown ending date key: {flag}")
        if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
            raise ValueError(f"Invalid ending date: {flag}")
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid ending date: {flag}") from exc
        if state is not None and state.get(flag) is not True:
            raise ValueError(f"Date belongs to a locked ending: {flag}")
        result[flag] = timestamp.isoformat(timespec="seconds")
    return result


def split_persistent_progress(data: dict) -> tuple[dict, dict[str, str]]:
    """Старые плоские persistent-файлы без ending_dates по-прежнему допустимы."""
    if not isinstance(data, dict):
        raise ValueError("Persistent state must be a dictionary")
    flags = {key: value for key, value in data.items() if key != "ending_dates"}
    if any(not isinstance(key, str) or not key.startswith("persistent.") for key in flags):
        raise ValueError("Invalid persistent key")
    validated = normalize_script_state(flags)
    dates = normalize_ending_dates(data.get("ending_dates", {}), validated)
    return flags, dates


def read_progress(path: Path) -> tuple[dict, dict[str, str]] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as source:
        return split_persistent_progress(json.load(source))


def write_progress(
    path: Path, flags: dict, dates: dict[str, str], *, backup_invalid: bool = False,
) -> None:
    state = {**flags, "ending_dates": dates} if dates else flags
    write_user_json(path, state, backup_invalid=backup_invalid)


def merge_ending_dates(current: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    """Сохраняет самое раннее известное открытие, в том числе из backup-save."""
    merged = current.copy()
    for flag, value in incoming.items():
        if flag not in merged or datetime.fromisoformat(value) < datetime.fromisoformat(merged[flag]):
            merged[flag] = value
    return merged


def format_ending_date(value: str | None, strings: dict[str, str] | None = None) -> str:
    strings = strings or {}
    unknown = strings.get("date.unknown", "Дата неизвестна")
    if value is None:
        return unknown
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return unknown
    label = strings.get("date.unlocked", "Получена: {date} в {time}")
    return label.replace("{date}", f"{timestamp:%d.%m.%Y}").replace("{time}", f"{timestamp:%H:%M}")
