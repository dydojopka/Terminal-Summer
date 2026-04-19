import os
import sys
import zipfile
import requests
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

# Твоя ссылка из Yandex Cloud
ASSETS_URL = "https://storage.yandexcloud.net/ts-assets/TS-0.1.zip"

def get_project_root() -> Path:
    """Определяет корень проекта для разработки и для PyInstaller"""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys.executable).parent
    # Если main.py лежит в src/, то корень на уровень выше
    return Path(__file__).parent.parent.parent

def check_assets() -> bool:
    """Проверяет наличие необходимых папок и файлов"""
    root = get_project_root()
    ts_dir = root / "TS"
    
    required = [
        ts_dir / "gallery",
        ts_dir / "game",
        ts_dir / "resources.yaml"
    ]
    
    # Если хоть один критический компонент отсутствует - возвращаем False
    for path in required:
        if not path.exists():
            return False
    return True

def download_assets():
    """Скачивает и распаковывает архив с визуализацией прогресса"""
    root = get_project_root()
    zip_path = root / "TS_temp.zip"
    
    print("[bold blue]Terminal Summer Assets Manager[/bold blue]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
    ) as progress:
        
        # 1. Скачивание
        task_id = progress.add_task("Загрузка ресурсов...", total=None)
        
        response = requests.get(ASSETS_URL, stream=True)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        progress.update(task_id, total=total_size)

        with open(zip_path, "wb") as f:
            for data in response.iter_content(chunk_size=8192):
                f.write(data)
                progress.update(task_id, advance=len(data))

        # 2. Распаковка
        progress.update(task_id, description="Распаковка архива...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Распаковываем в корень, так как в архиве уже есть папка TS или её структура
            zip_ref.extractall(root)

    # Удаляем временный архив
    if zip_path.exists():
        os.remove(zip_path)
    
    print("[bold green]Все ресурсы успешно установлены![/bold green]\n")