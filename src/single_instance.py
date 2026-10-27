"""Межпроцессная блокировка каталога пользовательских данных, без PID-файлов."""

from contextlib import contextmanager
import os
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    pass


@contextmanager
def single_instance(data_dir: Path):
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    # Не удаляем файл: иначе новый процесс сможет заблокировать другой inode.
    with (data_dir / ".terminal-summer.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise AlreadyRunningError("Terminal Summer уже запущена для этой папки данных.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AlreadyRunningError("Terminal Summer уже запущена для этой папки данных.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
