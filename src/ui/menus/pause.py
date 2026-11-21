"""Меню паузы."""

from textual.containers import VerticalScroll
from textual.widgets import Static

from ui.widgets.console_button import ConsoleButton as Button


class PauseMenu(Static):
    """Виджет меню паузы"""

    def compose(self):
        yield PauseMenuContainer()


class PauseMenuContainer(VerticalScroll):
    """Доп контейнер для меню паузы(Для отображения title)"""
    BORDER_TITLE = "Пауза"
    ENGLISH_BUTTONS = {
        "btn-continue": "Continue", "btn-save": "Saves", "btn-settings-pause": "Settings",
        "btn-menu": "Main menu", "btn-exit-pause": "Quit",
    }

    def compose(self):
        yield Button("Продолжить", id="btn-continue")
        yield Button("Сохранения", id="btn-save")
        yield Button("Настройки", id="btn-settings-pause")
        yield Button("В главное меню", id="btn-menu")
        yield Button("Выход", id="btn-exit-pause")

    def apply_language(self, language: str) -> None:
        buttons = {key: self.query_one(f"#{key}", Button) for key in self.ENGLISH_BUTTONS}
        if not hasattr(self, "_russian_labels"):
            self._russian_labels = {key: button.label for key, button in buttons.items()}
        for key, button in buttons.items():
            button.label = self.ENGLISH_BUTTONS[key] if language == "en" else self._russian_labels[key]
