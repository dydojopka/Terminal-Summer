"""Пути к установленным ассетам, ресурсам сборки и пользовательским данным."""

from pathlib import Path
import sys


SRC_DIR = Path(__file__).resolve().parent


def get_frozen_bundle_dir() -> Path | None:
    """Временный каталог ресурсов PyInstaller, не место для записи данных."""
    bundle_dir = getattr(sys, "_MEIPASS", None)
    return Path(bundle_dir) if bundle_dir is not None else None


def get_project_root() -> Path:
    if get_frozen_bundle_dir() is not None:
        return Path(sys.executable).resolve().parent
    return SRC_DIR.parent


def get_resource_path(relative_path: str) -> Path:
    return (get_frozen_bundle_dir() or SRC_DIR) / relative_path


def get_ts_path() -> Path:
    return get_project_root() / "TS"


def get_user_data_dir() -> Path:
    """В dev — src, в сборке — рядом с исполняемым файлом."""
    return get_project_root() if get_frozen_bundle_dir() is not None else SRC_DIR
