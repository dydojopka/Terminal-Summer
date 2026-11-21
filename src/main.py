"""Точка входа для запуска из исходников и сборки PyInstaller."""

import sys

from paths import get_frozen_bundle_dir, get_project_root
from single_instance import AlreadyRunningError, single_instance


def main() -> None:
    from app import TerminalSummer

    if get_frozen_bundle_dir() is None:
        sys.path.insert(0, str(get_project_root()))
    try:
        with single_instance(TerminalSummer.PERSISTENT_FILE.parent):
            from scripts.assets_manager import ensure_assets

            ensure_assets(quiet=True, require_endings=True)
            TerminalSummer().run()
    except AlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
