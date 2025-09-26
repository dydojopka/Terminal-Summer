import os
import json
import simpleaudio as sa
import threading
import asyncio

from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Button, Label, Footer, Header, Static, ListView, ListItem
from textual.widget import Widget
from textual.binding import Binding

from rich.text import Text

from script_parser import ScriptParser



class AudioPlayer:
    """Класс для управления аудио"""
    def __init__(self):
        self.current_playback = None
        
    def play_sound(self, file_path, loop=False):
        """Воспроизведение звука в отдельном потоке"""
        def play():
            try:
                wave_obj = sa.WaveObject.from_wave_file(file_path)
                play_obj = wave_obj.play()
                
                if loop:
                    play_obj.wait_done()
                    self.play_sound(file_path, loop=True)
                    
            except Exception as e:
                print(f"Ошибка воспроизведения звука: {e}")
        
        # Останавливаем предыдущее воспроизведение
        if self.current_playback:
            self.current_playback.stop()
            
        # Запускаем в отдельном потоке
        self.current_playback = threading.Thread(target=play, daemon=True)
        self.current_playback.start()
    
    def stop(self):
        """Остановка воспроизведения"""
        if self.current_playback:
            sa.stop_all()



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

            with ScrollableContainer(id="bg-cg-gallery"):
                yield Static("", id="ascii-content")
            
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
    BORDER_TITLE = "Размер ASCII артов"
    def compose(self):
        with Vertical():
            yield Button("маленький\n(60x20)", variant="default", id="btn-small")
            yield Button("Средний\n(150x51)", variant="default", id="btn-medium")
            yield Button("ОГРОМНЫЙ\n(300x101)", variant="default", id="btn-large")
            yield DescriptionSettingQuality()

class DescriptionSettingQuality(Widget):
    """Описание настройки Quality"""
    def render(self):
        return 'Размер ASCII артов необходимо подбирать по размеру окна консоли,\nс сильно большим размером - изображение может не поместиться.\n\nМожете так же попробовать уменьшить размер шрифта самой консоли (Обычно это Ctrl+"+" и Ctrl+"-")'


class NovelMenu(Static):
    """Виджет-контейнер для текст бара и кнопок"""
    def compose(self):
        yield Button("История", id="btn-back")
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

    async def animate_text(self, new_text, speed=0.02, append=False):
        """Анимация текста, символ за символом
        
        Если append=True → добавляет текст к текущему,
        Если append=False → начинает с нуля"""
        if not append:
            self.text = ""
            self.refresh()

        for char in new_text:
            self.text += char
            self.refresh()
            await asyncio.sleep(speed)

        self.refresh()

    def update_text(self, new_text):
        """Обновляем текст без анимации"""
        self.text = new_text
        self.refresh()

class ChoiceBar(Widget):
    """Окно выбора"""
    def compose(self):
        yield ListView(
            ListItem(Label("киси-киси")),
            ListItem(Label("мяу-мяу"))
        )


class NovelWindow(Widget):
    """Окно новеллы(bg-cg + ChoiceBar)"""
    def compose(self):
        yield ChoiceBar(id="choice-bar", classes="hidden")
        yield Static("", id="bg-cg")


class TerminalSummer(App):
    """Основное приложение новеллы"""
    CSS_PATH = "gameUI.tcss"

    CONFIG_FILE = "settings.json"

    def __init__(self):
        super().__init__()
        self.settings = {
            "header": True,
            "quality": "medium",
        }
        self.audio_player = AudioPlayer()
        self.script = ScriptParser("TS/text/day1.txt", self)

    current_scene = ""                     # Текущая сцена (имя файла без расширения)
    scenes_dir = "TS/ASCII/ASCII-large/bg" # Папка с ASCII-артами
    scene_cache = {}                       # Кэш для предзагруженных сцен

    gallery_mode = "cg"
    gallery_size = "medium" # small | medium | large
    gallery_index = 0
    gallery_images = []

    BINDINGS = [
        Binding("escape", "pause_game", "Пауза", show=True, id="bind-pause"),
        # Binding("b", "prev_scene", "Назад", show=True),
        Binding("space", "next_scene", "Продолжить", show=True, id="bind-next"),
        Binding("c", "open_ChoiceBar", "Меню выбора", show=True, id="bind-choice-bar")
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, classes="hidden")
        yield Footer(classes="hidden")
        yield MainMenu(id="main-menu")
        yield NovelWindow(id="novel-window")
        yield NovelMenu(id="novel-menu", classes="hidden")
        yield PauseMenu(id="pause-menu", classes="hidden")
        yield SettingsMenu(id="settings-menu", classes="hidden")
        yield GalleryMenu(id="gallery-menu", classes="hidden")


    # ============ Функции - on_ ============
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обработка событий при нажатии кнопок"""
        button_id = event.button.id

        # Кнопки в NovelMenu:
        if   button_id == "btn-next":             # Кнопка "Продолжить"
            await self.action_next_scene()
        # elif button_id == "btn-back":             # Кнопка "История"
        #    await self.action_prev_scene()

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
            # Изменение размера артов на small
            self.scenes_dir = "TS/ASCII/ASCII-small/bg"
            self.scene_cache = {} # Очистка кэша сцен
            self.preload_scenes() # Предзагрузка всех сцен
            self.load_scene(self.current_scene)

            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "error"
            self.query_one("#btn-medium", Button).variant = "default"
            self.query_one("#btn-large", Button).variant = "default"

            # Сохранение в файл настроек
            self.settings["quality"] = "small"
            self.save_settings()
        elif button_id == "btn-medium":           # Кнопка "Средний"
            # Изменение размера артов на medium
            self.scenes_dir = "TS/ASCII/ASCII-medium/bg"
            self.scene_cache = {} # Очистка кэша сцен
            self.preload_scenes() # Предзагрузка всех сцен
            self.load_scene(self.current_scene)
            
            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "default"
            self.query_one("#btn-medium", Button).variant = "warning"
            self.query_one("#btn-large", Button).variant = "default"

            # Сохранение в файл настроек
            self.settings["quality"] = "medium"
            self.save_settings()
        elif button_id == "btn-large":            # Кнопка "ОГРОМНЫЙ"
            # Изменение размера артов на large
            self.scenes_dir = "TS/ASCII/ASCII-large/bg"
            self.scene_cache = {} # Очистка кэша сцен
            self.preload_scenes() # Предзагрузка всех сцен
            self.load_scene(self.current_scene)

            # Меняем стили кнопок
            self.query_one("#btn-small", Button).variant = "default"
            self.query_one("#btn-medium", Button).variant = "default"
            self.query_one("#btn-large", Button).variant = "success"

            # Сохранение в файл настроек
            self.settings["quality"] = "large"
            self.save_settings()

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

            # Отображение NovelMenu
            self.query_one("#novel-menu").remove_class("hidden")
            self.query_one("#bg-cg").remove_class("hidden")

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

            self.gallery_size = "small"
            self.load_gallery_images()
            self.update_gallery_display()
        elif button_id == "btn-medium-gallery":   # Кнопка "Средний"
            # Меняем стили кнопок
            self.query_one("#btn-small-gallery", Button).variant = "default"
            self.query_one("#btn-medium-gallery", Button).variant = "warning"
            self.query_one("#btn-large-gallery", Button).variant = "default"
        
            self.gallery_size = "medium"
            self.load_gallery_images()
            self.update_gallery_display()
        elif button_id == "btn-large-gallery":    # Кнопка "ОГРОМНЫЙ"
            # Меняем стили кнопок
            self.query_one("#btn-small-gallery", Button).variant = "default"
            self.query_one("#btn-medium-gallery", Button).variant = "default"
            self.query_one("#btn-large-gallery", Button).variant = "success"

            self.gallery_size = "large"
            self.load_gallery_images()
            self.update_gallery_display()

        elif button_id == "btn-close-gallery":    # Кнопка "Назад"
            self.action_open_gallery()

    def on_mount(self) -> None:
        """Загрузка настроек при запуске"""
        self.load_settings()
        self.apply_settings()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Обработка выбора из меню"""
        choice = event.item.query_one(Label).renderable
    
        if hasattr(self, "pending_choices") and self.pending_choices:
            block = self.pending_choices.get(str(choice))
            if block:
                # вставляем строки выбранного блока в сценарий
                self.script.lines[self.script.index:self.script.index] = block
    
            # очищаем pending_choices
            self.pending_choices = None
    
        # скрываем меню и возвращаем фон
        self.query_one("#choice-bar").add_class("hidden")
        self.query_one("#bg-cg").remove_class("hidden")
    
        # продолжаем сценарий
        await self.script.next_line()


    # ============ Функции - action_ ============
    # async def action_prev_scene(self) -> None:
    #     """Переключение на предыдущую сцену"""
    #     if not self.query_one("#novel-menu").has_class("hidden"): # Если NovelMenu НЕ скрыт
    #         await self.script.prev_line() # Парсинг предыдущей строки через script_parser

    async def action_next_scene(self) -> None:
        """Переключение на следующую строку (асинхронно)"""
        if not self.query_one("#novel-menu").has_class("hidden"): # Если NovelMenu НЕ скрыт
            await self.script.next_line()  # Асинхронный вызов парсинга след. строки
            # попробовать добавить переключение флага прямо здесь чтобы избежать бага с работой space

    def action_open_ChoiceBar(self) -> None:
        """Откытие меню выбора"""
        choice_bar = self.query_one("#choice-bar")

        if choice_bar.has_class("hidden"):
            self.query_one("#bg-cg").add_class("hidden")

            choice_bar.remove_class("hidden")
        else:
            choice_bar.add_class("hidden")

            self.query_one("#bg-cg").remove_class("hidden")

    def action_pause_game(self) -> None:
        """Открытие меню паузы"""
        pause_menu = self.query_one("#pause-menu")
        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")
        settings_menu = self.query_one("#settings-menu")
        main_menu = self.query_one("#main-menu")
        gallery_menu = self.query_one("#gallery-menu")

        if main_menu.has_class("hidden") and gallery_menu.has_class("hidden"): # Если НЕ открыто главное меню
            if settings_menu.has_class("open-from-menu"):
                pass

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
            self.gallery_size = "medium"
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

    # def action_toggle_dark(self) -> None:
    #     """Смена тёмного/светлого режима"""
    #     self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"


    # ============ Функции - прочие ============
    def preload_scenes(self):
        """Предзагрузка всех сцен в кэш"""
        try:
            files = [f for f in os.listdir(self.scenes_dir) if f.endswith(".txt")]
            for file in files:
                scene_name = file[:-4]
                with open(os.path.join(self.scenes_dir, file), "r", encoding="utf-8") as f:
                    self.scene_cache[scene_name] = f.read()
        except FileNotFoundError:
            self.scene_cache = {}

    def load_scene(self, scene_name: str) -> None:
        """Загрузка ASCII-арт из кэша"""
        art_content = self.scene_cache.get(scene_name, f"Scene not found: {scene_name}")
        
        # Обновление виджета с артом
        bg_cg = self.query_one("#bg-cg", Static)
        bg_cg.update(art_content)
        
        # Обновление текущей сцены
        self.current_scene = scene_name

    def get_scene_list(self) -> list:
        """Получение списка доступных сцен"""
        try:
            files = [f[:-4] for f in os.listdir(self.scenes_dir) 
                     if f.endswith(".txt")]
            return sorted(files)
        except FileNotFoundError:
            return []

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
        if quality == "small":
            self.scenes_dir = "TS/ASCII/ASCII-small/bg"
            self.query_one("#btn-small", Button).variant = "error"
        elif quality == "medium":
            self.scenes_dir = "TS/ASCII/ASCII-medium/bg"
            self.query_one("#btn-medium", Button).variant = "warning"
        elif quality == "large":
            self.scenes_dir = "TS/ASCII/ASCII-large/bg"
            self.query_one("#btn-large", Button).variant = "success"

        self.scene_cache = {}
        self.preload_scenes()
        self.load_scene(self.current_scene)

    def load_gallery_images(self):
        """Загружает список файлов из директории по текущим настройкам"""
        folder = f"TS/ASCII/ASCII-{self.gallery_size}/{self.gallery_mode}"
        previous_filename = (
            self.gallery_images[self.gallery_index]
            if self.gallery_images and 0 <= self.gallery_index < len(self.gallery_images)
            else None
        )

        if os.path.exists(folder):
            self.gallery_images = sorted([
                f for f in os.listdir(folder)
                if f.endswith(".txt")
            ])
        else:
            self.gallery_images = []

        # Сохраняем индекс, если арт с тем же именем существует
        if previous_filename in self.gallery_images:
            self.gallery_index = self.gallery_images.index(previous_filename)
        else:
            self.gallery_index = 0

    def update_gallery_display(self):
        """Обновляет ascii-арт и заголовок"""
        if not self.gallery_images:
            self.query_one("#bg-cg-gallery", Static).update("[Ничего не найдено]")
            self.query_one(GalleryMenuMidBtns).border_title = "Пусто"
            return
    
        filename = self.gallery_images[self.gallery_index]
        path = f"TS/ASCII/ASCII-{self.gallery_size}/{self.gallery_mode}/{filename}"
        try:
            with open(path, "r", encoding="utf-8") as f:
                ascii_art = f.read()
        except Exception as e:
            ascii_art = f"[Ошибка загрузки: {e}]"
    
        self.query_one("#ascii-content", Static).update(ascii_art)
        self.query_one(GalleryMenuMidBtns).border_title = f'{os.path.splitext(filename)[0]} '


if __name__ == "__main__":
    app = TerminalSummer()
    app.run()