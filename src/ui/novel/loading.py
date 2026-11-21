"""Индикатор подготовки ресурсов сценария."""

import time

from rich.text import Text
from textual.widgets import Label, LoadingIndicator, Static


class ConsoleLoadingIndicator(LoadingIndicator):
    """Символьный спиннер без градиента."""

    FRAMES = "|/—\\"

    def render(self) -> Text:
        if self.app.animation_level == "none":
            return Text("[ * ]")
        frame = int(time.monotonic() * 6) % len(self.FRAMES)
        return Text(f"[ {self.FRAMES[frame]} ]")


class ScriptLoadingOverlay(Static):
    """Оверлей подготовки ресурсов сценария."""

    def compose(self):
        yield ConsoleLoadingIndicator(id="script-loading-indicator")
        yield Label("Подготовка сценария…", id="script-loading-text")
