"""Shared strict grammar and channel contract for runtime and validators."""

from dataclasses import dataclass
import re

from audio_catalog import AudioTrack, finite_number


CHANNELS = ("music", "ambience", "sfx", "sfx2", "loop", "loop2")
LOOP_CHANNELS = frozenset({"music", "ambience", "loop", "loop2"})
CHANNEL_GROUPS = {"music": "music", "ambience": "environment", "loop": "environment",
                  "loop2": "environment", "sfx": "effects", "sfx2": "effects"}
NUMBER = r"\d+(?:\.\d+)?"


@dataclass(frozen=True)
class AudioCommand:
    action: str
    channel: str
    key: str | None = None
    value: float = 0.0


def canonical_channel(channel: str) -> str:
    channel = "sfx2" if channel == "sfx_2" else channel
    if channel not in CHANNELS:
        raise ValueError(f"Неизвестный аудиоканал: {channel}")
    return channel


def validate_audio_key(channel: str, key: str, catalog: dict[str, AudioTrack]) -> None:
    if key not in catalog:
        raise ValueError(f"Неизвестный аудиоресурс: {key}")
    # Original scripts also play ambience resources as one-shot/loop effects.
    if (channel == "music") != catalog[key].path.startswith("music/"):
        raise ValueError(f"Аудиоресурс {key} не подходит для канала {channel}")


def parse_audio_command(line: str, catalog: dict[str, AudioTrack]) -> AudioCommand:
    match = re.fullmatch(rf"play\s+(\w+)\s+(\w+)(?:\s+fadein\s+({NUMBER}))?", line)
    if match:
        channel, key, fade = match.groups()
        channel = canonical_channel(channel)
        validate_audio_key(channel, key, catalog)
        return AudioCommand("play", channel, key, finite_number(float(fade or 0)))
    match = re.fullmatch(rf"stop\s+(\w+)(?:\s+fadeout\s+({NUMBER}))?", line)
    if match:
        channel, fade = match.groups()
        return AudioCommand("stop", canonical_channel(channel), value=finite_number(float(fade or 0)))
    match = re.fullmatch(rf"volume\s+(\w+)\s+({NUMBER})", line)
    if match:
        channel, value = match.groups()
        return AudioCommand("volume", canonical_channel(channel), value=finite_number(float(value), maximum=1))
    raise ValueError(f"Некорректная аудиокоманда: {line}")
