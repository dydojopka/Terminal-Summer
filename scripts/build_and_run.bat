@echo off
setlocal
cd /d "%~dp0\.."

python -m pip install -r requirements.txt
python -m pip install pyinstaller requests PyYAML

python -m PyInstaller --onefile ^
                      --name "Terminal-Summer-Windows" ^
                      --add-data "src/gameUI.tcss;." ^
                      --paths src ^
                      --paths scripts ^
                      --hidden-import assets_manager ^
                      --clean ^
                      src/main.py

echo Сборка завершена! Файл: dist\Terminal-Summer-Windows.exe
pause
