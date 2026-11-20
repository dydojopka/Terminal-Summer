"""Неинтерактивное отображение ANSI-арта."""

from textual import events
from textual.widgets import Static


class AnsiView(Static):
    can_focus = False
    can_focus_children = False
    ALLOW_SELECT = False

    def on_mount(self) -> None:
        # ANSI-арт не интерактивен: отключаем лишнюю обработку мыши и ссылок
        self.auto_links = False
        self.disable_messages(events.MouseMove, events.Enter, events.Leave)
