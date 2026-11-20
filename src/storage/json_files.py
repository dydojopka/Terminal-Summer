"""Запись пользовательского JSON с резервированием повреждённого файла."""

from pathlib import Path
import shutil
import time

from file_io import atomic_output, write_json_atomic


def write_user_json(path: Path, data: dict, *, backup_invalid: bool = False) -> None:
    if backup_invalid and path.exists():
        backup = path.with_name(f"{path.name}.invalid-{time.time_ns()}.bak")
        with path.open("rb") as source, atomic_output(backup, overwrite=False) as target:
            shutil.copyfileobj(source, target)
    write_json_atomic(path, data)
