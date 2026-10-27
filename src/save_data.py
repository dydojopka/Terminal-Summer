"""Проверка отображаемых секций save до изменения текущей игры."""

import re
from rich.errors import MarkupError
from rich.text import Text

from sprites_builder import parse_show_like, normalize_sprite_position, SPRITE_SIZES


def plain_save_text(value: str) -> str:
    """Читаемое превью без активной разметки; повреждённые теги — литералы."""
    try:
        return Text.from_markup(value).plain
    except MarkupError:
        return value


def validate_save_view(data: dict) -> tuple[dict, dict, dict]:
    scene, sprites, dialogue = (data.get(key, {}) for key in ("scene", "sprites", "dialogue"))
    if not all(isinstance(section, dict) for section in (scene, sprites, dialogue)):
        raise ValueError("Invalid save section")
    scene = {"current_scene": "", "current_scene_category": "", "current_time": "day",
             "current_text_mode": "adv", "window_visible": True, **scene}
    for key in ("current_scene", "current_scene_category", "current_time", "current_text_mode"):
        if not isinstance(scene[key], str):
            raise ValueError(f"Invalid scene field: {key}")
    if (not re.fullmatch(r"[a-zA-Z0-9_]*", scene["current_scene"])
            or scene["current_scene_category"] not in ("", "bg", "cg", "color")
            or scene["current_time"] not in ("day", "sunset", "night")
            or scene["current_text_mode"] not in ("adv", "nvl")
            or type(scene["window_visible"]) is not bool
            or (scene["current_scene_category"] == "color" and scene["current_scene"] not in ("black", "white"))):
        raise ValueError("Invalid scene values")
    dialogue = {"speaker": "", "text": "", "speaker_id": None, **dialogue}
    if any(not isinstance(dialogue[key], str) for key in ("speaker", "text")):
        raise ValueError("Invalid dialogue text")
    identity = dialogue["speaker_id"]
    if identity is not None and (not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", identity)):
        raise ValueError("Invalid dialogue speaker_id")
    try:
        Text.from_markup(dialogue["text"])
        Text.from_markup(dialogue["speaker"])
    except MarkupError as exc:
        raise ValueError("Invalid dialogue markup") from exc
    active, order = sprites.get("active_sprites", {}), sprites.get("sprite_order_seq", 0)
    if not isinstance(active, dict) or type(order) is not int or order < 0:
        raise ValueError("Invalid sprites section")
    normalized = {}
    for identity, item in active.items():
        if not isinstance(identity, str) or not isinstance(item, dict):
            raise ValueError("Invalid sprite entry")
        line = item.get("show_line")
        if not isinstance(line, str) or not line.startswith("show "):
            raise ValueError("Invalid sprite show_line")
        request = parse_show_like(line)
        if request.character != identity or item.get("character") != identity:
            raise ValueError("Invalid sprite character")
        value = {"character": identity, "show_line": line, "at": "center", "size": "normal",
                 "behind": None, "order": 0}
        for key in ("at", "size", "behind", "order"):
            if key in item:
                value[key] = item[key]
        if not isinstance(value["at"], str) or not isinstance(value["size"], str):
            raise ValueError("Invalid sprite placement")
        value["at"] = normalize_sprite_position(value["at"])
        if (value["size"] not in SPRITE_SIZES
                or type(value["order"]) is not int or value["order"] < 0
                or (value["behind"] is not None and (not isinstance(value["behind"], str)
                    or not re.fullmatch(r"[a-zA-Z0-9_]+", value["behind"])))):
            raise ValueError("Invalid sprite placement")
        normalized[identity] = value
    return scene, {"active_sprites": normalized, "sprite_order_seq": max(
        order, max((item["order"] for item in normalized.values()), default=0))}, dialogue
