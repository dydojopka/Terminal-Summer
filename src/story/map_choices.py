"""Распознавание сюжетных выборов, которые должны показывать карту лагеря."""

from pathlib import Path
import re


# Только шесть меню, заменявших show_map в оригинале. Не распознаём карту
# по русским подписям или текущему фону: обычные ответы остаются ответами.
# TXT не меняются, поэтому хэши сценариев в существующих save сохраняются.
MAP_MENUS = {
    "day2.txt": (
        {
            "day2_clubs": "clubs",
            "day2_musclub": "music_club",
            "day2_dinner": "dining_hall",
            "day2_aidpost": "medic_house",
            "day2_library": "library",
        },
        {
            "day2_busstop_eve": "camp_entrance",
            "day2_dock_eve": "boat_station",
            "day2_square_eve": "square",
            "day2_aidpost_eve": "medic_house",
            "day2_stage_eve": "estrade",
            "day2_beach_eve": "beach",
            "day2_football_eve": "sport_area",
        },
    ),
    "day4.txt": ({
        "day4_busstop": "camp_entrance",
        "day4_boathouse": "boat_station",
        "day4_house_of_mt": "me_mt_house",
        "day4_forest": "forest",
    },),
    "day5.txt": (
        {
            "day5_clubs": "clubs",
            "day5_aidpost": "medic_house",
            "day5_dining_hall": "dining_hall",
        },
        {
            "day5_clubs_2": "clubs",
            "day5_library_2": "library",
            "day5_aidpost_2": "medic_house",
        },
    ),
    "day6.txt": ({
        "day6_aidpost": "medic_house",
        "day6_dinner": "dining_hall",
        "day6_clubs": "clubs",
    },),
}


def map_choice_zones(filename, bodies) -> tuple[str, ...]:
    """Сопоставляет доступные тела меню с одним явным набором переходов."""
    targets = []
    for body in bodies:
        if len(body) != 1 or not (match := re.fullmatch(r"goto\s+(\w+)", body[0])):
            return ()
        targets.append(match[1])
    if not targets or len(set(targets)) != len(targets):
        return ()
    for menu in MAP_MENUS.get(Path(filename).name, ()):
        if all(target in menu for target in targets):
            return tuple(menu[target] for target in targets)
    return ()
