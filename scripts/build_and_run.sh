#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

APP_NAME="terminal-summer"
PYI_BUILD_DIR="${ROOT_DIR}/build/pyinstaller"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Проверка зависимостей окружения
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "Ошибка: не найден Python (${PYTHON_BIN})."
    echo "Создате/активируйте виртуальное окружение и установите зависимости"
    exit 1
fi

if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "Ошибка: требуется Python 3.10 или новее."
    exit 1
fi

if ! "${PYTHON_BIN}" -m PyInstaller --version >/dev/null 2>&1; then
    echo "Ошибка: модуль PyInstaller не найден в текущем окружении"
    echo "Установи его вручную: ${PYTHON_BIN} -m pip install pyinstaller"
    exit 1
fi

# Подготовка ассетов в корне проекта
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/assets_manager.py" --require-audio

# Проверка выпущенных сценариев и ресурсов до дорогостоящей сборки
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/validate_release.py" --day 2 --day 3
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/validate_gallery.py"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/validate_audio.py" --decode

# Сборка
"${PYTHON_BIN}" -m PyInstaller --onefile \
                       --name "${APP_NAME}" \
                       --add-data "${ROOT_DIR}/src/gameUI.tcss:." \
                        --add-data "${ROOT_DIR}/src/menu_logo.ansi:." \
                         --add-data "${ROOT_DIR}/src/gallery_manifest.json:." \
                          --add-data "${ROOT_DIR}/src/audio_manifest.json:." \
                          --add-data "${ROOT_DIR}/src/music_manifest.json:." \
                       --add-data "${ROOT_DIR}/TS/text/prologue.txt:TS/text" \
                       --add-data "${ROOT_DIR}/TS/text/day*.txt:TS/text" \
                       --add-data "${ROOT_DIR}/TS/text/epilogue*.txt:TS/text" \
                       --add-data "${ROOT_DIR}/TS/text/endings.txt:TS/text" \
                       --paths "${ROOT_DIR}/src" \
                       --paths "${ROOT_DIR}/scripts" \
                       --distpath "${ROOT_DIR}" \
                       --workpath "${PYI_BUILD_DIR}" \
                       --specpath "${PYI_BUILD_DIR}" \
                       --noconfirm \
                       --clean \
                       "${ROOT_DIR}/src/main.py"

echo "Сборка завершена: ${ROOT_DIR}/${APP_NAME}"
echo "Запуск из корня проекта: ./${APP_NAME}"
