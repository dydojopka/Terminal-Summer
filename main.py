import os

from textual.app import App, ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Label, Footer, Header, Static
from textual.widget import Widget

class PauseMenuContainer(VerticalScroll):
    """Доп контейнер для меню паузы(Для отопражения title)"""
    BORDER_TITLE="Пауза"

    def compose(self):
        yield Button("Продолжить", id="btn-continue")
        yield Button("Сохранить", id="btn-save")
        yield Button("Загрузить", id="btn-load")
        yield Button("Настройки", id="btn-settings")
        yield Button("В главное меню", id="btn-menu")
    
class PauseMenu(Static):
    """Виджет-контейнер для меню паузы"""
    def compose(self):
        yield PauseMenuContainer()


class NovelMenu(Static):
    """Виджет-контейнер для текст бара и кнопок"""
    def compose(self):
        yield Button("Назад", id="btn-back")
        yield TextBar(id="text-bar")
        yield Button("Вперёд", id="btn-next")

class TextBar(Widget):
    """Виджет текст бара"""
    BORDER_TITLE = "Райан гослинг"   # Имя персонажа

    def render(self):
        return "Ты пойдёшь со мной?" # Текст
    

class TerminalSummer(App):
    """Основное приложение новеллы"""
    CSS_PATH = "gameUI.tcss"

    current_scene = "_test_hight"    # Текущая сцена (имя файла без расширения)
    scenes_dir = "TS/Large/ASCII-bg" # Папка с ASCII-артами
    scene_cache = {}                 # Кэш для предзагруженных сцен

    BINDINGS = [
        #("space", "next_scene", "Далее"),
        ("escape", "pause_game", "Пауза"),
        ("b", "prev_scene", "Назад"),
        ("n", "next_scene", "Вперёд"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, classes="hidden")
        yield Footer()
        with Vertical(id="novel-mode"):
            yield Static("", id="bg-cg", classes="ascii-art")
            yield NovelMenu(id="novel-menu")
            yield PauseMenu(id="pause-menu", classes="hidden")
            #yield SettingsMenu(id="settings-menu", classes="hidden")
            #yield MainMenu(id="main-menu", classes="hidden")


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
        self.sub_title = f"Scene: {scene_name}"

    def get_scene_list(self) -> list:
        """Получение списка доступных сцен"""
        try:
            files = [f[:-4] for f in os.listdir(self.scenes_dir) 
                     if f.endswith(".txt")]
            return sorted(files)
        except FileNotFoundError:
            return []


    # ============ Функции - on_ ============
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обработка событий при нажатии кнопки"""
        button_id = event.button.id

        if button_id == "btn-next": # Кнопка "Вперёд"
            self.action_next_scene()
        elif button_id == "btn-back": # Кнопка "Назад"
            self.action_prev_scene()
        elif button_id == "btn-continue": # Кнопка "Продолжить"
            self.action_pause_game()

    def on_mount(self) -> None:
        """Действия при запуске приложения"""
        self.preload_scenes()  # Предзагрузка всех сцен
        self.load_scene(self.current_scene)


    # ============ Функции - бинды ============
    def action_prev_scene(self) -> None:
        """Переключение на предыдущую сцену"""
        scenes = self.get_scene_list()
        if scenes:
            current_index = scenes.index(self.current_scene)
            new_index = max(0, current_index - 1)
            self.load_scene(scenes[new_index])

    def action_next_scene(self) -> None:
        """Переключение на следующую сцену"""
        scenes = self.get_scene_list()
        if scenes:
            current_index = scenes.index(self.current_scene)
            new_index = min(len(scenes) - 1, current_index + 1)
            self.load_scene(scenes[new_index])

    def action_pause_game(self) -> None:
        """Открытие меню паузы"""
        pause_menu = self.query_one("#pause-menu")
        novel_menu = self.query_one("#novel-menu")
        bg_cg = self.query_one("#bg-cg")
        #settings_menu = self.query_one("#setting-menu")
        #main_menu = self.query_one("#main-menu")

        # Переключение видимости элементов
        if pause_menu.has_class("hidden"):
            # Включаем паузу: скрытие диологового окна, кнопок перемотки и задника
            novel_menu.add_class("hidden")
            bg_cg.add_class("hidden")

            # Показ меню паузы
            pause_menu.remove_class("hidden")
        else:
            # Выключаем паузу: скрытие меню паузы
            pause_menu.add_class("hidden")

            # Показ диологового окна, кнопок перемотки и задника
            novel_menu.remove_class("hidden")
            bg_cg.remove_class("hidden")



    # def action_toggle_dark(self) -> None:
    #     """Смена тёмного/светлого режима"""
    #     self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"


if __name__ == "__main__":
    app = TerminalSummer()
    app.run()