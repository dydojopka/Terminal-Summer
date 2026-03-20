import os
import json
# import simpleaudio as sa
import threading
import asyncio

from PIL import Image
from pil2ansi import convert_img, Palettes

from textual import events, errors, _time
from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Label, Footer, Header, Static, ListView, ListItem, Log
from textual.widget import Widget
from textual.binding import Binding

from rich.style import Style
from rich.segment import Segment
from rich.text import Text

from script_parser import ScriptParser

SPEAKER_NAME_COLORS = {
    "dreamgirl": "rgb(192,192,192)",
    "sl": "rgb(255,210,0)",
    "slp": "rgb(255,210,0)",
    "slg": "rgb(255,210,0)",
    "sa": "rgb(255,210,0)",
    "un": "rgb(185,86,255)",
    "unp": "rgb(185,86,255)",
    "dv": "rgb(255,170,0)",
    "dvp": "rgb(255,170,0)",
    "dvg": "rgb(255,170,0)",
    "el": "rgb(255,255,0)",
    "elp": "rgb(255,255,0)",
    "ro": "rgb(255,255,0)",
    "us": "rgb(255,50,0)",
    "usp": "rgb(255,50,0)",
    "usg": "rgb(255,50,0)",
    "mt": "rgb(0,234,50)",
    "mtp": "rgb(0,234,50)",
    "mt_voice": "rgb(0,234,50)",
    "cs": "rgb(165,165,255)",
    "mz": "rgb(114,160,255)",
    "mi": "rgb(0,252,255)",
    "ma": "rgb(0,252,255)",
    "uv": "rgb(78,255,0)",
    "uvp": "rgb(78,255,0)",
    "sh": "rgb(255,242,38)",
    "pi": "rgb(230,0,0)",
    "me": "rgb(225,221,125)",
    "FIXME_voice": "rgb(192,192,192)",
    "bush": "rgb(192,192,192)",
    "message": "rgb(192,192,192)",
    "odn": "rgb(192,192,192)",
    "all": "rgb(227,58,58)",
}

class AnsiView(Static):
    can_focus = False
    can_focus_children = False
    ALLOW_SELECT = False

    def on_mount(self) -> None:
        # ANSI-арт не интерактивен: отключаем лишнюю обработку мыши и ссылок.
        self.auto_links = False
        self.disable_messages(events.MouseMove, events.Enter, events.Leave)

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

# class AudioPlayer:
#     """Класс для управления аудио"""
#     def __init__(self):
#         self.current_playback = None
        
#     def play_sound(self, file_path, loop=False):
#         """Воспроизведение звука в отдельном потоке"""
#         def play():
#             try:
#                 wave_obj = sa.WaveObject.from_wave_file(file_path)
#                 play_obj = wave_obj.play()
                
#                 if loop:
#                     play_obj.wait_done()
#                     self.play_sound(file_path, loop=True)
                    
#             except Exception as e:
#                 print(f"Ошибка воспроизведения звука: {e}")
        
#         # Останавливаем предыдущее воспроизведение
#         if self.current_playback:
#             self.current_playback.stop()
            
#         # Запускаем в отдельном потоке
#         self.current_playback = threading.Thread(target=play, daemon=True)
#         self.current_playback.start()
    
#     def stop(self):
#         """Остановка воспроизведения"""
#         if self.current_playback:
#             sa.stop_all()



class MainMenu(Static):
    """Виджет главного меню"""
    BORDER_TITLE="Главное меню"
    def compose(self):
        yield MainMenuMiddleBtns()
        yield MainMenuBottomBtns()
    
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
        yield Button("Достижения 🏅", id="btn-achievements")
        yield Button("Настройки 🪛", id="btn-settings-menu")
        yield Button("Выход 🚪", id="btn-exit-menu")

class MainMenuStartBtn(Vertical):
    """Виджет для кнопки "Начать игру" с описанием"""
    def compose(self):
        yield Button("Начать игру ▶", id="btn-start-game")
        yield Label('   Дорогой пионер!\n   Ты — на пороге удивительных открытий.\n   Перед тобой распахнулись двери самого прекрасного места в мире — нашего любимого лагеря "Совёнок". Эта смена запомниться тебе на всю жизнь.\nДобро пожаловать!')

class MainMenuLoadBtn(Vertical):
    """Виджет для кнопки "Соханение" с описанием"""
    def compose(self):
        yield Button("Сохранение 📒", id="btn-save-load")
        yield Label('   Бережно относись к истории своего лагеря. Тщательно записывай свои наблюдения и мысли о прошедших днях.\nПри помощи сохранений ты всегда сможешь вернутся назад к пройденному эпизоду и осмыслить его заново. Удачи тебе в твоих начинаниях!\n   Если что-то пойдёт не так, ты знаешь, что делать')

class MainMenuGalleryBtn(Vertical):
    """Виджет для кнопки "Галерея" с описанием"""
    def compose(self):
        yield Button("Галерея 📷", id="btn-gallery")
        yield Label('   Здесь представлены работы участников нашего фотокружка. Твои товарищи всегда готовы запечатлеть важные моменты из жини лагеря, а на многих снимках ты сможешь встретить и себя. Будь опрятен и своим поведением подавай пример окружающим.')


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


class PauseMenu(Static):
    """Виджет меню паузы"""
    def compose(self):
        yield PauseMenuContainer()

class PauseMenuContainer(VerticalScroll):
    """Доп контейнер для меню паузы(Для отображения title)"""
    BORDER_TITLE = "Пауза"
    def compose(self):
        yield Button("Продолжить", id="btn-continue")
        yield Button("Сохранить", id="btn-save")
        yield Button("Загрузить", id="btn-load")
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
        with HorizontalGroup():
            yield Button("Включить", variant="default", id="btn-header-on")
            yield Button("Выключить", variant="error", id="btn-header-off")
            yield DescriptionSettingHeader()

class DescriptionSettingHeader(Widget):
    """Описание настройки Header"""
    def render(self):
        return "Верхняя панель расположена сверху и будет отображать: название программы, название текущей сцены, и часы \n(может слегка уменьшить обзор)"

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
    """Описание настройки Quality"""
    def render(self):
        return 'Размер артов необходимо подбирать по размеру окна консоли,\nс сильно большим размером - изображение может не поместиться.\n\nМожете так же попробовать уменьшить размер шрифта самой консоли (Обычно это Ctrl+"+" и Ctrl+"-")'

class SettingASCIIorANSI(Widget):
    """Виджет с настройкой стиля артов"""
    BORDER_TITLE = "Стиль артов"
    def compose(self):
        with HorizontalGroup():
            yield Button("ANSI", variant="default", id="btn-ANSI")
            yield Button("ASCII", variant="default", id="btn-ASCII")
            yield DescriptionSettingASCIIorANSI()

class DescriptionSettingASCIIorANSI(Widget):
    """Описание настройки стиля артов"""
    def render(self):
        return 'ANSI  - изображение будет цветным\nASCII - изображение будет состоять из символов .,:+*? и другие'

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
    """Описание настройки TextSpeed"""
    def render(self):
        return "Скорость появления текста в текстовом окне.\n\nМедленный   - 0.04\nСредний     - 0.025\nБыстрый     - 0.01\nМоментально - 0"


class NovelMenu(Static):
    """Виджет-контейнер для текст бара и кнопок"""
    def compose(self):
        yield Button("История", id="btn-log")
        yield TextBar(id="text-bar")
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

        Если append=True → добавляет текст к текущему,
        Если append=False → начинает с нуля"""

        speed = float(self.app.text_speed)
        
        if not append:
            self.text = ""
            self.refresh()

        for char in new_text:
            self.text += char
            self.refresh()
            await asyncio.sleep(speed)

        self.refresh()


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
    CSS_PATH = "gameUI.tcss"

    CONFIG_FILE = "settings.json"

    def __init__(self):
        super().__init__()
        self.settings = {
            "header": False,
            "quality": "150",
            "style": "ANSI",
            "text_speed": "0.025",
        }
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

    text_speed = "0.025" # Скорость текста 0.04 | 0.025 | 0.01 | 0

    gallery_mode = "cg"
    gallery_size = "150" # small - 50 | medium - 150 | large - 200
    gallery_index = 0
    gallery_images = []

    BINDINGS = [
        Binding("escape", "pause_game", "Пауза",      show=True, id="bind-pause"),
        Binding("h",      "log",        "История",    show=True, id="bind-log"),
    ]

    def get_default_screen(self) -> Screen:
        return PerformanceScreen(id="_default")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, classes="hidden")
        yield Footer(classes="hidden")

        yield MainMenu(    id="main-menu")
        yield NovelWindow( id="novel-window",  classes="hidden")
        yield NovelMenu(   id="novel-menu",    classes="hidden")
        yield LogMenu(     id="log-menu",      classes="hidden")
        yield PauseMenu(   id="pause-menu",    classes="hidden")
        yield SettingsMenu(id="settings-menu", classes="hidden")
        yield GalleryMenu( id="gallery-menu",  classes="hidden")



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
        elif button_id == "btn-save":             # Кнопка "Сохранить"
            pass
        elif button_id == "btn-load":             # Кнопка "Загрузить"
            pass
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

        # Quality
        elif button_id == "btn-small":            # Кнопка "маленький"
            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "error"
            self.query_one("#btn-medium", Button).variant = "default"
            self.query_one("#btn-large", Button).variant = "default"

            # Сохранение в файл настроек и обновление
            self.settings["quality"] = "50"
            self.save_settings()
            self.update_current_scene_art()
        elif button_id == "btn-medium":           # Кнопка "Средний"
            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "default"
            self.query_one("#btn-medium", Button).variant = "warning"
            self.query_one("#btn-large", Button).variant = "default"

            # Сохранение в файл настроек и обновление
            self.settings["quality"] = "150"
            self.save_settings()
            self.update_current_scene_art()
        elif button_id == "btn-large":            # Кнопка "ОГРОМНЫЙ"
            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "default"
            self.query_one("#btn-medium", Button).variant = "default"
            self.query_one("#btn-large", Button).variant = "success"

            # Сохранение в файл настроек и обновление
            self.settings["quality"] = "200"
            self.save_settings()
            self.update_current_scene_art()

        # ASCIIorANSI
        elif button_id == "btn-ANSI":             # Кнопка "ANSI"
            # Меняем стили кнопок
            self.query_one("#btn-ANSI", Button).variant = "primary"
            self.query_one("#btn-ASCII", Button).variant = "default"

            # Сохранение в файл настроек и обновляем текущую сцену
            self.settings["style"] = "ANSI"
            self.save_settings()
            self.update_current_scene_art()
        elif button_id == "btn-ASCII":            # Кнопка "ASCII"
            # Меняем стили кнопок
            self.query_one("#btn-ANSI", Button).variant = "default"
            self.query_one("#btn-ASCII", Button).variant = "primary"

            # Сохранение в файл настроек и обновляем текущую сцену
            self.settings["style"] = "ASCII"
            self.save_settings()
            self.update_current_scene_art()

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
            # Скрытие главного меню
            self.action_open_menu()
            self.clear_log()

            # Сброс всех глобальных переменных
            from script_parser import reset_globals
            reset_globals()

            # Запуск новой игры (всегда пролог)
            self.script = ScriptParser("TS/text/tmp.txt", self)

            # Отображение NovelMenu
            self.query_one("#novel-menu").remove_class("hidden")
            self.query_one("#novel-window").remove_class("hidden")

            # Фокус на кнопке "Вперёд" в игровом меню
            self.query_one("#btn-next", Button).focus()
        elif button_id == "btn-save-load":        # Кнопка "Сохранение"
            pass
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

    def on_mount(self) -> None:
        """Загрузка настроек при запуске"""
        self.load_settings()
        self.apply_settings()

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

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Обработка выбора из меню"""
        choice_label = event.item.query_one(Label)
        choice_text = str(choice_label.content).strip()

        if hasattr(self, "pending_choices") and self.pending_choices:
            block = self.pending_choices.get(choice_text)
            if block:
                # вставляем строки выбранного блока в сценарий
                self.script.lines[self.script.index:self.script.index] = block

            # очищаем pending_choices
            self.pending_choices = None

        # скрываем меню и возвращаем фон
        self.query_one("#choice-bar").add_class("hidden")
        self.query_one("#bg-cg").remove_class("hidden")

        # продолжаем сценарий
        await self._advance_script_line()

    async def key_space(self, event: events.Key) -> None:
        """Обработка пробела как перехода с фильтрацией ввода во время анимации."""
        now = getattr(event, "time", None) or _time.get_time()
        idle_for = now - self._space_last_event_at
        self._space_last_event_at = now

        if self._space_require_idle:
            if idle_for < self._space_idle_gap:
                return
            self._space_require_idle = False

        if self._is_space_event_during_animation(event):
            return
        await self.action_next_scene()


    # ============ Функции - action_ ============
    async def action_next_scene(self) -> None:
        """Переключение по bind(space)."""
        if not self.can_advance_scene():
            return
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

    def action_pause_game(self) -> None:
        """Открытие меню паузы"""
        pause_menu = self.query_one("#pause-menu")
        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")
        settings_menu = self.query_one("#settings-menu")
        main_menu = self.query_one("#main-menu")
        gallery_menu = self.query_one("#gallery-menu")
        choice_bar = self.query_one("#choice-bar")
        log_menu = self.query_one("#log-menu")
        

        if main_menu.has_class("hidden") and gallery_menu.has_class("hidden"): # Если НЕ открыто главное меню
            # Если открыто из главного меню ИЛИ НЕ скрыто окно выбора И окно истории
            if settings_menu.has_class("open-from-menu") or not (choice_bar.has_class("hidden") and log_menu.has_class("hidden")):
                pass # Пропуск

            elif settings_menu.has_class("hidden"): # Если НЕ открыто меню настроек
                # Переключение видимости элементов
                if pause_menu.has_class("hidden"):
                    # Cкрытие диологового окна, кнопок перемотки и задника
                    novel_menu.add_class("hidden")
                    novel_window.add_class("hidden")

                    # Показ меню паузы
                    pause_menu.remove_class("hidden")

                    # Фокус на первую кнопку в меню паузы
                    self.query_one("#btn-continue", Button).focus()
                else:
                    # Выключаем паузу: скрытие меню паузы
                    pause_menu.add_class("hidden")

                    # Показ диологового окна, кнопок перемотки и задника
                    novel_menu.remove_class("hidden")
                    novel_window.remove_class("hidden")

                    # Возвращаем фокус на кнопку "Вперёд" в игровом меню 
                    self.query_one("#btn-next", Button).focus()
            else:
                # Скрытие меню настроек
                settings_menu.add_class("hidden")

                # Показ диологового окна, кнопок перемотки и задника
                novel_menu.remove_class("hidden")
                novel_window.remove_class("hidden")

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
        bg_cg = self.query_one("#bg-cg")

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
                # Удаление класса-флага
                settings_menu.remove_class("open-from-pause")

                # Показ диологового окна, кнопок перемотки и задника
                novel_menu.remove_class("hidden")
                bg_cg.remove_class("hidden")

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


    # ============ Функции - прочие ============
    def generate_scene_ansi(self, category: str, scene_name: str):
        """Конвертирует JPG сцены в ANSI арт для игрового окна."""
        img_path = f"ES/{category}/{scene_name}.jpg"
        if not os.path.exists(img_path):
            img_path = f"ES/{category}/{scene_name}.png"
        if not os.path.exists(img_path):
            return Text.from_markup(f"[Файл не найден: {img_path}]")

        # Берём width прямо из настроек
        width = int(self.settings.get("quality", 150))

        try:
            img = Image.open(img_path)
            if self.settings["style"] == "ANSI":    # Если параметр ANSI
                palette = Palettes.color
            elif self.settings["style"] == "ASCII": # Если параметр ASCII
                palette = Palettes.ascii
            
            # Конвертация изображения в ANSI/ASCII 
            ansi_art = convert_img(img, width=width, alpha=True, palette=palette)
            return Text.from_ansi(ansi_art)
        except Exception as e:
            return Text.from_markup(f"[Ошибка конвертации: {e}]")
    
    def load_settings(self):
        """Загрузка настроек"""
        if os.path.exists(self.CONFIG_FILE):
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                self.settings = json.load(f)
        else:
            self.save_settings()
    
    def save_settings(self):
        """Сохранение настроек"""
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
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
        """Загружает список JPG/PNG файлов из папки ES/bg или ES/cg"""
        # Папка с изображениями
        folder = f"ES/{self.gallery_mode}"

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
        img = Image.open(f"ES/{self.gallery_mode}/{filename}")

        # gallery_size = "50" / "150" / "200"
        width = int(self.gallery_size)

        try:
            ansi_art = convert_img(img, width=width, alpha=True, palette=Palettes.color)
        except Exception as e:
            ansi_art = f"[Ошибка конвертации изображения: {e}]"

        static = self.query_one("#ansi-content", Static)
        static.update(Text.from_ansi(ansi_art))

        self.query_one(GalleryMenuMidBtns).border_title = os.path.splitext(filename)[0]

    def update_current_scene_art(self):
        """Перерисовывает текущий арт при смене качества."""
        if not hasattr(self, "current_scene") or not self.current_scene:
            return
        if not hasattr(self, "current_scene_category") or not self.current_scene_category:
            return

        ansi_art = self.generate_scene_ansi(
            self.current_scene_category, 
            self.current_scene
        )

        try:
            self.query_one("#bg-cg").update(ansi_art)
        except Exception:
            pass

    def reset_game_view(self):
        """Сбрасывает визуальное состояние игры перед выходом в меню"""
        # Получаем элементы
        text_bar = self.query_one("#text-bar", Widget)
        bg_cg = self.query_one("#bg-cg", Widget)

        # Очистка текста и имени персонажа
        text_bar.text = ""
        text_bar.border_title = ""
        text_bar.refresh()

        # Очистка ASCII-фона
        bg_cg.update("")

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
        if not self.can_advance_scene():
            return
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
        """Серийный вызов парсера без параллельных переходов."""
        if self._next_scene_in_progress:
            return
        if not hasattr(self, "script"):
            return

        self._next_scene_in_progress = True
        try:
            await self.script.next_line()
        finally:
            self._next_scene_in_progress = False

if __name__ == "__main__":
    app = TerminalSummer()
    app.run()
