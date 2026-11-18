"""Плоские кнопки с выделением подписи"""

from textual.content import Content
from textual.reactive import reactive
from textual.widgets import Button


class ConsoleButton(Button):
    selected = reactive(False, toggle_class="-selected")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active_effect_duration = 0

    def on_mount(self) -> None:
        # Textual может не перерисовывать эти состояния, если CSS не изменился
        for attribute in ("has_focus", "mouse_hover"):
            self.watch(self, attribute, self.refresh, init=False)

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
