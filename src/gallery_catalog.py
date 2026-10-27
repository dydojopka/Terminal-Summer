"""Явный каталог галереи с общими изображениями из TS/images."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class GalleryImage:
    id: str
    path: str


def get_gallery_manifest_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "gallery_manifest.json"
    return Path(__file__).with_name("gallery_manifest.json")


def load_gallery_catalog(path: Path | None = None) -> dict[str, tuple[GalleryImage, ...]]:
    manifest = get_gallery_manifest_path() if path is None else path
    try:
        content = manifest.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"Каталог галереи не найден: {manifest}") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Не удалось прочитать каталог галереи в UTF-8: {manifest}") from exc
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Некорректный JSON в каталоге галереи {manifest}: "
            f"строка {exc.lineno}, столбец {exc.colno}"
        ) from exc
    if not isinstance(data, dict) or set(data) != {"bg", "cg"}:
        raise ValueError("Каталог галереи должен содержать списки bg и cg")

    catalog = {}
    for category in ("bg", "cg"):
        if not isinstance(data[category], list):
            raise ValueError(f"Раздел галереи {category} должен быть списком")
        images = []
        ids = set()
        paths = set()
        for entry in data[category]:
            if not isinstance(entry, dict) or set(entry) != {"id", "path"}:
                raise ValueError(f"Некорректная запись галереи в разделе {category}: {entry!r}")
            image_id, relative_path = entry["id"], entry["path"]
            if not isinstance(image_id, str) or not image_id.strip():
                raise ValueError(f"Некорректный идентификатор галереи в разделе {category}: {image_id!r}")
            if not isinstance(relative_path, str):
                raise ValueError(f"Некорректный путь изображения галереи: {relative_path!r}")
            parts = relative_path.split("/")
            if (
                len(parts) != 2
                or parts[0] != category
                or parts[1] in ("", ".", "..")
                or "\\" in relative_path
                or ":" in relative_path
                or PurePosixPath(relative_path).suffix.lower() not in {".jpg", ".jpeg", ".png"}
            ):
                raise ValueError(f"Небезопасный путь или неподдерживаемый формат изображения галереи: {relative_path!r}")
            if image_id in ids or relative_path in paths:
                raise ValueError(f"Повторяющийся идентификатор или путь в разделе галереи {category}: {entry!r}")
            ids.add(image_id)
            paths.add(relative_path)
            images.append(GalleryImage(image_id, relative_path))
        catalog[category] = tuple(images)
    return catalog


def resolve_gallery_image(images_dir: Path, image: GalleryImage) -> Path:
    root = images_dir.resolve()
    path = (root / image.path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Путь изображения галереи выходит за пределы папки ассетов: {image.path}")
    return path


def validate_gallery_assets(
    ts_dir: Path,
    catalog: dict[str, tuple[GalleryImage, ...]],
    *,
    verify_images: bool = False,
) -> list[str]:
    errors = []
    for images in catalog.values():
        for image in images:
            try:
                path = resolve_gallery_image(ts_dir / "images", image)
                if not path.is_file():
                    errors.append(f"Изображение галереи не найдено: TS/images/{image.path}")
                elif verify_images:
                    from PIL import Image

                    with Image.open(path) as source:
                        source.verify()
            except OSError:
                errors.append(f"Не удалось прочитать изображение галереи: TS/images/{image.path}")
            except ValueError as exc:
                errors.append(f"Некорректное изображение галереи {image.path}: {exc}")
    return errors
