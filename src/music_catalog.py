"""The original music room's explicit selection, separate from DSL aliases."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

from audio_catalog import _unique_object, load_audio_catalog, validate_audio_assets
from script_audio import validate_audio_key


@dataclass(frozen=True)
class MusicTrack:
    id: str
    title: str
    audio_key: str
    duration: float


def music_manifest_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "music_manifest.json"
    return Path(__file__).with_name("music_manifest.json")


def load_music_catalog(path: Path | None = None, *, audio_catalog=None) -> tuple[MusicTrack, ...]:
    try:
        data = json.loads((path or music_manifest_path()).read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Не удалось прочитать каталог музыки: {exc}") from exc
    if (not isinstance(data, dict) or set(data) != {"version", "tracks"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["tracks"], list) or not data["tracks"]):
        raise ValueError("Некорректная структура каталога музыки")
    audio = load_audio_catalog() if audio_catalog is None else audio_catalog
    ids, paths, titles = set(), set(), set()
    result = []
    for item in data["tracks"]:
        if not isinstance(item, dict) or set(item) != {"id", "title", "audio_key"}:
            raise ValueError("Некорректная запись каталога музыки")
        identity, title, key = item["id"], item["title"], item["audio_key"]
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9_]+", identity)
                or not isinstance(title, str) or not title.strip() or title != title.strip()
                or any(not char.isprintable() for char in title) or not isinstance(key, str)):
            raise ValueError(f"Некорректное название/ID музыкального трека: {item!r}")
        validate_audio_key("music", key, audio)
        track = audio[key]
        if identity in ids or track.path in paths or title.casefold() in titles:
            raise ValueError(f"Повторный музыкальный трек: {identity}")
        ids.add(identity)
        paths.add(track.path)
        titles.add(title.casefold())
        result.append(MusicTrack(identity, title, key, track.duration))
    if [track.title for track in result] != sorted(track.title for track in result):
        raise ValueError("Каталог музыки должен быть упорядочен по названию")
    return tuple(result)


def filter_music(tracks, query: str) -> tuple[MusicTrack, ...]:
    query = query.strip().casefold()
    return tuple(track for track in tracks if query in track.title.casefold())


def validate_music_assets(ts_dir: Path, *, tracks=None, audio_catalog=None) -> list[str]:
    audio = load_audio_catalog() if audio_catalog is None else audio_catalog
    tracks = load_music_catalog(audio_catalog=audio) if tracks is None else tracks
    errors = validate_audio_assets(ts_dir, {track.audio_key: audio[track.audio_key] for track in tracks})
    if len(tracks) != 67:
        errors.append(f"Ожидается 67 треков музыкальной комнаты, найдено {len(tracks)}")
    return errors


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
