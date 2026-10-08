"""Явный каталог концовок; состояние открытия хранится только в persistent."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ENDING_ICON_WIDTHS = (16, 24, 32)


@dataclass(frozen=True)
class Ending:
    id: str
    ending: str
    title: str
    flag: str

    @property
    def source_filename(self) -> str:
        return f"{self.ending} - {self.title}.png"

    def ansi_path(self, width: int, unlocked: bool) -> str:
        if type(width) is not int or width not in ENDING_ICON_WIDTHS:
            raise ValueError(f"Неизвестный размер ANSI-иконки: {width}")
        suffix = "" if unlocked else "_locked"
        return f"achievements_ansi/{width}/{self.id}{suffix}.ansi"


def endings_manifest_path() -> Path:
    root = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent
    return root / "endings_manifest.json"


def load_endings_catalog(path: Path | None = None) -> tuple[Ending, ...]:
    from script_parser import ENDING_STATE_KEYS

    manifest = endings_manifest_path() if path is None else path
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Не удалось прочитать каталог концовок: {manifest}") from exc
    if (not isinstance(data, dict) or set(data) != {"version", "endings"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["endings"], list) or not data["endings"]):
        raise ValueError("Каталог концовок должен содержать version: 1 и список endings")
    entries = []
    ids, flags = set(), set()
    for entry in data["endings"]:
        if not isinstance(entry, dict) or set(entry) != {"id", "ending", "title", "flag"}:
            raise ValueError(f"Некорректная запись концовки: {entry!r}")
        if any(not isinstance(value, str) or not value or value != value.strip()
               or any(ord(char) < 32 or ord(char) == 127 for char in value)
               for value in entry.values()):
            raise ValueError(f"Некорректное поле концовки: {entry!r}")
        item = Ending(**entry)
        if (not re.fullmatch(r"[a-z][a-z0-9_]*", item.id)
                or item.flag != f"persistent.endings_{item.id}"
                or item.flag not in ENDING_STATE_KEYS
                or any(char in item.ending + item.title for char in '/\\:')):
            raise ValueError(f"Небезопасный путь или неизвестный флаг концовки: {item.id}")
        if item.id in ids or item.flag in flags:
            raise ValueError(f"Повторяющаяся запись концовки: {item.id}")
        ids.add(item.id)
        flags.add(item.flag)
        entries.append(item)
    if flags != set(ENDING_STATE_KEYS):
        raise ValueError("Каталог должен содержать каждую сценарную концовку ровно один раз")
    return tuple(entries)


def resolve_ending_ansi(ts_dir: Path, ending: Ending, width: int, unlocked: bool) -> Path:
    root = ts_dir.resolve()
    path = (root / ending.ansi_path(width, unlocked)).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Путь ANSI-иконки выходит за пределы папки TS: {ending.id}")
    return path


def runtime_ending_ansi(ts_dir: Path, ending: Ending, width: int, unlocked: bool) -> Path:
    """Внешний ANSI имеет приоритет; missing-файл берётся из onefile."""
    path = resolve_ending_ansi(ts_dir, ending, width, unlocked)
    original = ts_dir / ending.ansi_path(width, unlocked)
    if not path.exists() and not original.is_symlink() and hasattr(sys, "_MEIPASS"):
        return resolve_ending_ansi(Path(sys._MEIPASS), ending, width, unlocked)
    return path


def validate_endings_assets(ts_dir: Path, endings: tuple[Ending, ...] | None = None) -> list[str]:
    from endings_ansi import read_ending_ansi

    errors = []
    for ending in load_endings_catalog() if endings is None else endings:
        for width in ENDING_ICON_WIDTHS:
            for unlocked in (True, False):
                try:
                    path = resolve_ending_ansi(ts_dir, ending, width, unlocked)
                    read_ending_ansi(path, width)
                except (OSError, ValueError) as exc:
                    errors.append(f"Иконка концовки TS/{ending.ansi_path(width, unlocked)}: {exc}")
    return errors
