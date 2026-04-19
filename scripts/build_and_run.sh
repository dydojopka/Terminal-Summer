#!/bin/bash
# Установка зависимостей
pip install pyinstaller requests rich textual Pillow pil2ansi yaml

# Сборка
pyinstaller --onefile \
            --name "Terminal-Summer-Linux" \
            --add-data "src/gameUI.tcss:." \
            --paths src \
            --paths scripts \
            --clean \
            src/main.py

echo "Сборка завершена! Исполняемый файл находится в папке dist/"