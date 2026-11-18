"""Плоские кнопки с выделением подписи"""

from textual.binding import Binding
from textual.content import Content
from textual.reactive import reactive
from textual.widgets import Button, ListView


class ConsoleButton(Button):
    BINDINGS = [
        Binding(key, f"focus_direction('{key}')", show=False)
        for key in ("up", "down", "left", "right")
    ]

    selected = reactive(False, toggle_class="-selected")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active_effect_duration = 0

    def on_mount(self) -> None:
        # Textual может не перерисовывать эти состояния, если CSS не изменился
        for attribute in ("has_focus", "mouse_hover"):
            self.watch(self, attribute, self.refresh, init=False)

    def action_focus_direction(self, direction: str) -> None:
        """Выбирает соседнюю кнопку/список, не прокручивая контейнер."""
        horizontal = direction in {"left", "right"}
        sign = -1 if direction in {"up", "left"} else 1
        origin = self.region
        if not origin:
            return
        x, y = origin.center
        nearest = None
        best_score = None
        # Цепочка Textual исключает скрытые/отключённые элементы и ограничена
        # текущим экраном, включая модальные диалоги.
        for button in self.screen.focus_chain:
            if not isinstance(button, (ConsoleButton, ListView)) or button is self:
                continue
            region = button.region
            if not region:
                continue
            bx, by = region.center
            forward = sign * (bx - x if horizontal else by - y)
            if forward <= 0:
                continue
            aligned = (
                origin.y < region.bottom and region.y < origin.bottom
                if horizontal else
                origin.x < region.right and region.x < origin.right
            )
            # На краю ряда ←/→ не должны искать кнопку по диагонали.
            if horizontal and not aligned:
                continue
            sideways = abs(by - y if horizontal else bx - x)
            # Сначала тот же ряд/столбец, затем ближайший сосед по направлению.
            score = (not aligned, forward, sideways)
            if best_score is None or score < best_score:
                nearest, best_score = button, score
        if nearest is not None:
            nearest.focus()

    def render(self) -> Content:
        label = self.label
        if self.disabled:
            return label.stylize("#858278")
        if self.has_class("danger"):
            label = label.stylize("bold #ce8578")
        elif self.selected or self.variant != "default":
            label = label.stylize("bold #e3b778")
        elif self.mouse_hover:
            label = label.stylize("bold #f3f0df")
        if self.has_focus:
            label = label.stylize("bold reverse")
        return label
