import os
import re
import sys
import asyncio
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

# --- ЛОГИКА ПУТЕЙ ---
IS_FROZEN = hasattr(sys, "_MEIPASS")
SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else SRC_DIR.parent
BUNDLE_DIR = Path(sys._MEIPASS) if IS_FROZEN else SRC_DIR


def get_resource_path(relative_path: str) -> Path:
    """Путь к встроенному ресурсу (из src в dev, из _MEIPASS в сборке)"""
    return BUNDLE_DIR / relative_path


def get_ts_path() -> Path:
    """Путь к папке TS в runtime-среде"""
    return PROJECT_ROOT / "TS"


def get_settings_path() -> Path:
    """Путь к файлу настроек

    В dev сохраняем в src/settings.json
    В onefile-сборке сохраняем рядом с .exe
    """
    if IS_FROZEN:
        return PROJECT_ROOT / "settings.json"
    return SRC_DIR / "settings.json"


def get_saves_path() -> Path:
    """Путь к директории сохранений"""
    if IS_FROZEN:
        return PROJECT_ROOT / "saves"
    return SRC_DIR / "saves"


def get_persistent_path() -> Path:
    """Путь к persistent-флагам, общим для всех прохождений."""
    if IS_FROZEN:
        return PROJECT_ROOT / "persistent.json"
    return SRC_DIR / "persistent.json"


CSS_PATH = get_resource_path("gameUI.tcss")
SETTINGS_PATH = get_settings_path()
SAVES_PATH = get_saves_path()
PERSISTENT_PATH = get_persistent_path()
APP_VERSION = "0.2.0"


# ============ Сохранения ============
def _save_path(page: int, slot: int) -> Path:
    """Путь к файлу сохранения: saves/{page+1}/{slot+1}.json"""
    return SAVES_PATH / str(page + 1) / f"{slot + 1}.json"


def save_game_state(page: int, slot: int, game_state: dict, timestamp: str = "") -> None:
    """Сохранение состояния игры в JSON файл"""
    save_file = _save_path(page, slot)
    save_file.parent.mkdir(parents=True, exist_ok=True)
    save_data = {
        "save_id": f"{page}/{slot}",
        "page": page,
        "slot": slot,
        "timestamp": timestamp,
        "game_state": game_state,
    }
    with save_file.open("w", encoding="utf-8") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False)


def load_game_state(page: int, slot: int) -> dict | None:
    """Загрузка состояния игры из JSON файла"""
    save_file = _save_path(page, slot)
    if not save_file.exists():
        return None
    with save_file.open("r", encoding="utf-8") as f:
        save_data = json.load(f)
    return save_data.get("game_state")


def delete_save(page: int, slot: int) -> bool:
    """Удаление сохранения"""
    save_file = _save_path(page, slot)
    if save_file.exists():
        save_file.unlink()
        # Удаляем пустую директорию страницы, если она пуста
        try:
            save_file.parent.rmdir()
        except OSError:
            pass
        return True
    return False


def get_all_saves() -> dict[str, dict]:
    """Получение всех сохранений (возвращает dict['page/slot' -> save_data])"""
    saves = {}
    if not SAVES_PATH.exists():
        return saves
    for page_dir in SAVES_PATH.iterdir():
        if not page_dir.is_dir():
            continue
        try:
            page_num = int(page_dir.name)
        except ValueError:
            continue
        for save_file in page_dir.glob("*.json"):
            try:
                with save_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                slot_num = int(save_file.stem)
                save_id = f"{page_num - 1}/{slot_num - 1}"
                saves[save_id] = data
            except Exception:
                continue
    return saves

import asyncio
import json
from PIL import Image
from pil2ansi import convert_img, Palettes

from textual import events, errors, _time
from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Label, Footer, Header, Static, ListView, ListItem, Log, LoadingIndicator
from textual.widget import Widget
from textual.binding import Binding

from rich.style import Style
from rich.segment import Segment
from rich.text import Text

from script_parser import ScriptParser, format_script_state
from sprites_builder import (
    parse_show_like,
    load_yaml_dict as load_sprite_resources_yaml,
    resolve_sprite,
    compose_layers,
)


@dataclass(frozen=True)
class RenderSprite:
    character: str
    show_line: str
    image_path: str
    at: str
    size: str
    behind: str | None
    order: int


@dataclass(frozen=True)
class SceneRenderSnapshot:
    category: str
    name: str
    sprites: tuple[RenderSprite, ...]
    width: int
    style: str
    cache_epoch: int

    @property
    def key(self) -> tuple:
        sprite_key = tuple(
            (
                sprite.character,
                sprite.show_line,
                sprite.at,
                sprite.size,
                sprite.behind,
                sprite.order,
            )
            for sprite in self.sprites
        )
        return self.category, self.name, sprite_key, str(self.width), self.style, 2

def main():
    ts_dir = get_ts_path()
    required_paths = [
        ts_dir / "gallery",
        ts_dir / "game",
        ts_dir / "text",
        ts_dir / "resources.yaml",
    ]

    missing_paths = [path for path in required_paths if not path.exists()]
    if not missing_paths:
        return

    print("Ассеты не найдены. Запускаю загрузку...", file=sys.stderr)

    scripts_dir = PROJECT_ROOT / "scripts"
    if scripts_dir.exists():
        sys.path.insert(0, str(scripts_dir))

    try:
        from scripts.assets_manager import ensure_assets
        ensure_assets()
    except Exception as exc:
        print(f"Ошибка загрузки ассетов: {exc}", file=sys.stderr)
        raise SystemExit(1)

    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        print("Ошибка: ассеты после загрузки всё ещё отсутствуют.", file=sys.stderr)
        for path in missing_paths:
            print(f"  - {path}", file=sys.stderr)
        raise SystemExit(1)



# Цвета персонажей в истории
SPEAKER_NAME_COLORS = {
    "dreamgirl":   "rgb(192,192,192)",
    "sl":          "rgb(255,210,0)",
    "slp":         "rgb(255,210,0)",
    "slg":         "rgb(255,210,0)",
    "sa":          "rgb(255,210,0)",
    "un":          "rgb(185,86,255)",
    "unp":         "rgb(185,86,255)",
    "dv":          "rgb(255,170,0)",
    "dvp":         "rgb(255,170,0)",
    "dvg":         "rgb(255,170,0)",
    "el":          "rgb(255,255,0)",
    "elp":         "rgb(255,255,0)",
    "ro":          "rgb(255,255,0)",
    "us":          "rgb(255,50,0)",
    "usp":         "rgb(255,50,0)",
    "usg":         "rgb(255,50,0)",
    "mt":          "rgb(0,234,50)",
    "mtp":         "rgb(0,234,50)",
    "mt_voice":    "rgb(0,234,50)",
    "cs":          "rgb(165,165,255)",
    "csp":         "rgb(165,165,255)",
    "mz":          "rgb(114,160,255)",
    "mi":          "rgb(0,252,255)",
    "mip":         "rgb(0,252,255)",
    "ma":          "rgb(0,252,255)",
    "uv":          "rgb(78,255,0)",
    "uvp":         "rgb(78,255,0)",
    "sh":          "rgb(255,242,38)",
    "pi":          "rgb(230,0,0)",
    "me":          "rgb(225,221,125)",
    "FIXME_voice": "rgb(192,192,192)",
    "bush":        "rgb(192,192,192)",
    "message":     "rgb(192,192,192)",
    "odn":         "rgb(192,192,192)",
    "all":         "rgb(227,58,58)",
}

class AnsiView(Static):
    can_focus = False
    can_focus_children = False
    ALLOW_SELECT = False

    def on_mount(self) -> None:
        # ANSI-арт не интерактивен: отключаем лишнюю обработку мыши и ссылок
        self.auto_links = False
        self.disable_messages(events.MouseMove, events.Enter, events.Leave)


class ScriptStateHeader(Header):
    """Header, переносящий длинное состояние сценария на несколько строк."""

    DEFAULT_CSS = """
    ScriptStateHeader {
        height: auto;
        max-height: 8;
    }

    ScriptStateHeader HeaderTitle {
        height: auto;
        text-wrap: wrap;
        text-overflow: fold;
        padding: 0 1;
    }
    """

class PerformanceScreen(Screen):
    """Экран с облегчённой обработкой мыши для больших ANSI-артов."""

    MOUSE_STYLE_BYPASS_CLASS = "mouse-passive-art"

    def get_style_at(self, x: int, y: int) -> Style:
        try:
            widget, _ = self.get_widget_at(x, y)
        except errors.NoWidget:
            return Style.null()

        for node in widget.ancestors_with_self:
            if isinstance(node, Widget) and node.has_class(self.MOUSE_STYLE_BYPASS_CLASS):
                return Style.null()

        return super().get_style_at(x, y)


class MainMenu(Static):
    """Виджет главного меню"""
    BORDER_TITLE="Главное меню"
    def compose(self):
        yield MainMenuMiddleBtns()
        yield MainMenuBottomBtns()


class ScriptLoadingOverlay(Static):
    """Оверлей подготовки ресурсов сценария."""

    def compose(self):
        yield LoadingIndicator(id="script-loading-indicator")
        yield Label("Подготовка сценария…", id="script-loading-text")
    
class MainMenuMiddleBtns(HorizontalGroup):
    """Виджет-контейнер для центарльных кнопок"""
    BORDER_TITLE="Информация"
    def compose(self):
            yield MainMenuStartBtn(id="container-start-game")
            yield MainMenuLoadBtn(id="container-save-load")
            yield MainMenuGalleryBtn(id="container-gallery")

class MainMenuBottomBtns(HorizontalGroup):
    """Виджет-контейнер для нижних кнопок"""
    def compose(self):
        yield Button("Достижения (скоро) 🏅", id="btn-achievements", disabled=True)
        yield Button("Настройки 🪛", id="btn-settings-menu")
        yield Button("Выход 🚪", id="btn-exit-menu")

class MainMenuStartBtn(Vertical):
    """Виджет для кнопки "Начать игру" с описанием"""
    def compose(self):
        yield Button("Начать игру ▶", id="btn-start-game")
        yield Label('   Дорогой пионер!\n' \
        'Ты — на пороге удивительных открытий.\n' \
        '   Перед тобой распахнулись двери самого прекрасного места в мире — ' \
        'нашего любимого лагеря "Совёнок". Эта смена запомниться тебе на всю жизнь.\n' \
        'Добро пожаловать!')

class MainMenuLoadBtn(Vertical):
    """Виджет для кнопки "Соханение" с описанием"""
    def compose(self):
        yield Button("Сохранение 📒", id="btn-save-load")
        yield Label('   Бережно относись к истории своего лагеря. Тщательно записывай ' \
        'свои наблюдения и мысли о прошедших днях.\nПри помощи сохранений ты всегда ' \
        'сможешь вернутся назад к пройденному эпизоду и осмыслить его заново. ' \
        'Удачи тебе в твоих начинаниях!\n' \
        '   Если что-то пойдёт не так, ты знаешь, что делать')

class MainMenuGalleryBtn(Vertical):
    """Виджет для кнопки "Галерея" с описанием"""
    def compose(self):
        yield Button("Галерея 📷", id="btn-gallery")
        yield Label('   Здесь представлены работы участников нашего фотокружка. ' \
        'Твои товарищи всегда готовы запечатлеть важные моменты из жини лагеря, ' \
        'а на многих снимках ты сможешь встретить и себя. Будь опрятен и своим ' \
        'поведением подавай пример окружающим.')


class GalleryMenu(HorizontalGroup):
    """Виджет галереи"""
    BORDER_TITLE = "Галерея"
    def compose(self):
        yield GalleryMenuLeftBtns()
        yield GalleryMenuMidBtns()
        
class GalleryMenuLeftBtns(Vertical):
    """Виджет-контейнер для кнопок галереи сверху"""
    def compose(self):
        yield Button("Назад ↩", id="btn-close-gallery")
        with Static(id="container-left-btns"):
            yield Button("Музыка", variant="default", id="btn-gallery-music")
            yield Button("Иллюстрации", variant="primary", id="btn-gallery-cg")
            yield Button("Фоны", variant="default", id="btn-gallery-bg")

class GalleryMenuMidBtns(Vertical):
    """Виджет-контейнер для кнопок и арт-пространства галереи в центре"""
    BORDER_TITLE=""
    def compose(self):
        with HorizontalGroup():

            with ScrollableContainer(id="bg-cg-gallery", can_focus=False, can_focus_children=False):
                yield AnsiView("", id="ansi-content", classes="mouse-passive-art")
            
        yield GalleryMenuBottomBtns()
        
class GalleryMenuBottomBtns(HorizontalGroup):
    """Виджет-контейнер для кнопок качества"""
    def compose(self):
        yield Button("<-", id="btn-back-gallery")
        yield Button("маленький", variant="default", id="btn-small-gallery")
        yield Button("Средний", variant="warning", id="btn-medium-gallery")
        yield Button("ОГРОМНЫЙ", variant="default", id="btn-large-gallery")
        yield Button("->", id="btn-next-gallery")


class SaveMenuLeftBtns(Vertical):
    """Виджет-контейнер для кнопок сохранений слева (Назад + номера страниц)"""
    def compose(self):
        yield Button("Назад ↩", id="btn-close-save-menu")
        with Static(id="container-save-page-btns"):
            for i in range(1, 10):
                yield Button(str(i), id=f"btn-save-page-{i}", classes="save-page-btn")


class SaveMenuMidBtns(Vertical):
    """Виджет-контейнер для слотов и кнопок действий в центре"""
    BORDER_TITLE = "Сохранения"
    def compose(self):
        yield SaveMenuSlots(id="save-menu-slots")
        yield SaveMenuActionBtns(id="save-action-btns")


class SaveMenuSlots(Static):
    """Сетка из 12 слотов сохранения"""
    def compose(self):
        for row in range(3):
            with HorizontalGroup(id=f"save-row-{row}"):
                for col in range(4):
                    slot_index = row * 4 + col
                    yield Button(
                        f"Пусто\nСлот {slot_index + 1}",
                        id=f"save-slot-{slot_index}",
                        classes="save-slot save-slot-empty",
                    )


class SaveMenuActionBtns(HorizontalGroup):
    """Кнопки действий: Удалить, Загрузить, Сохранить"""
    def compose(self):
        yield Button("Удалить", id="btn-save-delete", classes="save-action-btn")
        yield Button("Загрузить", id="btn-save-load-game", classes="save-action-btn")
        yield Button("Сохранить", id="btn-save-save", classes="save-action-btn")


class SaveMenu(HorizontalGroup):
    """Меню сохранений с пагинацией и слотами"""
    BORDER_TITLE = "Сохранения"

    def __init__(self, *args, opened_from: str = "menu", **kwargs):
        super().__init__(*args, **kwargs)
        self.opened_from = opened_from  # "menu" или "pause"
        self.current_page = 0  # 0-8 (страницы 1-9)
        self.selected_slot: str | None = None  # id выбранного слота
        self.all_saves: dict[str, dict] = {}

    def compose(self):
        yield SaveMenuLeftBtns()
        yield SaveMenuMidBtns()


class PauseMenu(Static):
    """Виджет меню паузы"""
    def compose(self):
        yield PauseMenuContainer()

class PauseMenuContainer(VerticalScroll):
    """Доп контейнер для меню паузы(Для отображения title)"""
    BORDER_TITLE = "Пауза"
    def compose(self):
        yield Button("Продолжить", id="btn-continue")
        yield Button("Сохранения", id="btn-save")
        yield Button("Настройки", id="btn-settings-pause")
        yield Button("В главное меню", id="btn-menu")
        yield Button("Выход", id="btn-exit-pause")


class SettingsMenu(VerticalScroll):
    """Виджет меню настроек"""
    BORDER_TITLE = "Настройки"

    def compose(self):
        yield SettingHeader()
        yield SettingQuality()
        yield SettingASCIIorANSI()
        yield SettingTextSpeed()
        yield Button("Назад ↩", id="btn-close-settings")

class SettingHeader(Widget):
    """Виджет с настройкой Header"""
    BORDER_TITLE = "Верхняя панель(Header)"
    def compose(self):
        with Vertical(id="header-controls"):
            with HorizontalGroup(classes="header-setting-row"):
                yield Button("Включить", variant="default", id="btn-header-on")
                yield Button("Выключить", variant="error", id="btn-header-off")
            yield Label("Показывать в Header:", id="header-content-label")
            with HorizontalGroup(classes="header-setting-row"):
                yield Button("LP-поинты", id="btn-header-lp-points")
                yield Button("Флаги", id="btn-header-flags")
        yield DescriptionSettingHeader()

class DescriptionSettingHeader(Widget):
    """Описание настройки 'Верхняя панель(Header)'"""
    def render(self):
        return """Верхняя панель будет отображать:
название программы, выбранные группы переменных и системное время.\n
LP-поинты и флаги можно включать независимо.
(может слегка уменьшить обзор)"""

class SettingQuality(Widget):
    """Виджет с настройкой размера ASCII-артов"""
    BORDER_TITLE = "Размер ANSI/ASCII артов"
    def compose(self):
        with Vertical():
            yield Button("маленький\n(50)", variant="default", id="btn-small")
            yield Button("Средний\n(150)", variant="default", id="btn-medium")
            yield Button("ОГРОМНЫЙ\n(200)", variant="default", id="btn-large")
            yield DescriptionSettingQuality()

class DescriptionSettingQuality(Widget):
    """Описание настройки 'Размер ANSI/ASCII артов'"""
    def render(self):
        return """Размер артов лучше подбирать по размеру окна консоли,
с сильно большим размером изображение может не поместиться.\n 
Можно так же попробовать уменьшить размер шрифта самой консоли 
(Обычно это Ctrl+"+" и Ctrl+"-")"""

class SettingASCIIorANSI(Widget):
    """Виджет с настройкой стиля артов"""
    BORDER_TITLE = "Стиль артов"
    def compose(self):
        with HorizontalGroup():
            yield Button("ANSI", variant="default", id="btn-ANSI")
            yield Button("ASCII", variant="default", id="btn-ASCII")
            yield DescriptionSettingASCIIorANSI()

class DescriptionSettingASCIIorANSI(Widget):
    """Описание настройки 'Стиль артов'"""
    def render(self):
        return """ANSI  - изображение будет цветным
ASCII - изображение будет состоять из символов .,:+*? и других"""

class SettingTextSpeed(Widget):
    """Виджет с настройкой скорости текста"""
    BORDER_TITLE = "Скорость текста"
    def compose(self):
        with Vertical():
            yield Button("Медленно", variant="default", id="btn-speed-slow")
            yield Button("Средне", variant="default", id="btn-speed-medium")
            yield Button("Быстро", variant="default", id="btn-speed-fast")
            yield Button("Моментально", variant="default", id="btn-speed-instantly")
            yield DescriptionSettingTextSpeed()

class DescriptionSettingTextSpeed(Widget):
    """Описание настройки 'Скорость текста'"""
    def render(self):
        return """Скорость появления текста в текстовом окне.\n
Медленно    - 0.04
Средние     - 0.025
Быстро      - 0.01
Моментально - 0"""


class NovelMenu(Static):
    """Виджет-контейнер для текст бара и кнопок"""
    def compose(self):
        with Vertical(id="novel-log-control", classes="novel-control"):
            yield Button("История", id="btn-log")
        yield TextBar(id="text-bar")
        with Vertical(id="novel-next-control", classes="novel-control"):
            yield Button("Продолжить", id="btn-next")

class TextBar(Widget):
    """Виджет текст бара"""
    BORDER_TITLE = ""   # Имя персонажа
    
    def __init__(self, id=None):
        super().__init__(id=id)
        self.text = ""  # Текущий текст

    def render(self):
        return Text.from_markup(self.text)  # Отображаем содержимое текста

    async def animate_text(self, new_text, speed=None, append=False):
        """Анимация текста, символ за символом

        Если append=True  - добавляет текст к текущему,\n
        Если append=False - начинает с нуля"""

        speed = float(self.app.text_speed)
        
        if not append:
            self.text = ""
            self.refresh()

        for char in new_text:
            await self.app.wait_until_game_resumed()
            self.text += char
            self.refresh()
            await asyncio.sleep(speed)

        self.refresh()
        self.scroll_end(animate=False)


class NovelWindow(Widget):
    """Окно новеллы(bg-cg + ChoiceBar)"""
    def compose(self):
        yield ChoiceBar(id="choice-bar", classes="hidden")
        yield AnsiView("", id="bg-cg", classes="mouse-passive-art")
        
class ChoiceBar(Widget):
    """Окно выбора"""
    def compose(self):
        yield ListView()


class LogMenu(Log):
    """Виджет окна истории"""
    # BORDER_TITLE = "История"
    auto_scroll = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._speaker_line_styles: dict[int, Style] = {}

    def add_dialogue_entry(
        self,
        text: str,
        speaker: str = "",
        speaker_id: str | None = None,
    ) -> None:
        if speaker:
            self.write_line(speaker)
            line_index = self.line_count - 1
            color = SPEAKER_NAME_COLORS.get(speaker_id or "")
            if color:
                self._speaker_line_styles[line_index] = Style.parse(color)

        self.write_line(f" {text}")

    def clear(self):
        self._speaker_line_styles.clear()
        return super().clear()

    def _render_line(self, y: int, scroll_x: int, width: int):
        strip = super()._render_line(y, scroll_x, width)
        style = self._speaker_line_styles.get(y)
        if style is not None:
            return strip.__class__(
                Segment.apply_style(strip._segments, post_style=style),
                strip.cell_length,
            )
        return strip



class TerminalSummer(App):
    """Основное приложение новеллы"""
    CSS_PATH = str(CSS_PATH)
    TITLE = f"Terminal Summer {APP_VERSION}"
    SUB_TITLE = format_script_state()

    CONFIG_FILE = SETTINGS_PATH
    PERSISTENT_FILE = PERSISTENT_PATH

    DEFAULT_SETTINGS = {
        "header": False,
        "header_lp_points": True,
        "header_flags": True,
        "quality": "150",
        "style": "ANSI",
        "text_speed": "0.025",
    }

    def __init__(self):
        super().__init__()
        self.settings = self.DEFAULT_SETTINGS.copy()

        self.ts_path = get_ts_path()

        self._sprite_resources = None
        self._sprite_resources_loaded = False
        self._sprite_assets_root = self.ts_path / "game"
        self._sprite_runtime_dir = self.ts_path / "game/sprites/generated_runtime"
        self._active_sprites = {}
        self._sprite_order_seq = 0
        self.current_time = "day"
        self.current_text_mode = "adv"
        self._interface_hidden = False
        #self.audio_player = AudioPlayer()
        self._next_scene_in_progress = False
        self._text_animating = False
        self._text_animating_since = None
        self._text_animating_until = 0.0
        self._input_blocked = False
        self._input_blocked_since = None
        self._input_blocked_until = 0.0
        self._space_last_event_at = 0.0
        self._space_idle_gap = 0.12
        self._space_require_idle = False
        self._script_advance_task: asyncio.Task | None = None
        self._script_delay_event: asyncio.Event | None = None
        self._script_delay_kind: str | None = None
        self._script_delay_skippable = False
        self._script_delay_generation = 0
        self._game_paused = False
        self._game_pause_changed_event = asyncio.Event()
        self.scene_dirty = False
        self._scene_generation = 0
        self._cache_epoch = 0
        self._cache_lock = threading.RLock()
        self._scene_render_cache: OrderedDict[tuple, Text] = OrderedDict()
        self._sprite_build_cache: OrderedDict[str, str] = OrderedDict()
        self._decoded_image_cache: OrderedDict[str, tuple[Image.Image, int]] = OrderedDict()
        self._decoded_image_cache_bytes = 0
        self._decoded_image_cache_limit = 128 * 1024 * 1024
        self._render_tasks: dict[tuple, asyncio.Task] = {}
        self._prefetch_tasks: set[asyncio.Task] = set()
        self._render_semaphore = asyncio.Semaphore(2)
        self._script_preload_task = None
        self._preload_generation = 0
        self._preload_filename = None
        self._loading_restore_novel = False
        self._preload_after_settings = False
        self._render_cache_limit = 96
        self._sprite_cache_limit = 256

    text_speed = "0.025" # Скорость текста 0.04 | 0.025 | 0.01 | 0

    gallery_mode = "cg"
    gallery_size = "150" # small - 50 | medium - 150 | large - 200
    gallery_index = 0
    gallery_images = []

    BINDINGS = [
        Binding("escape", "pause_game", "Пауза",   show=True, id="bind-pause"),
        Binding("space",  "",           "Далее",   show=True, id="bind-next"),
        Binding("h",      "log",        "История", show=True, id="bind-log"),
        Binding("f",      "toggle_interface", "Скрыть интерфейс", show=True, id="bind-toggle-interface"),
    ]

    TEXT_MODES = {"adv", "nvl"}

    def get_default_screen(self) -> Screen:
        return PerformanceScreen(id="_default")

    def compose(self) -> ComposeResult:
        yield ScriptStateHeader(show_clock=True, classes="hidden")
        yield Footer(classes="hidden")

        yield MainMenu(    id="main-menu")
        yield NovelWindow( id="novel-window",  classes="hidden")
        yield NovelMenu(   id="novel-menu",    classes="hidden")
        yield LogMenu(     id="log-menu",      classes="hidden")
        yield PauseMenu(   id="pause-menu",    classes="hidden")
        yield SettingsMenu(id="settings-menu", classes="hidden")
        yield GalleryMenu( id="gallery-menu",  classes="hidden")
        yield SaveMenu(    id="save-menu",     classes="hidden")
        yield ScriptLoadingOverlay(id="script-loading", classes="hidden")

    def set_text_mode(self, mode: str) -> None:
        """Сохраняет режим текста и обновляет его отображение."""
        normalized_mode = mode.lower().strip()
        self.current_text_mode = (
            normalized_mode if normalized_mode in self.TEXT_MODES else "adv"
        )
        self.sync_text_mode_display()

    def sync_text_mode_display(self) -> None:
        """Синхронизирует оформление NVL и видимость сцены с состоянием UI."""
        novel_menu = self.query_one("#novel-menu", Widget)
        novel_window = self.query_one("#novel-window", Widget)
        bg_cg = self.query_one("#bg-cg", Widget)
        choice_bar = self.query_one("#choice-bar", Widget)
        is_nvl = self.current_text_mode == "nvl"

        novel_menu.set_class(is_nvl, "nvl-mode")
        novel_window.set_class(
            is_nvl
            and not self._interface_hidden
            and choice_bar.has_class("hidden"),
            "hidden",
        )
        bg_cg.set_class(
            is_nvl or self._interface_hidden or not choice_bar.has_class("hidden"),
            "hidden",
        )



    # ============ Функции - on_ ============
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обработка событий при нажатии кнопок"""
        button_id = event.button.id

        # Кнопки в NovelMenu:
        if   button_id == "btn-next":             # Кнопка "Продолжить"
            await self._advance_from_button()
        # TODO: Добавить закрытие через escape
        elif button_id == "btn-log":              # Кнопка "История"
            self.action_log()

        # Кнопки в PauseMenu:
        elif button_id == "btn-continue":         # Кнопка "Продолжить"
            self.action_pause_game()
        elif button_id == "btn-save":             # Кнопка "Сохранения"
            self.open_save_menu("pause")
        elif button_id == "btn-settings-pause":   # Кнопка "Настройки"
            self.query_one("#settings-menu").add_class("open-from-pause") # Класс-флаг что настройки открыты из PauseMenu
            self.action_open_settings()
        elif button_id == "btn-menu":             # Кнопка "В главное меню"
            # Полный сброс игрового интерфейса
            self.reset_game_view()

            # Переход в главное меню
            self.action_open_menu()
        elif button_id == "btn-exit-pause":       # Кнопка "Выход"
            self.app.exit()

        # Кнопки в SettingsMenu:
        # Header
        elif button_id == "btn-header-on":        # Кнопка "Включить"
            # Включаем заголовок
            self.query_one("Header").remove_class("hidden")

            # Меняем стили кнопок
            self.query_one("#btn-header-on", Button).variant = "success"
            self.query_one("#btn-header-off", Button).variant = "default"

            # Сохранение в файл настроек
            self.settings["header"] = True
            self.save_settings()
        elif button_id == "btn-header-off":       # Кнопка "Выключить"
            # Включаем заголовок
            self.query_one("Header").add_class("hidden")

            # Меняем стили кнопок
            self.query_one("#btn-header-on", Button).variant = "default"
            self.query_one("#btn-header-off", Button).variant = "error"

            # Сохранение в файл настроек
            self.settings["header"] = False
            self.save_settings()

        elif button_id == "btn-header-lp-points":
            self.settings["header_lp_points"] = not self.settings.get(
                "header_lp_points", True
            )
            self.sync_header_filter_buttons()
            self.update_script_header()
            self.save_settings()
        elif button_id == "btn-header-flags":
            self.settings["header_flags"] = not self.settings.get(
                "header_flags", True
            )
            self.sync_header_filter_buttons()
            self.update_script_header()
            self.save_settings()

        # Quality
        elif button_id == "btn-small":            # Кнопка "маленький"
            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "error"
            self.query_one("#btn-medium", Button).variant = "default"
            self.query_one("#btn-large", Button).variant = "default"

            # Сохранение в файл настроек и обновление
            self.settings["quality"] = "50"
            self.save_settings()
            await self.update_current_scene_art()
        elif button_id == "btn-medium":           # Кнопка "Средний"
            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "default"
            self.query_one("#btn-medium", Button).variant = "warning"
            self.query_one("#btn-large", Button).variant = "default"

            # Сохранение в файл настроек и обновление
            self.settings["quality"] = "150"
            self.save_settings()
            await self.update_current_scene_art()
        elif button_id == "btn-large":            # Кнопка "ОГРОМНЫЙ"
            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "default"
            self.query_one("#btn-medium", Button).variant = "default"
            self.query_one("#btn-large", Button).variant = "success"

            # Сохранение в файл настроек и обновление
            self.settings["quality"] = "200"
            self.save_settings()
            await self.update_current_scene_art()

        # ASCIIorANSI
        elif button_id == "btn-ANSI":             # Кнопка "ANSI"
            # Меняем стили кнопок
            self.query_one("#btn-ANSI", Button).variant = "primary"
            self.query_one("#btn-ASCII", Button).variant = "default"

            # Сохранение в файл настроек и обновляем текущую сцену
            self.settings["style"] = "ANSI"
            self.save_settings()
            await self.update_current_scene_art()
        elif button_id == "btn-ASCII":            # Кнопка "ASCII"
            # Меняем стили кнопок
            self.query_one("#btn-ANSI", Button).variant = "default"
            self.query_one("#btn-ASCII", Button).variant = "primary"

            # Сохранение в файл настроек и обновляем текущую сцену
            self.settings["style"] = "ASCII"
            self.save_settings()
            await self.update_current_scene_art()

        # TextSpeed
        elif button_id == "btn-speed-slow":       # Кнопка "Медленно"
             # Меняем стили кнопок
            self.query_one("#btn-speed-slow", Button).variant = "error"
            self.query_one("#btn-speed-medium", Button).variant = "default"
            self.query_one("#btn-speed-fast", Button).variant = "default"
            self.query_one("#btn-speed-instantly", Button).variant = "default"

            # Сохранение в файл настроек и применение
            self.settings["text_speed"] = "0.04"
            self.save_settings()
            self.apply_settings()
        elif button_id == "btn-speed-medium":     # Кнопка "Средне"
            # Меняем стили кнопок
            self.query_one("#btn-speed-slow", Button).variant = "default"
            self.query_one("#btn-speed-medium", Button).variant = "warning"
            self.query_one("#btn-speed-fast", Button).variant = "default"
            self.query_one("#btn-speed-instantly", Button).variant = "default"

            # Сохранение в файл настроек и применение
            self.settings["text_speed"] = "0.025"
            self.save_settings()
            self.apply_settings()
        elif button_id == "btn-speed-fast":       # Кнопка "Быстро"
            # Меняем стили кнопок
            self.query_one("#btn-speed-slow", Button).variant = "default"
            self.query_one("#btn-speed-medium", Button).variant = "default"
            self.query_one("#btn-speed-fast", Button).variant = "success"
            self.query_one("#btn-speed-instantly", Button).variant = "default"

            # Сохранение в файл настроек и применение
            self.settings["text_speed"] = "0.01"
            self.save_settings()
            self.apply_settings()
        elif button_id == "btn-speed-instantly":  # Кнопка "Моментально"
            # Меняем стили кнопок
            self.query_one("#btn-speed-slow", Button).variant = "default"
            self.query_one("#btn-speed-medium", Button).variant = "default"
            self.query_one("#btn-speed-fast", Button).variant = "default"
            self.query_one("#btn-speed-instantly", Button).variant = "primary"

            # Сохранение в файл настроек и применение
            self.settings["text_speed"] = "0"
            self.save_settings()
            self.apply_settings()

        elif button_id == "btn-close-settings":   # Кнопка "Назад"
            # Если открыто из меню паузы
            if self.query_one("#settings-menu").has_class("open-from-pause"):
                self.action_open_settings()
                #self.query_one("#settings-menu").remove_class("open-from-pause")
            # Если открыто из главного меню
            elif self.query_one("#settings-menu").has_class("open-from-menu"):
                self.action_open_menu()
                self.query_one("#settings-menu").remove_class("open-from-menu")

        # Кнопки в MainMenu:
        elif button_id == "btn-start-game":       # Кнопка "Начать игру"
            self.cancel_script_advance()

            # Скрытие главного меню
            self.action_open_menu()
            self.clear_log()
            self._interface_hidden = False
            self.set_text_mode("adv")

            # Сброс всех глобальных переменных
            from script_parser import reset_globals
            reset_globals()
            self.update_script_header()

            # Запуск новой игры (всегда пролог)
            prologue_path = self.ts_path / "text" / "prologue.txt"
            self.script = ScriptParser(prologue_path, self)

            # Отображение NovelMenu
            self.query_one("#novel-menu").remove_class("hidden")
            self.query_one("#novel-window").remove_class("hidden")
            self.start_script_preload(self.script)

            # Фокус на кнопке "Вперёд" в игровом меню
            self.query_one("#btn-next", Button).focus()
        elif button_id == "btn-save-load":        # Кнопка "Сохранение"
            self.open_save_menu("menu")
        elif button_id == "btn-gallery":          # Кнопка "Галерея"
            self.action_open_gallery()
        elif button_id == "btn-settings-menu":    # Кнопка "Настройки"
            self.query_one("#settings-menu").add_class("open-from-menu") # Класс-флаг что настройки открыты из MainMenu
            self.action_open_settings()
        elif button_id == "btn-exit-menu":        # Кнопка "Выход"
            self.app.exit()

        # Кнопки в GalleryMenu:
        # LeftBtns
        elif button_id == "btn-gallery-music":    # Кнопка "Музыка"
            # Меняем стили кнопок
            self.query_one("#btn-gallery-music", Button).variant = "primary"
            self.query_one("#btn-gallery-cg", Button).variant = "default"
            self.query_one("#btn-gallery-bg", Button).variant = "default"
        elif button_id == "btn-gallery-cg":       # Кнопка "Иллюстрации"
            # Меняем стили кнопок
            self.query_one("#btn-gallery-music", Button).variant = "default"
            self.query_one("#btn-gallery-cg", Button).variant = "primary"
            self.query_one("#btn-gallery-bg", Button).variant = "default"

            self.gallery_mode = "cg"
            self.load_gallery_images()
            self.update_gallery_display()
        elif button_id == "btn-gallery-bg":       # Кнопка "Фоны"
            # Меняем стили кнопок
            self.query_one("#btn-gallery-music", Button).variant = "default"
            self.query_one("#btn-gallery-cg", Button).variant = "default"
            self.query_one("#btn-gallery-bg", Button).variant = "primary"

            self.gallery_mode = "bg"
            self.load_gallery_images()
            self.update_gallery_display()

        # Перелистывание bg и cg
        elif button_id == "btn-back-gallery":     # Кнопка "<<<"
            if self.gallery_index > 0:
                self.gallery_index -= 1
                self.update_gallery_display()
        elif button_id == "btn-next-gallery":     # Кнопка ">>>"
            if self.gallery_index < len(self.gallery_images) - 1:
                self.gallery_index += 1
                self.update_gallery_display()

        # Quality
        elif button_id == "btn-small-gallery":    # Кнопка "маленький"
            # Меняем стили кнопок
            self.query_one("#btn-small-gallery", Button).variant = "error"
            self.query_one("#btn-medium-gallery", Button).variant = "default"
            self.query_one("#btn-large-gallery", Button).variant = "default"

            self.gallery_size = "50"
            self.load_gallery_images()
            self.update_gallery_display()
        elif button_id == "btn-medium-gallery":   # Кнопка "Средний"
            # Меняем стили кнопок
            self.query_one("#btn-small-gallery", Button).variant = "default"
            self.query_one("#btn-medium-gallery", Button).variant = "warning"
            self.query_one("#btn-large-gallery", Button).variant = "default"
        
            self.gallery_size = "150"
            self.load_gallery_images()
            self.update_gallery_display()
        elif button_id == "btn-large-gallery":    # Кнопка "ОГРОМНЫЙ"
            # Меняем стили кнопок
            self.query_one("#btn-small-gallery", Button).variant = "default"
            self.query_one("#btn-medium-gallery", Button).variant = "default"
            self.query_one("#btn-large-gallery", Button).variant = "success"

            self.gallery_size = "200"
            self.load_gallery_images()
            self.update_gallery_display()

        elif button_id == "btn-close-gallery":    # Кнопка "Назад"
            self.action_open_gallery()

        # Кнопки в SaveMenu:
        # Кнопка "Назад"
        elif button_id == "btn-close-save-menu":
            self.close_save_menu()
        # Page buttons (1-9)
        elif button_id.startswith("btn-save-page-"):
            page_num = int(button_id.split("-")[-1]) - 1
            self.switch_save_page(page_num)
        # Slot buttons (save-slot-0 through save-slot-11)
        elif button_id.startswith("save-slot-"):
            self.select_save_slot(button_id)
        # Action buttons
        elif button_id == "btn-save-delete":
            self.delete_selected_save()
        elif button_id == "btn-save-load-game":
            self.load_selected_save()
        elif button_id == "btn-save-save":
            self.save_to_selected_slot()

    def on_mount(self) -> None:
        """Загрузка настроек при запуске"""
        self.load_persistent_state()
        self.load_settings()
        self.apply_settings()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Обработка выбора из меню"""
        choice_bar = self.query_one("#choice-bar")
        pending_choices = getattr(self, "pending_choices", None)
        if choice_bar.has_class("hidden") or not pending_choices:
            return

        choice_label = event.item.query_one(Label)
        choice_text = str(choice_label.content).strip()
        choice = pending_choices.get(choice_text)
        if choice is None:
            return

        self.script.select_choice(choice)

        # Очищаем pending_choices до продолжения сценария.
        self.pending_choices = None

        # Скрываем меню выбора и возвращаем видимость, подходящую текущему режиму.
        choice_bar.add_class("hidden")
        self.query_one("#novel-menu").remove_class("hidden")
        self.sync_text_mode_display()

        # Продолжаем сценарий с выбранного неизменяемого диапазона. Само
        # выполнение уходит в отдельную задачу, чтобы не задерживать очередь UI.
        await self._advance_script_line()


    # ============ Функции - action_ ============
    async def action_next_scene(self) -> None:
        """Переключение по bind(space)."""
        await self._advance_script_line()

    def action_log(self) -> None:
        """Открытие меню истории"""
        log_menu = self.query_one("#log-menu")
        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")

        # Открываем историю только из novel_menu, закрытие доступно всегда
        if log_menu.has_class("hidden"):
            if novel_menu.has_class("hidden"):
                return

            # Скрыть bc, cg, text и кнопки
            novel_menu.add_class("hidden")
            novel_window.add_class("hidden")

            # Показ меню истории
            log_menu.remove_class("hidden")
        else:
            # Cкрытие меню истории
            log_menu.add_class("hidden")

            # Показ bc, cg, text и кнопок
            novel_menu.remove_class("hidden")
            novel_window.remove_class("hidden")
            self.sync_text_mode_display()

    def action_toggle_interface(self) -> None:
        """Показывает или скрывает интерфейс новеллы, оставляя сцену видимой."""
        if not hasattr(self, "script"):
            return

        main_menu = self.query_one("#main-menu")
        choice_bar = self.query_one("#choice-bar")
        blocked_menus = (
            self.query_one("#log-menu"),
            self.query_one("#pause-menu"),
            self.query_one("#settings-menu"),
            self.query_one("#save-menu"),
            self.query_one("#gallery-menu"),
        )
        if (
            not main_menu.has_class("hidden")
            or not choice_bar.has_class("hidden")
            or any(not menu.has_class("hidden") for menu in blocked_menus)
        ):
            return

        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")
        if self._interface_hidden:
            self._interface_hidden = False
            novel_menu.remove_class("hidden")
            self.sync_text_mode_display()
            return

        if novel_menu.has_class("hidden"):
            return

        self._interface_hidden = True
        novel_menu.add_class("hidden")
        novel_window.remove_class("hidden")
        self.query_one("#bg-cg").remove_class("hidden")

    def action_pause_game(self) -> None:
        """Открытие меню паузы"""
        # Preload временно скрывает игровой интерфейс и затем самостоятельно
        # восстанавливает его. Не позволяем Escape открыть PauseMenu под
        # полноэкранным оверлеем и получить два конкурирующих состояния UI.
        if not self.query_one("#script-loading", Widget).has_class("hidden"):
            return

        pause_menu = self.query_one("#pause-menu")
        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")
        settings_menu = self.query_one("#settings-menu")
        main_menu = self.query_one("#main-menu")
        gallery_menu = self.query_one("#gallery-menu")
        save_menu = self.query_one("#save-menu")
        choice_bar = self.query_one("#choice-bar")
        log_menu = self.query_one("#log-menu")

        # Escape закрывает сохранения и возвращает пользователя туда, откуда
        # меню было открыто: в главное меню или в окно новеллы.
        if not save_menu.has_class("hidden"):
            self.close_save_menu()
            return

        # Галерея всегда открывается из главного меню.
        if not gallery_menu.has_class("hidden"):
            self.action_open_gallery()
            return
        

        if main_menu.has_class("hidden") and gallery_menu.has_class("hidden") and save_menu.has_class("hidden"): # Если НЕ открыто главное меню
            # Если открыто из главного меню ИЛИ НЕ скрыто окно выбора И окно истории
            if settings_menu.has_class("open-from-menu") or not (choice_bar.has_class("hidden") and log_menu.has_class("hidden")):
                pass # Пропуск

            elif settings_menu.has_class("hidden"): # Если НЕ открыто меню настроек
                # Переключение видимости элементов
                if pause_menu.has_class("hidden"):
                    self.set_game_paused(True)
                    # Cкрытие диологового окна, кнопок перемотки и задника
                    novel_menu.add_class("hidden")
                    novel_window.add_class("hidden")

                    # Показ меню паузы
                    pause_menu.remove_class("hidden")

                    # Фокус на первую кнопку в меню паузы
                    self.query_one("#btn-continue", Button).focus()
                else:
                    self.set_game_paused(False)
                    # Выключаем паузу: скрытие меню паузы
                    pause_menu.add_class("hidden")

                    # Показ диологового окна, кнопок перемотки и задника
                    novel_menu.remove_class("hidden")
                    novel_window.remove_class("hidden")
                    self.sync_text_mode_display()

                    # Возвращаем фокус на кнопку "Вперёд" в игровом меню 
                    self.query_one("#btn-next", Button).focus()
            else:
                self.set_game_paused(False)
                # Скрытие меню настроек
                settings_menu.add_class("hidden")

                # Показ диологового окна, кнопок перемотки и задника
                novel_menu.remove_class("hidden")
                novel_window.remove_class("hidden")
                self.sync_text_mode_display()

                if self._preload_after_settings and hasattr(self, "script"):
                    self._preload_after_settings = False
                    self.start_script_preload(self.script)

                # Возвращаем фокус на кнопку "Вперёд" в игровом меню 
                self.query_one("#btn-next", Button).focus()
        else: pass # Не открывать в главном меню

    def action_open_menu(self) -> None:
        """Открытие главного меню"""
        pause_menu = self.query_one("#pause-menu")
        settings_menu = self.query_one("#settings-menu")
        main_menu = self.query_one("#main-menu")

        if main_menu.has_class("hidden"):
            # Скрытие предыдущего меню:
            if not pause_menu.has_class("hidden"):      # Из паузы
                pause_menu.add_class("hidden")
            elif not settings_menu.has_class("hidden"): # Из настроек
                settings_menu.add_class("hidden")

            # Скрытие footer
            self.query_one(Footer).add_class("hidden")

            # Показ главного меню
            main_menu.remove_class("hidden")

            # Фокус на кнопке "Начать игру"
            self.query_one("#btn-start-game", Button).focus()
        else:
            # Скрытие главного меню
            main_menu.add_class("hidden")
            self.query_one(Footer).remove_class("hidden")

    def action_open_settings(self) -> None:
        """Открытие меню настроек"""
        settings_menu = self.query_one("#settings-menu")
        pause_menu = self.query_one("#pause-menu")
        main_menu = self.query_one("#main-menu")
        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")

        # Переключение видимости элементов
        if settings_menu.has_class("hidden"):
            if settings_menu.has_class("open-from-pause"): # Если открыто из паузы
                # Скрытие меню паузы
                pause_menu.add_class("hidden")
            elif settings_menu.has_class("open-from-menu"): # Если открыто из меню
                # Скрытие главного меню
                main_menu.add_class("hidden")

            # Показ меню настроек
            settings_menu.remove_class("hidden")

            # Устанавливаем фокус на первую кнопку в меню настроек
            self.query_one("#btn-header-on", Button).focus()
        else:
            # Cкрытие меню настроек
            settings_menu.add_class("hidden")

            if settings_menu.has_class("open-from-pause"): # Если открыто из паузы
                self.set_game_paused(False)
                # Удаление класса-флага
                settings_menu.remove_class("open-from-pause")

                # Показ диологового окна, кнопок перемотки и задника
                novel_menu.remove_class("hidden")
                novel_window.remove_class("hidden")
                self.sync_text_mode_display()

                if self._preload_after_settings and hasattr(self, "script"):
                    self._preload_after_settings = False
                    self.start_script_preload(self.script)

                # Возвращаем фокус на кнопку "Вперёд" в игровом меню 
                self.query_one("#btn-next", Button).focus()
            elif settings_menu.has_class("open-from-menu"): # Если открыто из меню
                # Удаление класса-флага
                settings_menu.remove_class("open-from-menu")

                # Показ главного меню
                main_menu.remove_class("hidden")

                # Возвращаем фокус на кнопку "Начать игру" в главном меню 
                self.query_one("#btn-start-game", Button).focus()

    def action_open_gallery(self) -> None:
        """Открытие меню галереи"""
        main_menu = self.query_one("#main-menu")
        gallery_menu = self.query_one("#gallery-menu")

        if gallery_menu.has_class("hidden"):
            # Скрываем главное меню
            self.action_open_menu()
            #main_menu.add_class("hidden")

            # Показываем меню галереи
            gallery_menu.remove_class("hidden")

            # Устанавливаем фокус на первую кнопку в меню галереи
            self.query_one("#btn-close-gallery", Button).focus()

            # Загружаем иллюстрации
            self.gallery_mode = "cg"
            self.gallery_size = "150"
            self.gallery_index = 0
            self.load_gallery_images()
            self.update_gallery_display()

            # Стильи кнопок при открытии 
            self.query_one("#btn-small-gallery", Button).variant = "default"
            self.query_one("#btn-medium-gallery", Button).variant = "warning"
            self.query_one("#btn-large-gallery", Button).variant = "default"
        else:
            # Скрываем меню галереи
            gallery_menu.add_class("hidden")

            # Показываем главное меню
            self.action_open_menu()
            #main_menu.remove_class("hidden")


    # ============ Сохранения ============
    def is_savable_game_state(self) -> bool:
        """Проверка: можно ли сохраняться в текущем состоянии.

        Запрещает сохранение во время анимации текста, блокировки ввода,
        показа меню выбора или отсутствия запущенного сценария.
        """
        if self._text_animating:
            return False
        if self._input_blocked:
            return False
        if self._script_delay_event is not None:
            return False
        if self._next_scene_in_progress:
            return False
        if not hasattr(self, "script") or not self.script:
            return False
        if not self.query_one("#choice-bar").has_class("hidden"):
            return False
        return True

    def open_save_menu(self, opened_from: str) -> None:
        """Открытие меню сохранений"""
        save_menu = self.query_one("#save-menu")
        pause_menu = self.query_one("#pause-menu")
        main_menu = self.query_one("#main-menu")
        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")

        save_menu.opened_from = opened_from
        save_menu.current_page = 0
        save_menu.selected_slot = None
        save_menu.all_saves = get_all_saves()

        # Скрытие предыдущего меню
        if opened_from == "pause":
            pause_menu.add_class("hidden")
        elif opened_from == "menu":
            main_menu.add_class("hidden")
            self.query_one(Footer).remove_class("hidden")

        # Скрытие игровых элементов
        novel_menu.add_class("hidden")
        novel_window.add_class("hidden")

        # Показ меню сохранений
        save_menu.remove_class("hidden")

        # Настройка видимости кнопки "Сохранить"
        save_btn = self.query_one("#btn-save-save", Button)
        if opened_from == "pause":
            save_btn.disabled = False
        else:
            save_btn.disabled = True

        # Обновление отображения
        self.update_save_menu_display()

        # Подсветка первой страницы как активной
        self.query_one("#btn-save-page-1", Button).variant = "primary"
        for i in range(2, 10):
            self.query_one(f"#btn-save-page-{i}", Button).variant = "default"

        # Фокус на кнопку "Назад"
        self.query_one("#btn-close-save-menu", Button).focus()

    def close_save_menu(self) -> None:
        """Закрытие меню сохранений"""
        save_menu = self.query_one("#save-menu")
        save_menu.add_class("hidden")

        opened_from = save_menu.opened_from

        if opened_from == "pause":
            self.set_game_paused(False)
            self.query_one("#novel-menu").remove_class("hidden")
            self.query_one("#novel-window").remove_class("hidden")
            self.sync_text_mode_display()
            self.query_one("#btn-next", Button).focus()
        elif opened_from == "menu":
            self.query_one("#main-menu").remove_class("hidden")
            self.query_one(Footer).add_class("hidden")
            self.query_one("#btn-start-game", Button).focus()

    def update_save_menu_display(self) -> None:
        """Обновление отображения слотов на текущей странице"""
        save_menu = self.query_one("#save-menu")
        page = save_menu.current_page
        all_saves = save_menu.all_saves

        for slot_index in range(12):
            save_id = f"{page}/{slot_index}"
            btn_id = f"save-slot-{slot_index}"

            try:
                btn = self.query_one(f"#{btn_id}", Button)
            except Exception:
                continue

            save_data = all_saves.get(save_id)
            if save_data:
                game_state = save_data.get("game_state", {})
                dialogue = game_state.get("dialogue", {})
                speaker = dialogue.get("speaker", "")
                text = dialogue.get("text", "")
                timestamp = save_data.get("timestamp", "")

                # Обрезаем текст до 5 слов
                words = text.split()
                if len(words) > 6:
                    short_text = " ".join(words[:6]) + "..."
                else:
                    short_text = text

                # Формируем метку слота
                if speaker and short_text:
                    label = f"{speaker}: {short_text}"
                elif short_text:
                    label = short_text
                else:
                    label = "Пусто"

                btn.label = f"{label}\n{timestamp}"
                btn.remove_class("save-slot-empty")
                btn.add_class("save-slot-filled")
            else:
                btn.label = f"Пусто\nСлот {slot_index + 1}"
                btn.remove_class("save-slot-filled")
                btn.add_class("save-slot-empty")

            # Сброс выделения
            btn.remove_class("save-slot-selected")

        # Выделение выбранного слота
        if save_menu.selected_slot:
            try:
                selected_btn = self.query_one(f"#{save_menu.selected_slot}", Button)
                selected_btn.add_class("save-slot-selected")
            except Exception:
                pass

    def switch_save_page(self, page: int) -> None:
        """Переключение страницы сохранений"""
        save_menu = self.query_one("#save-menu")
        save_menu.current_page = page
        save_menu.selected_slot = None
        self.update_save_menu_display()

        # Обновление стиля активной кнопки страницы
        for i in range(1, 10):
            try:
                page_btn = self.query_one(f"#btn-save-page-{i}", Button)
                if i - 1 == page:
                    page_btn.variant = "primary"
                else:
                    page_btn.variant = "default"
            except Exception:
                continue

    def select_save_slot(self, slot_id: str) -> None:
        """Выбор слота сохранения"""
        save_menu = self.query_one("#save-menu")

        # Сброс предыдущего выделения
        if save_menu.selected_slot:
            try:
                old_btn = self.query_one(f"#{save_menu.selected_slot}", Button)
                old_btn.remove_class("save-slot-selected")
            except Exception:
                pass

        save_menu.selected_slot = slot_id

        # Новое выделение
        try:
            new_btn = self.query_one(f"#{slot_id}", Button)
            new_btn.add_class("save-slot-selected")
        except Exception:
            pass

    def delete_selected_save(self) -> None:
        """Удаление выбранного сохранения"""
        save_menu = self.query_one("#save-menu")
        if not save_menu.selected_slot:
            return

        slot_index = int(save_menu.selected_slot.split("-")[-1])
        page = save_menu.current_page

        delete_save(page, slot_index)
        save_menu.all_saves = get_all_saves()
        save_menu.selected_slot = None
        self.update_save_menu_display()

    def load_selected_save(self) -> None:
        """Загрузка выбранного сохранения"""
        save_menu = self.query_one("#save-menu")
        if not save_menu.selected_slot:
            return

        slot_index = int(save_menu.selected_slot.split("-")[-1])
        page = save_menu.current_page

        game_state = load_game_state(page, slot_index)
        if game_state is None:
            return

        # Закрытие меню сохранений
        self.close_save_menu()

        # Сброс текущего состояния
        self.reset_game_view()

        # Восстановление состояния сценария.
        from script_parser import set_script_state
        variables = game_state.get("variables", {})
        if "state" in variables:
            set_script_state(variables["state"])
        else:
            # Формат сохранений до единого состояния.
            set_script_state({
                "lp_sl": variables.get("SL", 0),
                "lp_un": variables.get("UN", 0),
                "lp_dv": variables.get("DV", 0),
                "lp_us": variables.get("US", 0),
                "prologue": variables.get("PROLOGUE", 0),
                "d1_keys": variables.get("D1_KEYS", False),
            })
        # Persistent-флаги не должны откатываться загрузкой старого слота.
        self.load_persistent_state()
        self.update_script_header()

        # Восстановление сцены
        scene = game_state.get("scene", {})
        self.current_scene = scene.get("current_scene", "")
        self.current_scene_category = scene.get("current_scene_category", "")
        self.current_time = scene.get("current_time", "day")
        self._interface_hidden = False
        self.set_text_mode(scene.get("current_text_mode", "adv"))

        # Восстановление спрайтов
        sprites_data = game_state.get("sprites", {})
        self.restore_active_sprites(
            sprites_data.get("active_sprites", {}),
            sprites_data.get("sprite_order_seq", 0),
        )

        # Загрузка сценария
        script_runtime = game_state.get("script", {})
        is_format_3 = game_state.get("save_format") == 3 and isinstance(script_runtime, dict)
        script_filename = script_runtime.get("filename", "") if is_format_3 else game_state.get("script_filename", "")
        script_index = script_runtime.get("pc", 0) if is_format_3 else game_state.get("script_index", 0)

        if script_filename:
            if is_format_3 and not Path(script_filename).is_absolute():
                script_filename = str(self.ts_path / script_filename)
            self.script = ScriptParser(script_filename, self)
            if is_format_3:
                if not self.script.restore_runtime_state(script_runtime):
                    return
            else:
                # Совместимость с format 2: старый движок изменял список строк.
                runtime_lines = game_state.get("runtime_lines")
                if isinstance(runtime_lines, list) and all(
                    isinstance(line, str) for line in runtime_lines
                ):
                    self.script.restore_runtime_lines(runtime_lines)
                self.script.index = script_index
            # Скрытие главного меню (если загрузка из главного меню)
            if save_menu.opened_from == "menu":
                self.query_one("#main-menu").add_class("hidden")
                self.query_one(Footer).remove_class("hidden")

            # Показ игровых элементов
            self.query_one("#novel-menu").remove_class("hidden")
            self.query_one("#novel-window").remove_class("hidden")
            self.sync_text_mode_display()

            # Восстановление текста и имени персонажа
            dialogue = game_state.get("dialogue", {})
            text_bar = self.query_one("#text-bar", Widget)

            # Очистка старых CSS-классов персонажа
            text_bar.remove_class(*[cls for cls in text_bar.classes if cls != "text-bar"])

            # Установка имени и текста
            text_bar.border_title = dialogue.get("speaker", "")
            text_bar.text = dialogue.get("text", "")

            # Восстановление CSS-класса персонажа для цвета имени
            saved_speaker_id = dialogue.get("speaker_id")
            if saved_speaker_id:
                text_bar.add_class(saved_speaker_id)

            text_bar.refresh()

            # Отрисовка и прогрев выполняются под полноэкранным оверлеем.
            self.mark_scene_dirty()
            self.start_script_preload(self.script)

            # Фокус на кнопку "Вперёд"
            self.query_one("#btn-next", Button).focus()

    def save_to_selected_slot(self) -> None:
        """Сохранение в выбранный слот"""
        save_menu = self.query_one("#save-menu")
        if not save_menu.selected_slot:
            return

        # Сохранение доступно только из паузы
        if save_menu.opened_from != "pause":
            return

        slot_index = int(save_menu.selected_slot.split("-")[-1])
        page = save_menu.current_page

        # Проверка: можно ли сохранять в текущем состоянии
        if not self.is_savable_game_state():
            return

        import script_parser

        # Текущий текст и имя персонажа из текстового бара
        text_bar = self.query_one("#text-bar", Widget)
        current_speaker = str(text_bar.border_title) if text_bar.border_title else ""
        current_text = text_bar.text if text_bar.text else ""
        # speaker_id — CSS-класс персонажа (sl, un, dv и т.д.)
        speaker_classes = [cls for cls in text_bar.classes if cls != "text-bar"]
        speaker_id = speaker_classes[0] if speaker_classes else None

        # Сбор состояния игры
        script_runtime = self.script.get_runtime_state() if hasattr(self, "script") else {}
        if script_runtime:
            try:
                script_runtime["filename"] = str(
                    Path(script_runtime["filename"]).resolve().relative_to(self.ts_path.resolve())
                )
            except ValueError:
                # Внешний сценарий сохраняем абсолютным путём как крайний случай.
                pass

        game_state = {
            "save_format": 3,
            "script": script_runtime,
            "variables": {
                "state": script_parser.get_script_state(),
            },
            "scene": {
                "current_scene": getattr(self, "current_scene", ""),
                "current_scene_category": getattr(self, "current_scene_category", ""),
                "current_time": getattr(self, "current_time", "day"),
                "current_text_mode": getattr(self, "current_text_mode", "adv"),
            },
            "sprites": {
                "active_sprites": self._active_sprites,
                "sprite_order_seq": self._sprite_order_seq,
            },
            "dialogue": {
                "speaker": current_speaker,
                "speaker_id": speaker_id,
                "text": current_text,
            },
        }

        from datetime import datetime
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        save_game_state(page, slot_index, game_state, timestamp)

        # Обновление отображения
        save_menu.all_saves = get_all_saves()
        self.update_save_menu_display()

    # ============ Функции - прочие ============
    async def key_space(self, event: events.Key) -> None:
        """Обработка пробела как перехода с фильтрацией ввода во время анимации."""
        now = getattr(event, "time", None) or _time.get_time()
        idle_for = now - self._space_last_event_at
        self._space_last_event_at = now

        # Пропуск задержки всегда имеет приоритет над фильтром анимации:
        # <w> находится внутри показа реплики, а pause помечается блокировкой.
        if self.skip_script_delay():
            # Не позволяем автоповтору того же удерживаемого пробела перейти
            # дальше после того, как фоновая задача продолжит сценарий.
            self._space_require_idle = True
            return

        if self._space_require_idle:
            if idle_for < self._space_idle_gap:
                return
            self._space_require_idle = False

        if self._is_space_event_during_animation(event):
            return
        await self.action_next_scene()

    def _get_scene_image_path(self, category: str, scene_name: str) -> str | None:
        """Возвращает путь до файла фона/CG."""
        for ext in ("jpg", "jpeg", "png", "webp"):
            candidate = self.ts_path / "game" / category / f"{scene_name}.{ext}"
            if candidate.exists():
                return str(candidate)
        return None

    def _load_sprite_resources(self):
        """Ленивая загрузка resources.yaml для сборщика спрайтов."""
        if self._sprite_resources_loaded:
            return self._sprite_resources

        self._sprite_resources_loaded = True
        resource_candidates = (
            (self.ts_path / "resources.yaml", self.ts_path / "game"),
            (Path("resources.yaml"), self.ts_path / "game"),
        )
        for candidate, assets_root in resource_candidates:
            if not candidate.exists():
                continue

            try:
                self._sprite_resources = load_sprite_resources_yaml(candidate)
                self._sprite_assets_root = assets_root
            except Exception as e:
                self._sprite_resources = None
                self.sub_title = f"Sprite resources error: {e}"
            return self._sprite_resources

        self._sprite_resources = None
        self.sub_title = "Sprite resources not found"
        return None

    @staticmethod
    def _sprite_position_factor(position: str | None) -> float:
        """Позиция спрайта по горизонтали."""
        mapping = {
            "fleft": 0.18,
            "left": 0.30,
            "cleft": 0.40,
            "center": 0.50,
            "cright": 0.60,
            "right": 0.70,
            "fright": 0.82,
        }
        key = (position or "center").strip().lower()
        return mapping.get(key, 0.50)

    @staticmethod
    def _sprite_size_scale(size_name: str | None) -> float:
        """Доп. масштаб из show size <...>."""
        mapping = {
            "normal": 1.0,
            "small": 0.86,
            "large": 1.12,
            "big": 1.12,
        }
        key = (size_name or "normal").strip().lower()
        return mapping.get(key, 1.0)

    def _sorted_active_sprites(self, active_sprites: dict | None = None) -> list[dict]:
        """Возвращает активные спрайты в порядке от заднего к переднему."""
        source = self._active_sprites if active_sprites is None else active_sprites
        sprites = sorted(source.values(), key=lambda item: item.get("order", 0))
        if len(sprites) <= 1:
            return sprites

        # Учитываем `behind <character>`.
        guard = 0
        max_passes = len(sprites) * len(sprites)
        while guard < max_passes:
            changed = False
            for idx, item in enumerate(list(sprites)):
                behind_id = item.get("behind")
                if not behind_id:
                    continue

                target_idx = next(
                    (i for i, candidate in enumerate(sprites) if candidate.get("character") == behind_id),
                    None,
                )
                if target_idx is None:
                    continue

                if idx > target_idx:
                    sprites.insert(target_idx, sprites.pop(idx))
                    changed = True
                    break

            if not changed:
                break
            guard += 1

        return sprites

    def mark_scene_dirty(self) -> None:
        """Помечает логическую сцену изменённой и инвалидирует старый UI-рендер."""
        self.scene_dirty = True
        self._scene_generation += 1

    def _make_scene_snapshot(
        self,
        category: str,
        name: str,
        active_sprites: dict,
    ) -> SceneRenderSnapshot:
        sprites = tuple(
            RenderSprite(
                character=str(sprite.get("character", "")),
                show_line=str(sprite.get("show_line", "")),
                image_path=str(sprite.get("image_path", "")),
                at=str(sprite.get("at") or "center"),
                size=str(sprite.get("size") or "normal"),
                behind=sprite.get("behind"),
                order=int(sprite.get("order", 0)),
            )
            for sprite in self._sorted_active_sprites(active_sprites)
        )
        return SceneRenderSnapshot(
            category=category,
            name=name,
            sprites=sprites,
            width=int(self.settings.get("quality", 150)),
            style=str(self.settings.get("style", "ANSI")),
            cache_epoch=self._cache_epoch,
        )

    def _capture_scene_snapshot(self) -> SceneRenderSnapshot:
        return self._make_scene_snapshot(
            getattr(self, "current_scene_category", ""),
            getattr(self, "current_scene", ""),
            {key: value.copy() for key, value in self._active_sprites.items()},
        )

    def _get_cached_render(self, key: tuple) -> Text | None:
        with self._cache_lock:
            cached = self._scene_render_cache.get(key)
            if cached is not None:
                self._scene_render_cache.move_to_end(key)
            return cached

    def _remember_render(self, key: tuple, art: Text) -> Text:
        with self._cache_lock:
            self._scene_render_cache[key] = art
            self._scene_render_cache.move_to_end(key)
            while len(self._scene_render_cache) > self._render_cache_limit:
                self._scene_render_cache.popitem(last=False)
        return art

    def _load_rgba_cached(self, path: str, cache_epoch: int) -> Image.Image:
        """Возвращает изменяемую копию RGBA, сохраняя декодированный оригинал в LRU."""
        with self._cache_lock:
            cached = self._decoded_image_cache.get(path)
            if cached is not None:
                self._decoded_image_cache.move_to_end(path)
                return cached[0].copy()

        with Image.open(path) as source:
            decoded = source.convert("RGBA")
        size = decoded.width * decoded.height * 4

        with self._cache_lock:
            existing = self._decoded_image_cache.get(path)
            if existing is not None:
                decoded.close()
                self._decoded_image_cache.move_to_end(path)
                return existing[0].copy()
            if (
                cache_epoch == self._cache_epoch
                and size <= self._decoded_image_cache_limit
            ):
                self._decoded_image_cache[path] = (decoded, size)
                self._decoded_image_cache_bytes += size
                while (
                    self._decoded_image_cache
                    and self._decoded_image_cache_bytes > self._decoded_image_cache_limit
                ):
                    _, (old_image, old_size) = self._decoded_image_cache.popitem(last=False)
                    self._decoded_image_cache_bytes -= old_size
                    old_image.close()
                return decoded.copy()
        return decoded

    async def _run_scene_render(self, snapshot: SceneRenderSnapshot) -> Text:
        async with self._render_semaphore:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._render_scene_snapshot, snapshot
            )

    def _render_scene_snapshot(self, snapshot: SceneRenderSnapshot) -> Text:
        """CPU-часть полного рендера. Метод не обращается к Textual-виджетам."""
        cached = self._get_cached_render(snapshot.key)
        if cached is not None:
            return cached
        if not snapshot.name or not snapshot.category:
            return Text("")

        scene_path = self._get_scene_image_path(snapshot.category, snapshot.name)
        if scene_path is None:
            return Text.from_markup(
                f"[Файл не найден: TS/game/{snapshot.category}/{snapshot.name}.*]"
            )

        palette = Palettes.color if snapshot.style == "ANSI" else Palettes.ascii
        try:
            composed = self._load_rgba_cached(scene_path, snapshot.cache_epoch)
            for sprite in snapshot.sprites:
                if not sprite.image_path or not os.path.exists(sprite.image_path):
                    continue
                sprite_img = self._load_rgba_cached(
                    sprite.image_path, snapshot.cache_epoch
                )
                scale = self._sprite_size_scale(sprite.size)
                if abs(scale - 1.0) > 1e-3:
                    resized = sprite_img.resize(
                        (
                            max(1, int(sprite_img.width * scale)),
                            max(1, int(sprite_img.height * scale)),
                        ),
                        resample=Image.NEAREST,
                    )
                    sprite_img.close()
                    sprite_img = resized
                max_sprite_height = max(1, int(composed.height * 0.98))
                if sprite_img.height > max_sprite_height:
                    resized = sprite_img.resize(
                        (
                            max(
                                1,
                                int(
                                    sprite_img.width
                                    * (max_sprite_height / sprite_img.height)
                                ),
                            ),
                            max_sprite_height,
                        ),
                        resample=Image.NEAREST,
                    )
                    sprite_img.close()
                    sprite_img = resized
                x = int(
                    composed.width * self._sprite_position_factor(sprite.at)
                    - sprite_img.width / 2
                )
                x = max(0, min(x, composed.width - sprite_img.width))
                y = max(0, composed.height - sprite_img.height)
                composed.alpha_composite(sprite_img, dest=(x, y))
                sprite_img.close()

            ansi_art = convert_img(
                composed,
                width=snapshot.width,
                alpha=not snapshot.sprites,
                palette=palette,
            )
            composed.close()
            art = Text.from_ansi(ansi_art)
        except Exception as exc:
            art = Text.from_markup(f"[Ошибка сборки сцены со спрайтами: {exc}]")

        if snapshot.cache_epoch == self._cache_epoch:
            self._remember_render(snapshot.key, art)
        return art

    async def _get_render_async(self, snapshot: SceneRenderSnapshot) -> Text:
        cached = self._get_cached_render(snapshot.key)
        if cached is not None:
            return cached
        task = self._render_tasks.get(snapshot.key)
        if task is None:
            task = asyncio.create_task(self._run_scene_render(snapshot))
            self._render_tasks[snapshot.key] = task
        try:
            return await task
        finally:
            if self._render_tasks.get(snapshot.key) is task:
                self._render_tasks.pop(snapshot.key, None)

    def _snapshot_after_visual_commands(
        self, commands: tuple[str, ...]
    ) -> SceneRenderSnapshot | None:
        """Строит снимок будущего кадра без изменения настоящей сцены."""
        category = getattr(self, "current_scene_category", "")
        name = getattr(self, "current_scene", "")
        active = {key: value.copy() for key, value in self._active_sprites.items()}
        order_seq = self._sprite_order_seq

        for line in commands:
            if line.startswith("scene color"):
                category = ""
                name = ""
                active.clear()
                order_seq = 0
                continue
            scene_match = re.search(
                r"scene\s+(cg|bg)\s+([a-zA-Z0-9_]+)", line
            )
            if scene_match:
                category, name = scene_match.groups()
                active.clear()
                order_seq = 0
                continue
            if line.startswith("show "):
                built = self._build_sprite_png(line)
                if built is None:
                    continue
                request, out_path = built
                previous = active.get(request.character)
                if previous is None:
                    order_seq += 1
                    order = order_seq
                else:
                    order = previous.get("order", 0)
                active[request.character] = {
                    "character": request.character,
                    "show_line": line,
                    "image_path": str(out_path),
                    "at": request.at or (previous.get("at") if previous else "center"),
                    "size": request.size or (
                        previous.get("size") if previous else "normal"
                    ),
                    "behind": request.extras.get("behind") if request.extras else None,
                    "order": order,
                }
                continue
            hide_match = re.search(r"hide\s+([a-zA-Z0-9_]+)", line)
            if hide_match:
                active.pop(hide_match.group(1), None)

        if not name or not category:
            return None
        return self._make_scene_snapshot(category, name, active)

    @staticmethod
    def _consume_prefetch_result(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            # Prefetch — оптимизация; ошибка не должна останавливать сценарий.
            pass

    def _schedule_snapshot_prefetch(
        self, snapshot: SceneRenderSnapshot | None
    ) -> None:
        if snapshot is None or self._get_cached_render(snapshot.key) is not None:
            return
        task = asyncio.create_task(self._get_render_async(snapshot))
        self._prefetch_tasks.add(task)

        def done(completed: asyncio.Task) -> None:
            self._prefetch_tasks.discard(completed)
            self._consume_prefetch_result(completed)

        task.add_done_callback(done)

    def prefetch_next_scene(self, script: ScriptParser) -> None:
        """Готовит следующий детерминированный кадр, пока читается диалог."""
        commands = script.predict_visual_commands()
        self._schedule_snapshot_prefetch(
            self._snapshot_after_visual_commands(commands)
        )

    def prefetch_choice_scenes(self, script: ScriptParser, choices) -> None:
        """Готовит первый кадр каждой доступной ветки во время выбора."""
        for choice in choices:
            commands = script.predict_choice_visual_commands(choice)
            self._schedule_snapshot_prefetch(
                self._snapshot_after_visual_commands(commands)
            )

    async def flush_scene_render(self) -> None:
        """Рендерит сцену только в момент, когда её действительно увидит игрок."""
        if not self.scene_dirty:
            return
        if not getattr(self, "current_scene", ""):
            self.query_one("#bg-cg", Widget).update("")
            self.scene_dirty = False
            return
        generation = self._scene_generation
        snapshot = self._capture_scene_snapshot()
        art = await self._get_render_async(snapshot)
        if generation != self._scene_generation:
            return
        self.query_one("#bg-cg", Widget).update(art)
        self.scene_dirty = False

    def start_script_preload(self, script: ScriptParser) -> None:
        """Неблокирующе прогревает чистые фоны активного сценарного файла."""
        filename = str(Path(script.filename).resolve())
        # Сначала инвалидируем старый worker: поток, закончившийся после
        # отмены задачи, не должен вернуть старые данные в очищенный кэш.
        self._preload_generation += 1
        generation = self._preload_generation
        if self._script_preload_task and not self._script_preload_task.done():
            self._script_preload_task.cancel()
        if filename != self._preload_filename:
            # Кэш ограничен текущим файлом сценария, а не всей игрой.
            self._clear_render_caches()
            self._preload_filename = filename
        self._script_preload_task = asyncio.create_task(
            self._preload_script_scenes(script, generation)
        )

    def _clear_render_caches(self) -> None:
        """Очищает RAM-кэши и запрещает старым worker возвращать результаты."""
        self._cache_epoch += 1
        for task in tuple(self._render_tasks.values()):
            task.cancel()
        self._render_tasks.clear()
        for task in tuple(self._prefetch_tasks):
            task.cancel()
        self._prefetch_tasks.clear()
        with self._cache_lock:
            self._scene_render_cache.clear()
            self._sprite_build_cache.clear()
            for image, _ in self._decoded_image_cache.values():
                image.close()
            self._decoded_image_cache.clear()
            self._decoded_image_cache_bytes = 0

    def clear_script_cache(self) -> None:
        """Останавливает прогрев и освобождает кэш при выходе из игры."""
        self._preload_generation += 1
        if self._script_preload_task and not self._script_preload_task.done():
            self._script_preload_task.cancel()
        self._script_preload_task = None
        self._preload_filename = None
        self._clear_render_caches()
        self._loading_restore_novel = False
        try:
            self.query_one("#script-loading", Widget).add_class("hidden")
        except Exception:
            pass

    async def _preload_script_scenes(self, script: ScriptParser, generation: int) -> None:
        overlay = self.query_one("#script-loading", Widget)
        label = self.query_one("#script-loading-text", Label)
        scenes = script.resource_manifest.get("scenes", ())
        show_lines = script.resource_manifest.get("show_lines", ())
        novel_menu = self.query_one("#novel-menu", Widget)
        novel_window = self.query_one("#novel-window", Widget)
        self._loading_restore_novel = (
            not novel_menu.has_class("hidden") or not novel_window.has_class("hidden")
        )
        if self._loading_restore_novel:
            novel_menu.add_class("hidden")
            novel_window.add_class("hidden")
        overlay.remove_class("hidden")
        try:
            total = len(scenes) + len(show_lines)
            for number, (category, name) in enumerate(scenes, start=1):
                if generation != self._preload_generation:
                    return
                label.update(f"Подготовка сценария: {number}/{total}")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, self._cache_plain_scene, category, name, generation
                )
                # Даём Textual отрисовать индикатор и обработать ввод.
                await asyncio.sleep(0)
            for offset, show_line in enumerate(show_lines, start=len(scenes) + 1):
                if generation != self._preload_generation:
                    return
                label.update(f"Подготовка спрайтов: {offset}/{total}")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, self._build_sprite_png, show_line, generation
                )
                await asyncio.sleep(0)
            if generation == self._preload_generation:
                current_snapshot = self._capture_scene_snapshot()
                if current_snapshot.name and current_snapshot.category:
                    label.update("Подготовка текущего кадра…")
                    current_art = await self._get_render_async(current_snapshot)
                    if generation == self._preload_generation:
                        self.query_one("#bg-cg", Widget).update(current_art)
                        self.scene_dirty = False
                label.update("Подготовка следующего кадра…")
                snapshot = self._snapshot_after_visual_commands(
                    script.predict_visual_commands()
                )
                if snapshot is not None:
                    await self._get_render_async(snapshot)
        except asyncio.CancelledError:
            raise
        finally:
            if generation == self._preload_generation:
                overlay.add_class("hidden")
                if self._loading_restore_novel:
                    novel_menu.remove_class("hidden")
                    novel_window.remove_class("hidden")
                    self.sync_text_mode_display()
                    self.query_one("#btn-next", Button).focus()
                self._loading_restore_novel = False

    def _cache_plain_scene(
        self, category: str, name: str, generation: int | None = None
    ) -> None:
        snapshot = self._make_scene_snapshot(category, name, {})
        if self._get_cached_render(snapshot.key) is None:
            self._render_scene_snapshot(snapshot)

    def generate_scene_ansi(self, category: str, scene_name: str):
        """Конвертирует только сцену (без спрайтов) в ANSI/ASCII."""
        return self._render_scene_snapshot(
            self._make_scene_snapshot(category, scene_name, {})
        )

    def generate_scene_with_sprites_ansi(self):
        """Собирает сцену + активные спрайты и конвертирует в ANSI/ASCII."""
        return self._render_scene_snapshot(self._capture_scene_snapshot())

    def show_sprite_from_script_line(self, show_line: str):
        """Собирает PNG спрайта из show-строки и обновляет активный набор спрайтов."""
        built = self._build_sprite_png(show_line)
        if built is None:
            return None
        request, out_path = built

        previous = self._active_sprites.get(request.character)
        if previous is None:
            self._sprite_order_seq += 1
            order = self._sprite_order_seq
        else:
            order = previous.get("order", 0)

        self._active_sprites[request.character] = {
            "character": request.character,
            "show_line": show_line,
            "image_path": str(out_path),
            "at": request.at or (previous.get("at") if previous else "center"),
            "size": request.size or (previous.get("size") if previous else "normal"),
            "behind": request.extras.get("behind") if request.extras else None,
            "order": order,
        }

        return None

    def _build_sprite_png(self, show_line: str, generation: int | None = None):
        """Собирает или получает из кэша PNG, не изменяя состояние сцены."""
        resources = self._load_sprite_resources()
        if not resources:
            return None

        try:
            request = parse_show_like(show_line)
            cached_path = self._sprite_build_cache.get(show_line)
            if cached_path and os.path.exists(cached_path):
                out_path = Path(cached_path)
            else:
                digest = hashlib.sha256(
                    f"sprite-v2\0{show_line}".encode("utf-8")
                ).hexdigest()[:16]
                runtime_dir = self._sprite_runtime_dir
                try:
                    runtime_dir.mkdir(parents=True, exist_ok=True)
                except Exception:
                    runtime_dir = Path("/tmp/terminal-summer-sprites/generated_runtime")
                    runtime_dir.mkdir(parents=True, exist_ok=True)
                out_path = runtime_dir / f"{request.character}_{digest}.png"
                if not out_path.exists():
                    resolved = resolve_sprite(resources, request, self._sprite_assets_root)
                    sprite_img = compose_layers(
                        resolved.picks, request.extras.get("spritecolor")
                    )
                    try:
                        sprite_img.save(out_path, format="PNG")
                    finally:
                        sprite_img.close()
                if generation is None or generation == self._preload_generation:
                    self._sprite_build_cache[show_line] = str(out_path)
                    self._sprite_build_cache.move_to_end(show_line)
                    while len(self._sprite_build_cache) > self._sprite_cache_limit:
                        self._sprite_build_cache.popitem(last=False)
        except Exception as e:
            self.sub_title = f"Sprite build error: {e}"
            return None
        return request, out_path

    def restore_active_sprites(
        self,
        saved_sprites: dict,
        saved_order_seq: int,
    ) -> None:
        """Собирает спрайты из show-команд, не используя устаревший PNG-кэш."""
        self.clear_active_sprites()
        if not isinstance(saved_sprites, dict):
            return

        sprites = sorted(
            (sprite for sprite in saved_sprites.values() if isinstance(sprite, dict)),
            key=lambda sprite: sprite.get("order", 0),
        )
        for saved_sprite in sprites:
            show_line = saved_sprite.get("show_line")
            character = saved_sprite.get("character")
            if isinstance(show_line, str) and show_line.startswith("show "):
                self.show_sprite_from_script_line(show_line)
                restored_sprite = self._active_sprites.get(character)
                if restored_sprite is not None:
                    for key in ("at", "size", "behind", "order"):
                        if key in saved_sprite:
                            restored_sprite[key] = saved_sprite[key]
                continue

            # Старые сохранения не содержат show-команд. Оставляем прежний fallback.
            if isinstance(character, str):
                self._active_sprites[character] = saved_sprite.copy()

        self._sprite_order_seq = max(
            saved_order_seq if isinstance(saved_order_seq, int) else 0,
            max((sprite.get("order", 0) for sprite in self._active_sprites.values()), default=0),
        )

    def hide_sprite_by_id(self, character_id: str):
        """Удаляет персонажа со сцены."""
        self._active_sprites.pop(character_id, None)
        return None

    def clear_active_sprites(self):
        """Очищает активные спрайты сцены."""
        self._active_sprites.clear()
        self._sprite_order_seq = 0

    def load_persistent_state(self) -> bool:
        """Загружает общие для всех прохождений сценарные флаги."""
        if not self.PERSISTENT_FILE.exists():
            return False
        try:
            with self.PERSISTENT_FILE.open("r", encoding="utf-8") as file:
                state = json.load(file)
            from script_parser import update_persistent_state

            update_persistent_state(state)
            self.update_script_header()
            return True
        except (OSError, ValueError, TypeError) as exc:
            self.sub_title = f"[Persistent state error] {exc}"
            return False

    def save_persistent_state(self) -> None:
        """Атомарно сохраняет persistent-флаги рядом с настройками."""
        from script_parser import get_persistent_state

        state = get_persistent_state()
        temporary_path = self.PERSISTENT_FILE.with_suffix(".json.tmp")
        try:
            self.PERSISTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(state, file, indent=2, ensure_ascii=False)
            temporary_path.replace(self.PERSISTENT_FILE)
        except OSError as exc:
            self.sub_title = f"[Persistent state error] {exc}"
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def update_script_header(self) -> None:
        """Обновляет Header согласно выбранным группам сценарных переменных."""
        self.sub_title = format_script_state(
            include_lp_points=bool(
                self.settings.get("header_lp_points", True)
            ),
            include_flags=bool(self.settings.get("header_flags", True)),
        )

    def sync_header_filter_buttons(self) -> None:
        """Синхронизирует вид кнопок фильтра с сохранёнными настройками."""
        self.query_one("#btn-header-lp-points", Button).variant = (
            "success" if self.settings.get("header_lp_points", True) else "default"
        )
        self.query_one("#btn-header-flags", Button).variant = (
            "success" if self.settings.get("header_flags", True) else "default"
        )

    def load_settings(self):
        """Загрузка настроек"""
        if self.CONFIG_FILE.exists():
            with self.CONFIG_FILE.open("r", encoding="utf-8") as f:
                loaded_settings = json.load(f)
            if isinstance(loaded_settings, dict):
                self.settings = {
                    **self.DEFAULT_SETTINGS,
                    **loaded_settings,
                }
                if any(
                    key not in loaded_settings for key in self.DEFAULT_SETTINGS
                ):
                    self.save_settings()
        else:
            self.settings = self.DEFAULT_SETTINGS.copy()
            self.save_settings()
    
    def save_settings(self):
        """Сохранение настроек"""
        self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with self.CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4)

    def apply_settings(self):
        """Применение настроек при старте"""
        # Header
        if self.settings["header"]:
            self.query_one("Header").remove_class("hidden")
            self.query_one("#btn-header-on", Button).variant = "success"
            self.query_one("#btn-header-off", Button).variant = "default"
        else:
            self.query_one("Header").add_class("hidden")
            self.query_one("#btn-header-on", Button).variant = "default"
            self.query_one("#btn-header-off", Button).variant = "error"
        self.sync_header_filter_buttons()
        self.update_script_header()

        # Quality
        quality = self.settings["quality"]
        if quality == "50":
            self.query_one("#btn-small", Button).variant = "error"
        elif quality == "150":
            self.query_one("#btn-medium", Button).variant = "warning"
        elif quality == "200":
            self.query_one("#btn-large", Button).variant = "success"

        # ASCIIorANSI
        style = self.settings["style"]
        if style == "ANSI":
            self.query_one("#btn-ANSI", Button).variant = "primary"
        elif style == "ASCII":
            self.query_one("#btn-ASCII", Button).variant = "primary"

        # TextSpeed
        text_speed = self.settings["text_speed"]
        self.text_speed = float(text_speed)
        if text_speed == "0.04":
            self.query_one("#btn-speed-slow", Button).variant = "error"
        elif text_speed == "0.025":
            self.query_one("#btn-speed-medium", Button).variant = "warning"
        elif text_speed == "0.01":
            self.query_one("#btn-speed-fast", Button).variant = "success"
        elif text_speed == "0":
            self.query_one("#btn-speed-instantly", Button).variant = "primary"

    def load_gallery_images(self):
        """Загружает список JPG/PNG файлов из папки TS/game/bg или TS/game/cg"""
        # Папка с изображениями
        folder = self.ts_path / "gallery" / self.gallery_mode

        previous_filename = (
            self.gallery_images[self.gallery_index]
            if self.gallery_images and 0 <= self.gallery_index < len(self.gallery_images)
            else None
        )

        if os.path.exists(folder):
            # Берём JPG/PNG
            self.gallery_images = sorted([
                f for f in os.listdir(folder)
                if f.lower().endswith((".jpg", ".jpeg", ".png"))
            ])
        else:
            self.gallery_images = []

        # Восстанавливаем индекс, если файл существует
        if previous_filename in self.gallery_images:
            self.gallery_index = self.gallery_images.index(previous_filename)
        else:
            self.gallery_index = 0

    def update_gallery_display(self):
        """Конвертация JPG в ANSI арт и обновление отображения"""
        if not self.gallery_images:
            self.query_one("#bg-cg-gallery", Static).update("[Ничего не найдено]")
            self.query_one(GalleryMenuMidBtns).border_title = "Пусто"
            return

        filename = self.gallery_images[self.gallery_index]
        image_path = self.ts_path / "gallery" / self.gallery_mode / filename
        img = Image.open(image_path)

        # gallery_size = "50" / "150" / "200"
        width = int(self.gallery_size)

        try:
            ansi_art = convert_img(img, width=width, alpha=True, palette=Palettes.color)
        except Exception as e:
            ansi_art = f"[Ошибка конвертации изображения: {e}]"

        static = self.query_one("#ansi-content", Static)
        static.update(Text.from_ansi(ansi_art))

        self.query_one(GalleryMenuMidBtns).border_title = os.path.splitext(filename)[0]

    async def update_current_scene_art(self):
        """Перерисовывает текущий арт при смене качества."""
        if not hasattr(self, "current_scene") or not self.current_scene:
            return
        if not hasattr(self, "current_scene_category") or not self.current_scene_category:
            return

        self.mark_scene_dirty()
        await self.flush_scene_render()

        # Для новых параметров ANSI/ASCII прогреваем только активный файл.
        if hasattr(self, "script"):
            settings_menu = self.query_one("#settings-menu", Widget)
            if settings_menu.has_class("hidden"):
                self.start_script_preload(self.script)
            else:
                self._preload_after_settings = True

    def reset_game_view(self):
        """Сбрасывает визуальное состояние игры перед выходом в меню"""
        self.set_game_paused(False)
        self.cancel_script_advance()
        # Отменённый парсер больше не считается активным: его finally-блоки
        # не смогут восстановить элементы UI уже сброшенной или новой игры.
        if hasattr(self, "script"):
            del self.script

        # Получаем элементы
        text_bar = self.query_one("#text-bar", Widget)
        bg_cg = self.query_one("#bg-cg", Widget)
        novel_menu = self.query_one("#novel-menu", Widget)
        novel_window = self.query_one("#novel-window", Widget)
        next_button = self.query_one("#btn-next", Button)

        # Очистка текста и имени персонажа
        text_bar.text = ""
        text_bar.border_title = ""
        text_bar.refresh()

        # Во время анимации реплики кнопка скрыта. Отменённый старый parser-task
        # не должен менять UI загруженного сценария, поэтому нормализуем кнопку
        # здесь явно до восстановления сохранения или запуска новой игры.
        next_button.remove_class("invisible")
        next_button.disabled = False

        # Очистка ASCII-фона
        bg_cg.update("")
        self.clear_active_sprites()
        self.current_scene = ""
        self.current_scene_category = ""
        self.scene_dirty = False
        self.clear_script_cache()

        # Очистка pending_choices
        if hasattr(self, "pending_choices"):
            self.pending_choices = None

        # Очистка истории диалогов
        self.clear_log()

        # Сброс блокировки перехода по строкам
        self._next_scene_in_progress = False
        self._text_animating = False
        self._text_animating_since = None
        self._text_animating_until = 0.0
        self._input_blocked = False
        self._input_blocked_since = None
        self._input_blocked_until = 0.0
        self._space_last_event_at = 0.0
        self._space_require_idle = False
        self._interface_hidden = False
        self.set_text_mode("adv")
        novel_menu.add_class("hidden")
        novel_window.add_class("hidden")

    def can_advance_scene(self) -> bool:
        """Можно ли переходить к следующей строке по пользовательскому вводу."""
        if self._next_scene_in_progress:
            return False
        if self._text_animating:
            return False
        if not hasattr(self, "script"):
            return False

        if self.query_one("#novel-menu").has_class("hidden"):
            return False
        if not self.query_one("#choice-bar").has_class("hidden"):
            return False
        if self.query_one("#btn-next", Button).has_class("invisible"):
            return False

        return True
    
    async def _advance_from_button(self) -> None:
        """Переключение по кнопке (без анти-repeat логики клавиатуры)."""
        await self._advance_script_line()

    def _is_space_event_during_animation(self, event: events.Key) -> bool:
        """True если событие пробела было сгенерировано во время блокировки ввода."""
        if self._text_animating or self._input_blocked:
            return True

        event_time = getattr(event, "time", None)
        if event_time is None:
            return False

        if (
            self._text_animating_since is not None
            and self._text_animating_since <= event_time <= self._text_animating_until
        ):
            return True

        if (
            self._input_blocked_since is not None
            and self._input_blocked_since <= event_time <= self._input_blocked_until
        ):
            return True

        return False

    async def _advance_script_line(self) -> None:
        """Запрашивает выполнение следующей строки без блокировки очереди UI."""
        if self.skip_script_delay():
            return
        self._start_script_advance()

    def _start_script_advance(self) -> bool:
        """Запускает единственную фоновую цепочку выполнения сценария."""
        if self._next_scene_in_progress:
            return False
        if not hasattr(self, "script"):
            return False
        if not self.can_advance_scene():
            return False

        self._next_scene_in_progress = True
        task = asyncio.create_task(self.script.next_line())
        self._script_advance_task = task
        task.add_done_callback(self._on_script_advance_done)
        return True

    def _on_script_advance_done(self, task: asyncio.Task) -> None:
        """Освобождает переход после завершения только актуальной задачи."""
        if self._script_advance_task is task:
            self._script_advance_task = None
            self._next_scene_in_progress = False

        if task.cancelled():
            return

        try:
            task.result()
        except Exception as exc:
            # Исключение уже извлечено из Task и не останется незамеченным.
            self.sub_title = f"[Script error] {exc}"

    def set_game_paused(self, paused: bool) -> None:
        """Меняет состояние паузы и будит ожидающие сценарные задачи."""
        paused = bool(paused)
        if self._game_paused == paused:
            return
        self._game_paused = paused
        previous_event = self._game_pause_changed_event
        self._game_pause_changed_event = asyncio.Event()
        previous_event.set()

    async def wait_until_game_resumed(self) -> None:
        """Не даёт сценарию и анимации текста идти под меню паузы."""
        while self._game_paused:
            pause_changed = self._game_pause_changed_event
            await pause_changed.wait()

    async def wait_script_delay(
        self, seconds: float, kind: str, *, skippable: bool = True
    ) -> bool:
        """Ждёт сценарную задержку или её пропуск действием «Далее»."""
        if seconds <= 0:
            return False

        delay_event = asyncio.Event()
        self._script_delay_generation += 1
        generation = self._script_delay_generation
        self._script_delay_event = delay_event
        self._script_delay_kind = kind
        self._script_delay_skippable = skippable
        self._input_blocked = True
        self._input_blocked_since = _time.get_time()
        self._input_blocked_until = self._input_blocked_since

        remaining = seconds
        try:
            while remaining > 0:
                await self.wait_until_game_resumed()
                started_at = _time.get_time()
                pause_changed = self._game_pause_changed_event
                delay_task = asyncio.create_task(delay_event.wait())
                pause_task = asyncio.create_task(pause_changed.wait())
                try:
                    done, pending = await asyncio.wait(
                        (delay_task, pause_task),
                        timeout=remaining,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for task in (delay_task, pause_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        delay_task, pause_task, return_exceptions=True
                    )

                elapsed = max(0.0, _time.get_time() - started_at)
                remaining = max(0.0, remaining - elapsed)
                if delay_event.is_set():
                    return True
                if not done:
                    return False
            return False
        finally:
            # Старая отменённая задача не должна очищать состояние новой паузы.
            if (
                self._script_delay_event is delay_event
                and self._script_delay_generation == generation
            ):
                self._script_delay_event = None
                self._script_delay_kind = None
                self._script_delay_skippable = False
                self._input_blocked = False
                self._input_blocked_until = _time.get_time()

    def skip_script_delay(self) -> bool:
        """Завершает только активную сценарную задержку."""
        delay_event = self._script_delay_event
        if (
            delay_event is None
            or not self._script_delay_skippable
            or delay_event.is_set()
        ):
            return False
        delay_event.set()
        return True

    def cancel_script_delay(self) -> None:
        """Сбрасывает ожидание при отмене или смене сценария."""
        delay_event = self._script_delay_event
        self._script_delay_generation += 1
        self._script_delay_event = None
        self._script_delay_kind = None
        self._script_delay_skippable = False
        self._input_blocked = False
        self._input_blocked_since = None
        self._input_blocked_until = _time.get_time()
        if delay_event is not None:
            delay_event.set()

    def cancel_script_advance(self) -> None:
        """Отменяет старое выполнение сценария и его активную задержку."""
        task = self._script_advance_task
        self._script_advance_task = None
        self._next_scene_in_progress = False
        self.cancel_script_delay()
        if task is not None and not task.done():
            task.cancel()

    def add_log_entry(
        self,
        text: str,
        speaker: str = "",
        speaker_id: str | None = None,
    ) -> None:
        if not text:
            return
        self.query_one("#log-menu", LogMenu).add_dialogue_entry(
            text=text,
            speaker=speaker,
            speaker_id=speaker_id,
        )

    def clear_log(self) -> None:
        self.query_one("#log-menu", LogMenu).clear()


if __name__ == "__main__":
    main()
    app = TerminalSummer()
    app.run()
