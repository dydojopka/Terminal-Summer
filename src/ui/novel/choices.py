"""Сюжетные ответы и их отображение на карте лагеря."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.cells import cell_len
from textual import events
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView

from story.map_choices import map_choice_zones
from ui.novel.camp_map import CampMap

if TYPE_CHECKING:
    from story.parser import ScriptParser


class ChoiceItem(ListItem):
    def on_enter(self) -> None:
        listing = self.parent
        if isinstance(listing, ChoiceList) and listing.parent.has_class("map-mode"):
            listing.index = listing.children.index(self)


class ChoiceList(ListView):
    """Сюжетные ответы с быстрым выбором по номеру."""
    BINDINGS = [
        Binding("tab", "cycle_choice(1)", show=False),
        Binding("shift+tab", "cycle_choice(-1)", show=False),
    ]

    async def set_choices(self, options, *, on_map: bool = False, captions=None) -> None:
        """Общие колонки номеров и центрированных подписей для всего меню."""
        rows_data = [(key, key if captions is None else captions[key]) for key in options]
        number_width = len(str(len(rows_data))) + 2
        caption_width = max(
            (cell_len(line) for _, caption in rows_data for line in caption.splitlines()),
            default=0,
        )
        self.styles.width = "1fr" if on_map else caption_width + 2 * number_width
        rows = []
        for number, (key, caption) in enumerate(rows_data, start=1):
            number_label = Label(f"{number}.", classes="choice-number")
            number_label.styles.width = number_width
            row = ChoiceItem(
                number_label,
                Center(Label(caption, markup=False, classes="choice-caption")),
                name=key,
            )
            # Правое поле уравновешивает номер, чтобы центр текста не смещался.
            row.styles.padding = (0, 0 if on_map else number_width, 1, 0)
            rows.append(row)
        await self.clear()
        await self.extend(rows)

    def on_resize(self) -> None:
        if self.parent.has_class("map-mode"):
            self.call_after_refresh(self._keep_map_choice_visible)

    def _keep_map_choice_visible(self) -> None:
        item = self.highlighted_child
        if item is not None:
            item.scroll_visible(animate=False)

    def action_cycle_choice(self, direction: int) -> None:
        if self.children:
            self.index = ((self.index or 0) + direction) % len(self.children)

    def on_key(self, event: events.Key) -> None:
        if len(event.key) != 1 or event.key not in "123456789":
            return
        if not self.is_on_screen:
            return
        index = int(event.key) - 1
        if index >= len(self.children):
            return
        event.stop()
        event.prevent_default()
        self.index = index
        self.action_select_cursor()


class ChoiceBar(Widget):
    """Окно выбора"""
    def compose(self):
        yield CampMap(id="camp-map", classes="hidden mouse-passive-art")
        with Vertical(id="choice-options"):
            yield ChoiceList()

    async def set_choices(self, options, script: ScriptParser) -> None:
        zones = map_choice_zones(script.filename, tuple(
            script.lines[target.start:target.end] for target in options.values()
        ))
        on_map = bool(zones)
        self.set_class(on_map, "map-mode")
        self.query_one("#choice-options").set_class(on_map, "map-mode")
        self.query_one(CampMap).set_class(not on_map, "hidden")
        self.query_one(CampMap).set_zones(zones)
        await self.query_one(ChoiceList).set_choices(
            options, on_map=on_map,
            captions={key: script.choice_caption(key, target) for key, target in options.items()},
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if self.has_class("map-mode") and event.list_view is self.query_one(ChoiceList):
            self.query_one(CampMap).preview(event.list_view.index)

    def close(self) -> None:
        self.add_class("hidden")
        self.query_one(CampMap).set_zones(())
