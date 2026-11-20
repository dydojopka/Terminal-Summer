"""Главное меню и его виджеты."""

from pathlib import Path

from rich.text import Text
from textual.containers import HorizontalGroup, Vertical
from textual.widgets import Label, Static

from ui.widgets.ansi_view import AnsiView
from ui.widgets.console_button import ConsoleButton as Button


class MainMenu(Static):
    """Виджет главного меню"""
    BORDER_TITLE = "Главное меню"
    ENGLISH_BUTTONS = {
        "btn-start-game": "Start game", "btn-save-load": "Load game", "btn-gallery": "Gallery",
        "btn-achievements": "Achievements", "btn-settings-menu": "Settings", "btn-exit-menu": "Quit",
    }
    DESCRIPTION_IDS = ("main-start-description", "main-load-description", "main-gallery-description")

    def __init__(self, logo_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.logo_path = logo_path
        self._russian_copy = None

    def compose(self):
        with HorizontalGroup(id="main-language-bar"):
            yield Button("RU", id="btn-language-menu", tooltip="Язык / Language")
        yield MainMenuBrand(self.logo_path, classes="mouse-passive-art")
        yield MainMenuMiddleBtns()
        yield MainMenuBottomBtns()

    def sync_language_button(self, language: str) -> None:
        self.query_one("#btn-language-menu", Button).label = language.upper()

    def apply_language(self, language: str, announcements: dict[str, str]) -> None:
        buttons = {key: self.query_one(f"#{key}", Button) for key in self.ENGLISH_BUTTONS}
        labels = {key: self.query_one(f"#{key}", Label) for key in self.DESCRIPTION_IDS}
        if self._russian_copy is None:
            self._russian_copy = {
                **{key: widget.label for key, widget in buttons.items()},
                **{key: widget.content for key, widget in labels.items()},
            }
        for key, widget in buttons.items():
            widget.label = self.ENGLISH_BUTTONS[key] if language == "en" else self._russian_copy[key]
        for key, widget in labels.items():
            widget.update(announcements.get(key, self._russian_copy[key]))
        self.query_one(MainMenuMiddleBtns).border_title = announcements.get(
            "information", MainMenuMiddleBtns.BORDER_TITLE,
        )
        self.border_title = "Main menu" if language == "en" else self.BORDER_TITLE


class MainMenuBrand(AnsiView):
    """Готовый ANSI-логотип главного меню."""

    def __init__(self, logo_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.logo_path = logo_path

    def on_mount(self) -> None:
        super().on_mount()
        try:
            ansi_logo = self.logo_path.read_text(encoding="utf-8")
            self.update(Text.from_ansi(ansi_logo))
        except (OSError, UnicodeError):
            # Логотип не должен мешать запуску игры при повреждённом ассете.
            self.update(
                Text("Terminal Summer", style="bold #E3B778", justify="center")
            )


class MainMenuMiddleBtns(HorizontalGroup):
    """Виджет-контейнер для центарльных кнопок"""
    BORDER_TITLE = "Информация"

    def compose(self):
        yield MainMenuStartBtn(id="container-start-game")
        yield MainMenuLoadBtn(id="container-save-load")
        yield MainMenuGalleryBtn(id="container-gallery")

class MainMenuBottomBtns(HorizontalGroup):
    """Виджет-контейнер для нижних кнопок"""
    def compose(self):
        yield Button("Достижения", id="btn-achievements")
        yield Button("Настройки", id="btn-settings-menu")
        yield Button("Выход", id="btn-exit-menu")

class MainMenuStartBtn(Vertical):
    """Виджет для кнопки "Начать игру" с описанием"""
    def compose(self):
        yield Button("Начать игру", id="btn-start-game")
        yield Label('   Дорогой пионер!\n' \
        'Ты — на пороге удивительных открытий.\n' \
        '   Перед тобой распахнулись двери самого прекрасного места в мире — ' \
        'нашего любимого лагеря "Совёнок". Эта смена запомнится тебе на всю жизнь.\n' \
        'Добро пожаловать!', id="main-start-description")

class MainMenuLoadBtn(Vertical):
    """Виджет для кнопки "Соханение" с описанием"""
    def compose(self):
        yield Button("Сохранение", id="btn-save-load")
        yield Label('   Бережно относись к истории своего лагеря. Тщательно записывай ' \
        'свои наблюдения и мысли о прошедших днях.\nПри помощи сохранений ты всегда ' \
        'сможешь вернуться назад к пройденному эпизоду и осмыслить его заново. ' \
        'Удачи тебе в твоих начинаниях!\n' \
        '   Если что-то пойдёт не так, ты знаешь, что делать', id="main-load-description")

class MainMenuGalleryBtn(Vertical):
    """Виджет для кнопки "Галерея" с описанием"""
    def compose(self):
        yield Button("Галерея", id="btn-gallery")
        yield Label('   Здесь представлены работы участников нашего фотокружка. ' \
        'Твои товарищи всегда готовы запечатлеть важные моменты из жизни лагеря, ' \
        'а на многих снимках ты сможешь встретить и себя. Будь опрятен и своим ' \
        'поведением подавай пример окружающим.', id="main-gallery-description")
