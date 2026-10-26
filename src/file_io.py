"""Атомарная публикация файлов; временные файлы принадлежат только вызову."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def atomic_output(path: Path, *, overwrite: bool = True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", prefix=f".{path.name}.",
                                         suffix=".tmp", dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            yield target
            target.flush()
            os.fsync(target.fileno())
        if overwrite:
            os.replace(temporary, path)
        elif os.name == "nt":
            # Windows rename атомарен и не заменяет существующий файл;
            # в отличие от hard link работает также на FAT/exFAT.
            os.rename(temporary, path)
        else:
            # Атомарное create-if-absent: не затирает даже появившийся параллельно файл.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json_atomic(path: Path, data) -> None:
    encoded = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with atomic_output(path) as target:
        target.write(encoded)


def install_missing(source, path: Path) -> bool:
    try:
        with atomic_output(path, overwrite=False) as target:
            shutil.copyfileobj(source, target)
    except FileExistsError:
        return False
    return True
