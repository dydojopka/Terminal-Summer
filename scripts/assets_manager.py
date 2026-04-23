import sys
import zipfile
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

# Твоя ссылка из Yandex Cloud
ASSETS_URL = "https://storage.yandexcloud.net/terminal-summer-assets/TS.zip"

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
        ts_dir / "gallery",
        ts_dir / "game",
        ts_dir / "text",
        ts_dir / "resources.yaml",
    ]

def check_assets() -> bool:
    """Проверяет наличие необходимых папок и файлов"""
    return all(path.exists() for path in _required_asset_paths())


def _safe_extract(zip_ref: zipfile.ZipFile, target_dir: Path) -> None:
    """Безопасная распаковка архива без выхода за target_dir."""
    target_dir = target_dir.resolve()
    for member in zip_ref.infolist():
        dest = (target_dir / member.filename).resolve()
        try:
            dest.relative_to(target_dir)
        except ValueError:
            raise RuntimeError(f"Unsafe path in archive: {member.filename}")
    zip_ref.extractall(target_dir)

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

    print("Terminal Summer Assets Manager")
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
    finally:
        if zip_path.exists():
            zip_path.unlink()

    if not check_assets():
        raise RuntimeError("Assets downloaded, but required files are still missing")

    print("Все ресурсы успешно установлены.\n")


def ensure_assets() -> None:
    """Гарантирует наличие ассетов в рабочем корне"""
    if check_assets():
        print("Ассеты уже есть. Скачивание не требуется")
        return
    download_assets()


def main() -> None:
    try:
        ensure_assets()
    except Exception as exc:
        print(f"Ошибка менеджера ассетов: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
