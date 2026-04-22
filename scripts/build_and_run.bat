@echo off
setlocal
cd /d "%~dp0\.."

set "APP_NAME=Terminal-Summer-Windows"
set "PYI_BUILD_DIR=build\pyinstaller"
set "ROOT_DIR=%cd%"

python -m pip install -r requirements.txt || exit /b 1
python -m pip install pyinstaller || exit /b 1

REM Подготовка ассетов в корне проекта
python "%ROOT_DIR%\scripts\assets_manager.py" || exit /b 1

python -m PyInstaller --onefile ^
                      --name "%APP_NAME%" ^
                      --add-data "%ROOT_DIR%\src\gameUI.tcss;." ^
                      --paths "%ROOT_DIR%\src" ^
                      --paths "%ROOT_DIR%\scripts" ^
                      --distpath "." ^
                      --workpath "%PYI_BUILD_DIR%" ^
                      --specpath "%PYI_BUILD_DIR%" ^
                      --noconfirm ^
                      --clean ^
                      "%ROOT_DIR%\src\main.py" || exit /b 1

echo Сборка завершена! Файл: %cd%\%APP_NAME%.exe
pause
