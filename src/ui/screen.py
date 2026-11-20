"""Базовый экран игры."""

from rich.style import Style
from textual import errors
from textual.screen import Screen
from textual.widget import Widget


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
