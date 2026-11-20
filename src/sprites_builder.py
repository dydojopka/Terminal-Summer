#!/usr/bin/env python3
"""Совместимая точка запуска; основная команда — scripts/build_sprites.py."""

if __name__ == "__main__":
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.build_sprites import main

    raise SystemExit(main())
