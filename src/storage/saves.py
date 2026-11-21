"""Дисковый формат слотов сохранений; без доступа к текущей игре."""

import hashlib
import json
from pathlib import Path

from file_io import write_json_atomic
from paths import get_user_data_dir


SAVES_PATH = get_user_data_dir() / "saves"
CORRUPT_SAVE = "Повреждённое сохранение"


def slot_path(page: int, slot: int) -> Path:
    return SAVES_PATH / str(page + 1) / f"{slot + 1}.json"


def slot_digest(page: int, slot: int) -> bytes:
    """Содержимое слота могло измениться, пока диалог подтверждения был открыт."""
    return hashlib.sha256(slot_path(page, slot).read_bytes()).digest()


def _read_slot(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict):
        raise ValueError("Invalid save file")
    if not isinstance(data.get("game_state"), dict):
        raise ValueError("Invalid game state")
    return data


def save_game_state(page: int, slot: int, game_state: dict, timestamp: str = "") -> None:
    path = slot_path(page, slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {
        "save_id": f"{page}/{slot}",
        "page": page,
        "slot": slot,
        "timestamp": timestamp,
        "game_state": game_state,
    })


def load_game_state(page: int, slot: int) -> dict | None:
    path = slot_path(page, slot)
    if not path.exists():
        return None
    return _read_slot(path)["game_state"]


def delete_save(page: int, slot: int) -> bool:
    path = slot_path(page, slot)
    if not path.exists():
        return False
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return True


def get_all_saves() -> dict[str, dict]:
    saves = {}
    if not SAVES_PATH.exists():
        return saves
    for page_dir in SAVES_PATH.iterdir():
        if not page_dir.is_dir():
            continue
        try:
            page = int(page_dir.name) - 1
        except ValueError:
            continue
        for path in page_dir.glob("*.json"):
            try:
                slot = int(path.stem) - 1
            except ValueError:
                continue
            save_id = f"{page}/{slot}"
            try:
                saves[save_id] = _read_slot(path)
            except (OSError, ValueError):
                saves[save_id] = {"error": CORRUPT_SAVE}
    return saves
