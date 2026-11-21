"""Плоские кнопки с выделением подписи"""

from collections.abc import Iterable

from textual.binding import Binding
from textual.content import Content
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, ListView


def directional_focus_target(origin: Widget, candidates: Iterable[Widget], direction: str) -> Widget | None:
    """Ближайший сосед в заданной группе; по горизонтали — только тот же ряд."""
    horizontal = direction in {"left", "right"}
    sign = -1 if direction in {"up", "left"} else 1
    region = origin.region
    if not region:
        return None
    x, y = region.center
    nearest = None
    best_score = None
    for candidate in candidates:
        if candidate is origin or not candidate.region:
            continue
        other = candidate.region
        bx, by = other.center
        forward = sign * (bx - x if horizontal else by - y)
        if forward <= 0:
            continue
        aligned = (
            region.y < other.bottom and other.y < region.bottom
            if horizontal else
            region.x < other.right and other.x < region.right
        )
        if horizontal and not aligned:
            continue
        sideways = abs(by - y if horizontal else bx - x)
        score = (not aligned, forward, sideways)
        if best_score is None or score < best_score:
            nearest, best_score = candidate, score
    return nearest


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
        # Цепочка Textual исключает скрытые/отключённые элементы и ограничена
        # текущим экраном, включая модальные диалоги.
        nearest = directional_focus_target(
            self,
            (widget for widget in self.screen.focus_chain
             if isinstance(widget, (ConsoleButton, ListView))),
            direction,
        )
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
