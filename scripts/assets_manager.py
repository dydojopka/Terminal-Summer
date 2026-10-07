import os
import sys
import shutil
import zipfile
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

if not hasattr(sys, "_MEIPASS"):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gallery_catalog import load_gallery_catalog, resolve_gallery_image, validate_gallery_assets

# Старый архив поддерживается до публикации TS-v3.zip; URL можно сменить без сборки.
ASSETS_URL = os.environ.get(
    "TS_ASSETS_URL", "https://storage.yandexcloud.net/terminal-summer-assets/TS.zip"
)

def get_project_root() -> Path:
    """Возвращает рабочий корень, где должны лежать папка TS и settings"""
    if hasattr(sys, "_MEIPASS"):
        # Для onefile-сборки работаем рядом с бинарником
        return Path(sys.executable).resolve().parent
    # scripts/assets_manager.py -> корень проекта на уровень выше scripts
    return Path(__file__).resolve().parent.parent


def _required_asset_paths() -> list[Path]:
    ts_dir = get_project_root() / "TS"
    return [
        ts_dir / "images",
        ts_dir / "text",
        ts_dir / "resources.yaml",
    ]

def check_assets() -> bool:
    """Проверяет основные пути и каждое изображение из каталога галереи."""
    return all(path.exists() for path in _required_asset_paths()) and not validate_gallery_assets(
        get_project_root() / "TS", load_gallery_catalog()
    )


def migrate_legacy_images(ts_dir: Path | None = None) -> None:
    """Переименовывает старую TS/game или переносит её файлы без перезаписи."""
    ts_dir = get_project_root() / "TS" if ts_dir is None else ts_dir
    legacy = ts_dir / "game"
    images = ts_dir / "images"
    if not legacy.exists() and not legacy.is_symlink():
        return
    if legacy.is_symlink() or not legacy.is_dir():
        raise ValueError("Нельзя перенести TS/game: ожидается папка без символической ссылки")
    if not images.exists() and not images.is_symlink():
        legacy.rename(images)
        return
    if images.is_symlink() or not images.is_dir():
        raise ValueError("Нельзя перенести ассеты: TS/images должна быть папкой без символической ссылки")

    def merge(source_dir: Path, target_dir: Path) -> None:
        for source in source_dir.iterdir():
            target = target_dir / source.name
            if source.is_symlink() or target.is_symlink():
                continue
            if not target.exists():
                source.rename(target)
            elif source.is_dir() and target.is_dir():
                merge(source, target)
        if not any(source_dir.iterdir()):
            source_dir.rmdir()

    merge(legacy, images)


def migrate_legacy_gallery(ts_dir: Path | None = None) -> int:
    """Копирует недостающие изображения из старой галереи, ничего не удаляя."""
    ts_dir = get_project_root() / "TS" if ts_dir is None else ts_dir
    migrate_legacy_images(ts_dir)
    copied = 0
    for images in load_gallery_catalog().values():
        for image in images:
            original_path = ts_dir / "images" / image.path
            if original_path.is_symlink():
                # Не изменяем даже сломанные пользовательские ссылки.
                continue
            destination = resolve_gallery_image(ts_dir / "images", image)
            if destination.exists():
                continue
            source = resolve_gallery_image(ts_dir / "gallery", image)
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied += 1
    return copied


def restore_bundled_scripts() -> None:
    """Восстанавливает отсутствующие сценарии onefile, не затирая внешние."""
    if not hasattr(sys, "_MEIPASS"):
        return
    source = Path(sys._MEIPASS) / "TS" / "text"
    target = get_project_root() / "TS" / "text"
    for script in source.glob("*.txt"):
        destination = target / script.name
        if not destination.exists():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(script, destination)


def _safe_extract(zip_ref: zipfile.ZipFile, target_dir: Path) -> None:
    """Безопасная распаковка без перезаписи; старые TS/game идут в TS/images."""
    target_dir = target_dir.resolve()
    destinations = []
    for member in zip_ref.infolist():
        name = member.filename
        if name == "TS/game" or name.startswith("TS/game/"):
            name = "TS/images" + name[len("TS/game"):]
        original_dest = target_dir / name
        dest = original_dest.resolve()
        try:
            dest.relative_to(target_dir)
        except ValueError:
            raise RuntimeError(f"Небезопасный путь в архиве: {member.filename}")
        destinations.append((member, original_dest, dest))
    for member, original_dest, dest in destinations:
        if member.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists() and not original_dest.is_symlink():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zip_ref.open(member) as source, dest.open("xb") as target:
                shutil.copyfileobj(source, target)

def download_assets():
    """Скачивает и распаковывает архив с визуализацией прогресса"""
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "Модуль 'requests' не установлен. Установите зависимости из requirements.txt"
        ) from exc

    root = get_project_root()
    zip_path = root / "TS_temp.zip"
    root.mkdir(parents=True, exist_ok=True)

    print("Менеджер ассетов Terminal Summer")
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
        ) as progress:
            task_id = progress.add_task("Загрузка ресурсов...", total=None)

            with requests.get(ASSETS_URL, stream=True, timeout=60) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                progress.update(task_id, total=total_size)

                with zip_path.open("wb") as f:
                    for data in response.iter_content(chunk_size=1024 * 1024):
                        if not data:
                            continue
                        f.write(data)
                        progress.update(task_id, advance=len(data))

            progress.update(task_id, description="Распаковка архива...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                _safe_extract(zip_ref, root)
    except requests.RequestException as exc:
        raise RuntimeError(
            "Не удалось скачать архив ассетов. Проверьте подключение к сети и адрес загрузки."
        ) from exc
    except zipfile.BadZipFile as exc:
        raise RuntimeError("Скачанный архив ассетов повреждён или не является ZIP-архивом") from exc
    except OSError as exc:
        raise RuntimeError("Не удалось сохранить или распаковать архив ассетов") from exc
    finally:
        if zip_path.exists():
            zip_path.unlink()

    migrate_legacy_gallery()
    if not check_assets():
        raise RuntimeError("Ассеты скачаны, но необходимые файлы всё ещё отсутствуют")

    print("Все ресурсы успешно скачаны!\n")


def ensure_assets(*, quiet: bool = False) -> None:
    """Гарантирует наличие ассетов в рабочем корне"""
    restore_bundled_scripts()
    migrate_legacy_gallery()
    if check_assets():
        if not quiet:
            print("Ассеты уже есть. Скачивание не требуется")
        return
    print("Ассеты не найдены. Запускаю загрузку...", file=sys.stderr)
    download_assets()


def main() -> None:
    try:
        ensure_assets()
    except OSError:
        print("Ошибка менеджера ассетов: не удалось прочитать или записать файл ассетов.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"Ошибка менеджера ассетов: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
