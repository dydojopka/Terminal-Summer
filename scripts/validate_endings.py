#!/usr/bin/env python3
"""Проверяет готовые ANSI-иконки концовок, не создавая и не изменяя ассеты."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from endings_catalog import ENDING_ICON_WIDTHS, load_endings_catalog, validate_endings_assets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts-dir", type=Path, default=ROOT_DIR / "TS")
    args = parser.parse_args()
    try:
        catalog = load_endings_catalog()
        errors = validate_endings_assets(args.ts_dir, catalog)
    except OSError:
        errors = ["Не удалось прочитать каталог или ANSI-иконки концовок"]
    except ValueError as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"[ОШИБКА] {error}", file=sys.stderr)
        return 1
    count = len(catalog) * len(ENDING_ICON_WIDTHS) * 2
    print(f"Концовки проверены: {len(catalog)} концовок, {count} ANSI-иконок.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
