#!/usr/bin/env python3
"""Validate the explicit audio catalog and every TXT audio command, without UI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from audio_catalog import load_audio_catalog, resolve_audio_path, validate_audio_assets
from script_audio import parse_audio_command
from music_catalog import validate_music_assets


def validate_audio(ts_dir: Path, *, decode=False) -> list[str]:
    catalog = load_audio_catalog()
    errors = validate_audio_assets(ts_dir, catalog)
    errors.extend(validate_music_assets(ts_dir, audio_catalog=catalog))
    scripts = sorted((ts_dir / "text").glob("*.txt"))
    if not scripts:
        errors.append(f"Нет TXT-сценариев: {ts_dir / 'text'}")
    for path in scripts:
        if path.stem == "test":
            continue
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if line.split(maxsplit=1)[:1] not in (["play"], ["stop"], ["volume"]):
                continue
            try:
                parse_audio_command(line, catalog)
            except ValueError as exc:
                errors.append(f"{path.name}:{number}: {exc}")
    if decode and not errors:
        # Offline integrity test only; no hardware playback, not a runtime dependency.
        import os
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
        from pygame import mixer
        mixer.init(frequency=48000, size=-16, channels=2)
        try:
            for track in sorted(set(catalog.values()), key=lambda item: item.path):
                try:
                    sound = mixer.Sound(str(resolve_audio_path(ts_dir / "sound", track)))
                    # Vorbis preroll/padding/resampling differs between ffprobe's
                    # container duration and SDL_mixer's decoded PCM length.
                    if abs(sound.get_length() - track.duration) > 0.5:
                        errors.append(f"Длительность отличается от каталога: {track.path}")
                    del sound
                except Exception as exc:
                    errors.append(f"Аудио не декодируется: {track.path}: {exc}")
        finally:
            mixer.quit()
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts-dir", type=Path, default=ROOT_DIR / "TS")
    parser.add_argument("--decode", action="store_true", help="Полное декодирование через pygame, без аудиоустройства")
    args = parser.parse_args()
    try:
        errors = validate_audio(args.ts_dir, decode=args.decode)
    except Exception as exc:
        errors = [str(exc)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("PASS: аудиокаталог, 67 треков музыкальной комнаты, файлы и все TXT-аудиокоманды" + ("; декодирование pygame" if args.decode else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
