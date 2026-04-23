@echo off
setlocal
cd /d "%~dp0\.."

set "PYTHON_BIN=python"
set "APP_NAME=Terminal-Summer-Windows"
set "PYI_BUILD_DIR=build\pyinstaller"
set "ROOT_DIR=%cd%"

REM Проверка окружения
"%PYTHON_BIN%" --version >nul 2>&1 || (
    echo Ошибка: Python не найден в PATH.
    echo Создайте/активируйте виртуальное окружение и установите зависимости вручную
    exit /b 1
)

"%PYTHON_BIN%" -m PyInstaller --version >nul 2>&1 || (
    echo Ошибка: модуль PyInstaller не найден в текущем окружении
    echo Установите его вручную: %PYTHON_BIN% -m pip install pyinstaller
    exit /b 1
)

REM Подготовка ассетов в корне проекта
"%PYTHON_BIN%" "%ROOT_DIR%\scripts\assets_manager.py" || exit /b 1

"%PYTHON_BIN%" -m PyInstaller --onefile ^
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

echo Сборка завершена: %cd%\%APP_NAME%.exe
echo Запуск из корня проекта: %APP_NAME%.exe
pause
