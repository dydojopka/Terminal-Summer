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
        self.update(
            f"Увеличьте окно терминала минимум до {minimum.width} столбцов × "
            f"{minimum.height} строк.\n"
            f"Сейчас: {size.width} × {size.height}.\n"
            "Разверните окно или уменьшите размер шрифта терминала."
        )
