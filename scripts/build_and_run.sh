#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

APP_NAME="terminal-summer"
PYI_BUILD_DIR="${ROOT_DIR}/build/pyinstaller"
LOCAL_BIN_DIR="${HOME}/.local/bin"
LINK_PATH="${LOCAL_BIN_DIR}/${APP_NAME}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Проверка зависимостей окружения
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "Ошибка: не найден Python (${PYTHON_BIN})."
    echo "Создате/активируйте виртуальное окружение и установите зависимости"
    exit 1
fi

if ! "${PYTHON_BIN}" -m PyInstaller --version >/dev/null 2>&1; then
    echo "Ошибка: модуль PyInstaller не найден в текущем окружении"
    echo "Установи его вручную: ${PYTHON_BIN} -m pip install pyinstaller"
    exit 1
fi

# Подготовка ассетов в корне проекта
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/assets_manager.py"

# Сборка
"${PYTHON_BIN}" -m PyInstaller --onefile \
                       --name "${APP_NAME}" \
                       --add-data "${ROOT_DIR}/src/gameUI.tcss:." \
                       --paths "${ROOT_DIR}/src" \
                       --paths "${ROOT_DIR}/scripts" \
                       --distpath "${ROOT_DIR}" \
                       --workpath "${PYI_BUILD_DIR}" \
                       --specpath "${PYI_BUILD_DIR}" \
                       --noconfirm \
                       --clean \
                       "${ROOT_DIR}/src/main.py"

mkdir -p "${LOCAL_BIN_DIR}"
if [[ -e "${LINK_PATH}" && ! -L "${LINK_PATH}" ]]; then
    echo "ВНИМАНИЕ: ${LINK_PATH} уже существует и не является symlink."
    echo "Создай symlink вручную: ln -s \"${ROOT_DIR}/${APP_NAME}\" \"${LINK_PATH}\""
else
    ln -sfn "${ROOT_DIR}/${APP_NAME}" "${LINK_PATH}"
fi

echo "Сборка завершена: ${ROOT_DIR}/${APP_NAME}"
echo "Команда для запуска из любого места: ${APP_NAME}"

if [[ ":${PATH}:" != *":${LOCAL_BIN_DIR}:"* ]]; then
    echo "ВНИМАНИЕ: ${LOCAL_BIN_DIR} не в PATH."
    echo "Добавте в ~/.bashrc: export PATH=\"${LOCAL_BIN_DIR}:\$PATH\""
fi
