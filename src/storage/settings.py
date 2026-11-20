"""Настройки на диске и миграция старых значений."""

import json
from pathlib import Path

from audio.catalog import finite_number
from audio.manager import AUDIO_DEFAULTS
from art_renderer import ART_STYLES
from storage.json_files import write_user_json


DEFAULT_SETTINGS = {
    "language": "ru",
    "header": False,
    "header_lp_points": True,
    "header_flags": True,
    "quality": "150",
    "style": "ANSI",
    "scene_filters_enabled": True,
    "text_speed": "0.025",
    **AUDIO_DEFAULTS,
}


def _reject_constant(value: str):
    raise ValueError(f"Недопустимое число в настройках: {value}")


def _parse_float(value: str) -> float:
    return finite_number(float(value), minimum=-float("inf"))


def read_settings(path: Path, defaults: dict) -> tuple[dict, bool]:
    """Возвращает настройки и признак, что файл нужно создать или обновить."""
    if not path.exists():
        return defaults.copy(), True
    with path.open("r", encoding="utf-8") as source:
        loaded = json.load(source, parse_constant=_reject_constant, parse_float=_parse_float)
    if not isinstance(loaded, dict):
        raise ValueError("Настройки должны быть JSON-объектом")

    settings = {**defaults, **loaded}
    if settings["language"] not in ("ru", "en"):
        settings["language"] = "ru"
    for key in ("header", "header_lp_points", "header_flags", "scene_filters_enabled"):
        if type(settings[key]) is not bool:
            raise ValueError(f"Некорректная настройка: {key}")
    for key, choices in (("quality", ("50", "150", "200")),
                         ("text_speed", ("0", "0.01", "0.025", "0.04"))):
        raw = settings[key]
        if type(raw) in (int, float):
            value = next((choice for choice in choices if raw == float(choice)), None)
        else:
            value = raw
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f"Некорректная настройка: {key}")
        settings[key] = value
    style = settings["style"]
    if not isinstance(style, str) or style not in ART_STYLES:
        raise ValueError("Некорректная настройка: style")
    for key in AUDIO_DEFAULTS:
        if key == "audio_muted":
            if type(settings[key]) is not bool:
                raise ValueError(f"Некорректная настройка: {key}")
        else:
            settings[key] = finite_number(settings[key], maximum=1)
    return settings, settings != loaded


def write_settings(path: Path, settings: dict, *, backup_invalid: bool = False) -> None:
    write_user_json(path, settings, backup_invalid=backup_invalid)
