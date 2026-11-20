"""Карта лагеря: явные сюжетные переходы и терминальная подсветка мест."""

from pathlib import Path
from math import ceil
import re

from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widgets import Static


MAP_SIZE = (1920, 1080)

# Границы видимых объектов с небольшим полем и точки номеров на карте.
# Широкие области клика из game/media.rpy сюда не подходят: например, область
# причала включает всю дорожку от площади, а домика — соседние дома.
# Координаты принадлежат исходному изображению, а не размеру терминала.
MAP_ZONES = {
    "me_mt_house": ((960, 170, 1002, 226), (981, 198)),
    "estrade": ((1062, 47, 1154, 144), (1104, 100)),
    "music_club": ((622, 249, 701, 345), (658, 297)),
    "square": ((881, 359, 1009, 551), (944, 463)),
    "dining_hall": ((1004, 450, 1148, 590), (1079, 519)),
    "sport_area": ((1215, 472, 1582, 664), (1440, 552)),
    "beach": ((1192, 668, 1496, 832), (1355, 738)),
    "boat_station": ((829, 797, 962, 858), (904, 827)),
    "clubs": ((429, 433, 657, 610), (560, 520)),
    "library": ((1155, 267, 1288, 368), (1220, 320)),
    "medic_house": ((1039, 352, 1142, 450), (1090, 400)),
    "camp_entrance": ((280, 435, 420, 559), (348, 510)),
    "forest": ((552, 51, 696, 199), (625, 140)),
}

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


def map_render_width(width: int, height: int, quality: int) -> int:
    """Вписывает полный кадр, учитывая два пикселя на строку терминала."""
    if width <= 0 or height <= 0:
        return 0
    return max(1, min(width, quality, int((2 * height - 1) * MAP_SIZE[0] / MAP_SIZE[1])))


def highlight_map(art: Text, zones: tuple[str, ...], selected: int | None, style: str) -> Text:
    """Рамка и номера поверх копии арта; исходный кэш рендера не меняется."""
    lines = art.split("\n")
    width, height = len(lines[0]), len(lines)
    if width < 3 or height < 2 or any(len(line) != width for line in lines):
        # Диагностику отсутствующего/повреждённого изображения не затираем.
        return art.copy()
    pixel_height = max(1, round(width * MAP_SIZE[1] / MAP_SIZE[0]))

    def point(x, y):
        return (
            min(width - 1, max(0, int(x * width / MAP_SIZE[0]))),
            min(height - 1, max(0, int(y * pixel_height / MAP_SIZE[1]) // 2)),
        )

    def put(x, y, label, text_style):
        lines[y] = (
            lines[y][:x] + Text(label, style=text_style)
            + lines[y][x + len(label):]
        )

    def paint_pixel(x, y):
        """ANSI хранит два пикселя в ячейке; соседнюю половину не затираем."""
        row = y // 2
        cell = lines[row][x]
        cell_style = Style.parse(cell.style) if isinstance(cell.style, str) else cell.style
        for span in cell.spans:
            cell_style += Style.parse(span.style) if isinstance(span.style, str) else span.style
        color = Style(bgcolor="#ff654d") if y % 2 else Style(color="#ff654d")
        put(x, row, "▀", cell_style + color)

    monochrome = style == "ASCII"
    if selected is not None and 0 <= selected < len(zones):
        (left, top, right, bottom), _ = MAP_ZONES[zones[selected]]
        x1, y1 = int(left * width / MAP_SIZE[0]), int(top * pixel_height / MAP_SIZE[1])
        x2 = min(width - 1, ceil(right * width / MAP_SIZE[0]) - 1)
        y2 = min(pixel_height - 1, ceil(bottom * pixel_height / MAP_SIZE[1]) - 1)
        if style == "ANSI":
            for x in range(x1, x2 + 1):
                paint_pixel(x, y1)
                paint_pixel(x, y2)
            for y in range(y1 + 1, y2):
                paint_pixel(x1, y)
                paint_pixel(x2, y)
        else:
            y1, y2 = y1 // 2, y2 // 2
            x2 = min(width - 1, max(x1 + 2, x2))
            x1 = min(x1, width - 3)
            frame_style = "bold reverse" if monochrome else "bold #ff654d on #241b16"
            put(x1, y1, "+" + "-" * (x2 - x1 - 1) + "+", frame_style)
            for y in range(y1 + 1, y2):
                put(x1, y, "|", frame_style)
                put(x2, y, "|", frame_style)
            if y2 > y1:
                put(x1, y2, "+" + "-" * (x2 - x1 - 1) + "+", frame_style)

    for index, zone in enumerate(zones):
        _, anchor = MAP_ZONES[zone]
        x, y = point(*anchor)
        active = index == selected
        label = f">{index + 1}<" if active else f"[{index + 1}]"
        x = max(0, min(width - len(label), x - len(label) // 2))
        marker_style = (
            "bold reverse" if active else "bold"
        ) if monochrome else (
            "bold #fff7df on #a52e1e" if active else "bold #201e18 on #efd18a"
        )
        put(x, y, label, marker_style)
    return Text("\n", no_wrap=True, overflow="crop").join(lines)


class CampMap(Static):
    """Дешёвое синхронное выделение поверх асинхронно подготовленного фона."""

    can_focus = False
    can_focus_children = False
    ALLOW_SELECT = False

    class ViewportChanged(Message):
        pass

    def __init__(self, **kwargs):
        super().__init__("", markup=False, **kwargs)
        self.zones: tuple[str, ...] = ()
        self.selected: int | None = None
        self.revision = 0
        self.request_key = None
        self.art_key = None
        self._art = Text("")
        self._art_style = "ANSI"

    def on_mount(self) -> None:
        self.auto_links = False

    def on_resize(self) -> None:
        self.post_message(self.ViewportChanged())

    def set_zones(self, zones: tuple[str, ...]) -> None:
        self.zones = zones
        self.selected = 0 if zones else None
        self.revision += 1
        self.request_key = None
        self.preview(self.selected)

    def set_art(self, art: Text, key, style: str) -> None:
        self._art, self.art_key, self._art_style = art, key, style
        self.preview(self.selected)

    def preview(self, index: int | None) -> None:
        self.selected = index
        self.update(highlight_map(self._art, self.zones, index, self._art_style))
