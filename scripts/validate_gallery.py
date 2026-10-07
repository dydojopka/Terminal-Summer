#!/usr/bin/env python3
"""Проверяет каталог галереи и читаемость всех общих изображений."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from gallery_catalog import load_gallery_catalog, validate_gallery_assets


def main() -> int:
    try:
        catalog = load_gallery_catalog()
        errors = validate_gallery_assets(ROOT_DIR / "TS", catalog, verify_images=True)
    except OSError:
        errors = ["Не удалось прочитать каталог или изображения галереи"]
    except ValueError as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"[ОШИБКА] {error}", file=sys.stderr)
        return 1
    print(f"Галерея проверена: {len(catalog['bg'])} фонов, {len(catalog['cg'])} иллюстраций.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
