"""Минимальная геометрия интерфейса в терминальных ячейках, не пикселях."""

from textual.geometry import Size
from textual.widgets import Static


# Маленький арт: 50×14 (ANSI) или 50×15 (ASCII). По высоте нужны ещё
# 6 строк диалога, по одной для Header, Footer и отступа. В 80 колонок
# помещаются арт и читаемая текстовая панель с компактными кнопками.
# Размеры прокручиваемых меню не задают минимум игрового окна.
MINIMUM_TERMINAL_SIZE = Size(80, 24)


class TerminalSizeWarning(Static):
    """Единственное видимое содержимое экрана при недостатке ячеек."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self):
        super().__init__("", markup=False)

    def on_mount(self) -> None:
        self.update_size(self.app.size)

    def update_size(self, size: Size) -> None:
        minimum = MINIMUM_TERMINAL_SIZE
        strings = getattr(self.app, "runtime_ui", {})
        minimum_text = strings.get("terminal.minimum",
                                   "Увеличьте окно терминала минимум до {width} столбцов × {height} строк.")
        current_text = strings.get("terminal.current", "Сейчас: {width} × {height}.")
        hint = strings.get("terminal.hint", "Разверните окно или уменьшите размер шрифта терминала.")
        self.update("\n".join(
            template.replace("{width}", str(dimensions.width)).replace("{height}", str(dimensions.height))
            for template, dimensions in ((minimum_text, minimum), (current_text, size), (hint, size))
        ))
