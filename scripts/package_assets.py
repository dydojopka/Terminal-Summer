#!/usr/bin/env python3
"""Готовит TS-v4-audio.zip с изображениями и звуками, без сценариев/generated."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from gallery_catalog import load_gallery_catalog, validate_gallery_assets
from audio_catalog import validate_audio_assets
from music_catalog import validate_music_assets
from scripts.assets_manager import migrate_legacy_gallery


def create_assets_archive(ts_dir: Path, output: Path, catalog: dict, *, include_audio: bool = True) -> None:
    if output.resolve().is_relative_to(ts_dir.resolve()):
        raise ValueError("Архив нужно сохранить за пределами папки TS")
    errors = validate_gallery_assets(ts_dir, catalog, verify_images=True)
    if include_audio:
        errors.extend(validate_audio_assets(ts_dir))
        errors.extend(validate_music_assets(ts_dir))
    resources = ts_dir / "resources.yaml"
    if not resources.is_file():
        errors.append("Файл ресурсов не найден: TS/resources.yaml")
    if errors:
        raise ValueError("\n".join(errors))

    files = [resources]
    for path in sorted((ts_dir / "images").rglob("*")):
        relative = path.relative_to(ts_dir)
        if relative.parts[:3] in (
            ("images", "sprites", "generated"),
            ("images", "sprites", "generated_runtime"),
        ):
            continue
        if path.is_file():
            if not path.resolve().is_relative_to(ts_dir.resolve()):
                raise ValueError(f"Путь ассета выходит за пределы папки TS: {path}")
            files.append(path)
    if include_audio:
        for path in sorted((ts_dir / "sound").rglob("*.ogg")):
            if path.is_file():
                if not path.resolve().is_relative_to((ts_dir / "sound").resolve()):
                    raise ValueError(f"Путь аудио выходит за пределы TS/sound: {path}")
                files.append(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Не перезаписываем уже подготовленные архивы.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "TS/" + path.relative_to(ts_dir).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT_DIR / "build" / "TS-v4-audio.zip",
        help="Путь к новому архиву (по умолчанию: build/TS-v4-audio.zip)",
    )
    args = parser.parse_args()
    try:
        migrate_legacy_gallery(ROOT_DIR / "TS")
        create_assets_archive(ROOT_DIR / "TS", args.output, load_gallery_catalog())
    except FileExistsError:
        print(f"Ошибка упаковки: архив уже существует: {args.output}. Укажите другой путь через --output.", file=sys.stderr)
        return 1
    except OSError:
        print(f"Ошибка упаковки: не удалось прочитать ассеты или записать архив {args.output}.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Ошибка упаковки: {exc}", file=sys.stderr)
        return 1
    print(f"Архив готов: {args.output} ({args.output.stat().st_size / 1024**2:.2f} МиБ).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
