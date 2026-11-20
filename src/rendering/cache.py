"""Потокобезопасные LRU-кэши и их общая эпоха."""

from collections import OrderedDict
import hashlib
from pathlib import Path
from threading import RLock

from PIL import Image
from rich.text import Text


def file_signature(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class RenderCache:
    _FRAME_LIMIT = 96
    _RGBA_BYTE_LIMIT = 128 * 1024 * 1024
    _FINGERPRINT_LIMIT = 2048
    _VALIDATED_SPRITE_LIMIT = 256

    def __init__(self) -> None:
        self._lock = RLock()
        self._epoch = 0
        self._frames: OrderedDict[tuple, Text] = OrderedDict()
        self._images: OrderedDict[str, tuple[Image.Image, int]] = OrderedDict()
        self._image_bytes = 0
        self._fingerprints: OrderedDict[str, tuple[tuple, str]] = OrderedDict()
        self._validated_sprites: OrderedDict[str, tuple] = OrderedDict()

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def frame(self, key: tuple) -> Text | None:
        with self._lock:
            art = self._frames.get(key)
            if art is not None:
                self._frames.move_to_end(key)
            return art

    def store_frame(self, key: tuple, art: Text, epoch: int) -> None:
        with self._lock:
            if epoch != self._epoch:
                return
            self._frames[key] = art
            self._frames.move_to_end(key)
            while len(self._frames) > self._FRAME_LIMIT:
                self._frames.popitem(last=False)

    def load_rgba(self, path: str, epoch: int) -> Image.Image:
        """Возвращает изменяемую копию RGBA, сохраняя декодированный оригинал."""
        with self._lock:
            if epoch == self._epoch and (cached := self._images.get(path)) is not None:
                self._images.move_to_end(path)
                return cached[0].copy()

        with Image.open(path) as source:
            decoded = source.convert("RGBA")
        size = decoded.width * decoded.height * 4

        with self._lock:
            if epoch != self._epoch:
                return decoded
            existing = self._images.get(path)
            if existing is not None:
                decoded.close()
                self._images.move_to_end(path)
                return existing[0].copy()
            if size <= self._RGBA_BYTE_LIMIT:
                self._images[path] = (decoded, size)
                self._image_bytes += size
                while self._image_bytes > self._RGBA_BYTE_LIMIT:
                    _, (old_image, old_size) = self._images.popitem(last=False)
                    self._image_bytes -= old_size
                    old_image.close()
                return decoded.copy()
        return decoded

    def asset_fingerprint(self, path: Path, epoch: int) -> str:
        name = str(path.resolve())
        signature = file_signature(path)
        with self._lock:
            cached = self._fingerprints.get(name)
            if epoch == self._epoch and cached is not None and cached[0] == signature:
                self._fingerprints.move_to_end(name)
                return cached[1]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if signature != file_signature(path):
            raise ValueError(f"Ассет изменился во время чтения: {path}")
        with self._lock:
            if epoch == self._epoch:
                self._fingerprints[name] = (signature, digest)
                self._fingerprints.move_to_end(name)
                while len(self._fingerprints) > self._FINGERPRINT_LIMIT:
                    self._fingerprints.popitem(last=False)
        return digest

    def valid_generated_sprite(self, path: Path, epoch: int) -> bool:
        name = str(path)
        try:
            signature = file_signature(path)
            with self._lock:
                if epoch == self._epoch and self._validated_sprites.get(name) == signature:
                    return True
            with Image.open(path) as image:
                image.verify()
            with self._lock:
                if epoch == self._epoch:
                    self._validated_sprites[name] = signature
                    self._validated_sprites.move_to_end(name)
                    while len(self._validated_sprites) > self._VALIDATED_SPRITE_LIMIT:
                        self._validated_sprites.popitem(last=False)
            return True
        except (OSError, ValueError):
            return False

    def clear(self) -> None:
        with self._lock:
            # Смена эпохи и очистка атомарны относительно публикации из worker.
            self._epoch += 1
            self._frames.clear()
            self._fingerprints.clear()
            self._validated_sprites.clear()
            for image, _ in self._images.values():
                image.close()
            self._images.clear()
            self._image_bytes = 0
