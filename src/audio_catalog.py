"""Explicit audio resources; no directory scans or guessed aliases at runtime."""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioTrack:
    path: str
    duration: float


def audio_manifest_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "audio_manifest.json"
    return Path(__file__).with_name("audio_manifest.json")


def finite_number(value, *, minimum=0, maximum=None) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"Ожидается конечное число: {value!r}")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError("Слишком большое число") from exc
    if not math.isfinite(value):
        raise ValueError(f"Ожидается конечное число: {value!r}")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Число вне диапазона: {value!r}")
    return float(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Повторный ключ аудиокаталога: {key}")
        result[key] = value
    return result


def load_audio_catalog(path: Path | None = None) -> dict[str, AudioTrack]:
    data = json.loads((path or audio_manifest_path()).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) != {"version", "source", "tracks"}:
        raise ValueError("Некорректная структура аудиокаталога")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Неподдерживаемая версия аудиокаталога")
    if not isinstance(data["source"], str) or not isinstance(data["tracks"], dict) or not data["tracks"]:
        raise ValueError("Аудиокаталог должен содержать источник и tracks")
    result = {}
    for key, entry in data["tracks"].items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or not isinstance(entry, list) or len(entry) != 2:
            raise ValueError(f"Некорректная запись аудиокаталога: {key}")
        relative, duration = entry
        if not isinstance(relative, str):
            raise ValueError(f"Некорректный путь аудио: {relative!r}")
        parts = relative.split("/")
        if (len(parts) != 2 or parts[0] not in {"music", "ambiences", "sfx"}
                or parts[1] in {"", ".", ".."} or "\\" in relative or ":" in relative
                or PurePosixPath(relative).suffix != ".ogg"):
            raise ValueError(f"Небезопасный путь аудио: {relative}")
        duration = finite_number(duration)
        if duration == 0:
            raise ValueError(f"Нулевая длительность аудио: {key}")
        result[key] = AudioTrack(relative, duration)
    return result


def resolve_audio_path(sound_dir: Path, track: AudioTrack) -> Path:
    root = sound_dir.resolve()
    path = (root / track.path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Путь аудио выходит за пределы TS/sound: {track.path}")
    return path


def validate_audio_assets(ts_dir: Path, catalog: dict[str, AudioTrack] | None = None) -> list[str]:
    errors = []
    for track in set((catalog if catalog is not None else load_audio_catalog()).values()):
        try:
            path = resolve_audio_path(ts_dir / "sound", track)
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"Аудиофайл отсутствует или пуст: TS/sound/{track.path}")
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    return sorted(errors)
