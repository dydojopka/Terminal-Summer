#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT_DIR"

APP_NAME="terminal-summer"
PYI_BUILD_DIR="${ROOT_DIR}/build/pyinstaller"
LOCAL_BIN_DIR="${HOME}/.local/bin"
LINK_PATH="${LOCAL_BIN_DIR}/${APP_NAME}"
VENV_DIR="${ROOT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

# Подготовка виртуального окружения и зависимостей
if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "Ошибка: не найден интерпретатор виртуального окружения: ${VENV_PYTHON}"
    exit 1
fi

"${VENV_PYTHON}" -m pip install --upgrade pip
"${VENV_PYTHON}" -m pip install -r requirements.txt
"${VENV_PYTHON}" -m pip install pyinstaller

# Подготовка ассетов в корне проекта
"${VENV_PYTHON}" "${ROOT_DIR}/scripts/assets_manager.py"

# Сборка
"${VENV_PYTHON}" -m PyInstaller --onefile \
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

echo "Сборка завершена! Бинарник: ${ROOT_DIR}/${APP_NAME}"
echo "Команда для запуска из любого места: ${APP_NAME}"

if [[ ":${PATH}:" != *":${LOCAL_BIN_DIR}:"* ]]; then
    echo "ВНИМАНИЕ: ${LOCAL_BIN_DIR} не в PATH."
    echo "Добавь в ~/.bashrc: export PATH=\"${LOCAL_BIN_DIR}:\$PATH\""
fi
