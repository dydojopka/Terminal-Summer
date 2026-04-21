#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

# Установка зависимостей
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller requests PyYAML

# Сборка
python3 -m PyInstaller --onefile \
                       --name "Terminal-Summer-Linux" \
                       --add-data "src/gameUI.tcss:." \
                       --paths src \
                       --paths scripts \
                       --hidden-import assets_manager \
                       --clean \
                       src/main.py

echo "Сборка завершена! Исполняемый файл: dist/Terminal-Summer-Linux"
