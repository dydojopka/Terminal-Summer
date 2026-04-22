@echo off
setlocal
cd /d "%~dp0\.."

set "APP_NAME=Terminal-Summer-Windows"
set "PYI_BUILD_DIR=build\pyinstaller"
set "ROOT_DIR=%cd%"

python -m pip install -r requirements.txt
python -m pip install pyinstaller requests PyYAML

python -m PyInstaller --onefile ^
                      --name "%APP_NAME%" ^
                      --add-data "%ROOT_DIR%\src\gameUI.tcss;." ^
                      --paths "%ROOT_DIR%\src" ^
                      --paths "%ROOT_DIR%\scripts" ^
                      --hidden-import assets_manager ^
                      --distpath "." ^
                      --workpath "%PYI_BUILD_DIR%" ^
                      --specpath "%PYI_BUILD_DIR%" ^
                      --noconfirm ^
                      --clean ^
                      "%ROOT_DIR%\src\main.py"

echo Сборка завершена! Файл: %cd%\%APP_NAME%.exe
pause
