@echo off
pip install pyinstaller requests rich textual Pillow pil2ansi yaml
pyinstaller --onefile ^
            --name "Terminal-Summer-Windows" ^
            --add-data "src/gameUI.tcss;." ^
            --paths src ^
            --paths scripts ^
            --clean ^
            src/main.py
echo Сборка завершена! Файл в папке dist.
pause