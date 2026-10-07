#!/usr/bin/env python3
"""Переносит старую галерею в TS/images; удаление копий требует явного флага."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from gallery_catalog import load_gallery_catalog, resolve_gallery_image, validate_gallery_assets
from scripts.assets_manager import migrate_legacy_gallery


def remove_legacy_duplicates(ts_dir: Path, catalog: dict) -> tuple[int, int]:
    """Удаляет только записи каталога с побайтово идентичной игровой копией."""
    errors = validate_gallery_assets(ts_dir, catalog, verify_images=True)
    if errors:
        raise ValueError("\n".join(errors))
    legacy = ts_dir / "gallery"
    if legacy.is_symlink():
        raise ValueError("Нельзя очищать TS/gallery: папка является символической ссылкой")
    removed = 0
    freed = 0
    for images in catalog.values():
        for image in images:
            source = legacy / image.path
            if source.parent.is_symlink() or source.is_symlink() or not source.is_file():
                continue
            if not source.resolve().is_relative_to(legacy.resolve()):
                raise ValueError(f"Путь старого изображения галереи выходит за пределы TS/gallery: {image.path}")
            target = resolve_gallery_image(ts_dir / "images", image)
            size = source.stat().st_size
            if size == target.stat().st_size and (
                hashlib.sha256(source.read_bytes()).digest()
                == hashlib.sha256(target.read_bytes()).digest()
            ):
                source.unlink()
                removed += 1
                freed += size
    for directory in (legacy / "bg", legacy / "cg", legacy):
        if directory.is_dir() and not directory.is_symlink() and not any(directory.iterdir()):
            directory.rmdir()
    return removed, freed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remove-duplicates", action="store_true",
        help="Удалить только проверенные идентичные копии; остальные файлы сохранить",
    )
    args = parser.parse_args()
    try:
        ts_dir = ROOT_DIR / "TS"
        copied = migrate_legacy_gallery(ts_dir)
        catalog = load_gallery_catalog()
        errors = validate_gallery_assets(ts_dir, catalog, verify_images=True)
        if errors:
            raise ValueError("\n".join(errors))
        print(f"Перенесено недостающих изображений: {copied}.")
        if args.remove_duplicates:
            removed, freed = remove_legacy_duplicates(ts_dir, catalog)
            print(f"Удалено проверенных копий: {removed}; освобождено {freed / 1024**2:.2f} МиБ.")
        return 0
    except OSError:
        print("Ошибка миграции: не удалось прочитать, перенести или удалить файл ассетов.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Ошибка миграции: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
