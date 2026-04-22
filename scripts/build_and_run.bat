@echo off
setlocal
cd /d "%~dp0\.."

set "APP_NAME=Terminal-Summer-Windows"
set "PYI_BUILD_DIR=build\pyinstaller"

python -m pip install -r requirements.txt
python -m pip install pyinstaller requests PyYAML

python -m PyInstaller --onefile ^
                      --name "%APP_NAME%" ^
                      --add-data "src/gameUI.tcss;." ^
                      --paths src ^
                      --paths scripts ^
                      --hidden-import assets_manager ^
                      --distpath "." ^
                      --workpath "%PYI_BUILD_DIR%" ^
                      --specpath "%PYI_BUILD_DIR%" ^
                      --noconfirm ^
                      --clean ^
                      src/main.py

echo Сборка завершена! Файл: %cd%\%APP_NAME%.exe
pause
