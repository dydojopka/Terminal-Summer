"""Полноэкранное меню концовок"""

from functools import lru_cache
from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ListItem, ListView, Static

from endings_catalog import load_endings_catalog, runtime_ending_ansi
from endings_ansi import read_ending_ansi
from ending_progress import format_ending_date
from script_parser import get_persistent_state


@lru_cache(maxsize=128)
def load_ending_icon(path: str, mtime_ns: int, width: int) -> Text:
    """Кеширует чтение готового ассета"""
    return read_ending_ansi(Path(path), width)


class EndingsList(ListView):
    BINDINGS = [
        Binding("home", "first", show=False),
        Binding("end", "last", show=False),
    ]

    def action_first(self):
        if self.children:
            self.index = 0

    def action_last(self):
        if self.children:
            self.index = len(self.children) - 1


class EndingRow(ListItem):
    def __init__(self, ending, **kwargs):
        super().__init__(**kwargs)
        self.ending = ending
        self.unlocked = False
        self.icon_error = None
        self._icon_signature = None

    def compose(self):
        yield Static("", classes="ending-icon")
        with Horizontal(classes="ending-details"):
            yield Label(Text(self.ending.ending), classes="ending-route")
            with Vertical(classes="ending-caption"):
                yield Label(Text(self.ending.title), classes="ending-title")
                yield Label("Не открыта", classes="ending-status")
                yield Label("", classes="ending-date hidden")

    def update_progress(self, state, dates=None):
        self.unlocked = state.get(self.ending.flag) is True
        self.set_class(self.unlocked, "ending-unlocked")
        self.query_one(".ending-status", Label).update("Открыта" if self.unlocked else "Не открыта")
        date = self.query_one(".ending-date", Label)
        date.set_class(not self.unlocked, "hidden")
        date.update(format_ending_date((dates or {}).get(self.ending.flag)) if self.unlocked else "")
        self.update_icon()

    def on_resize(self):
        self.update_icon()

    def update_icon(self):
        if not self.is_mounted or self.size.width <= 0:
            return
        width = 32 if self.size.width >= 138 else 24 if self.size.width >= 72 else 16
        self.set_class(self.size.width < 72, "ending-compact")
        icon = self.query_one(".ending-icon", Static)
        icon.styles.width = width
        icon.styles.height = width // 2
        self.styles.min_height = width // 2 + 2
        try:
            path = runtime_ending_ansi(self.app.ts_path, self.ending, width, self.unlocked)
            signature = (str(path), path.stat().st_mtime_ns, width)
            if signature == self._icon_signature:
                return
            art = load_ending_icon(*signature)
            # Cached Rich Text is never shared with a mutable widget renderable.
            icon.update(art.copy())
            self._icon_signature = signature
            self.icon_error = None
        except (OSError, ValueError) as exc:
            self._icon_signature = None
            self.icon_error = str(exc)
            icon.update(Text("Нет иконки", style="dim"))


class EndingsMenu(Vertical):
    BORDER_TITLE = "Концовки"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.endings = ()
        self.catalog_error = None

    def compose(self):
        with Horizontal(id="endings-toolbar"):
            yield Button("Назад ↩", id="btn-close-endings")
            yield Label("Открыто: 0/13", id="endings-progress")
        yield Static("↑/↓ · Home/End — выбор · Колесо — прокрутка · Esc — назад", id="endings-help")
        yield Static("", id="endings-error", classes="hidden")
        yield EndingsList(id="endings-list")

    async def on_mount(self):
        try:
            self.endings = load_endings_catalog()
        except ValueError as exc:
            self.catalog_error = str(exc)
            self.query_one("#endings-error", Static).update(Text(self.catalog_error))
            self.query_one("#endings-error").remove_class("hidden")
        listing = self.query_one(EndingsList)
        await listing.extend(EndingRow(ending) for ending in self.endings)
        listing.index = 0 if self.endings else None
        self.refresh_progress()

    def refresh_progress(self):
        state = get_persistent_state()
        opened = sum(state.get(ending.flag) is True for ending in self.endings)
        self.query_one("#endings-progress", Label).update(f"Открыто: {opened}/{len(self.endings)}")
        for row in self.query(EndingRow):
            row.update_progress(state, self.app.ending_dates)

    def on_list_view_selected(self, event: ListView.Selected):
        event.stop()  # Enter/клик только выделяют строку, не запускают сценарий.

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        event.stop()


class EndingResult(ModalScreen):
    """Результат прохождения; готовый ANSI, без зависимости от старых ach/*.png."""

    BINDINGS = [
        Binding("escape", "return_to_menu", show=False, priority=True),
        # Удержанный во время титров пробел не должен закрыть результат.
        Binding("space", "ignore", show=False, priority=True),
    ]

    def __init__(self, ending, *, newly_unlocked: bool, date: str | None):
        super().__init__(id="ending-result")
        self.ending = ending
        self.newly_unlocked = newly_unlocked
        self.date = date
        self.icon_error = None
        self._sound_played = False
        self._ending_icon = Static("", id="ending-result-icon")
        self._menu_button = Button("В главное меню", id="btn-ending-menu")

    def compose(self):
        with Vertical(id="ending-result-panel"):
            yield Label("Игра окончена", id="ending-result-heading")
            with VerticalScroll(id="ending-result-content"):
                yield self._ending_icon
                yield Label(Text(self.ending.ending), id="ending-result-route")
                yield Label(Text(self.ending.title), id="ending-result-title")
                yield Label("Впервые открыта" if self.newly_unlocked else "Уже открыта",
                            id="ending-result-status")
                yield Label(format_ending_date(self.date), id="ending-result-date")
            with Horizontal(id="ending-result-actions"):
                yield self._menu_button

    def on_mount(self):
        if not self._menu_button.is_mounted:
            return
        self.update_icon()
        self._menu_button.focus()
        self.call_after_refresh(self.play_completion_sound)

    def on_resize(self):
        self.update_icon()

    def update_icon(self):
        if not self._ending_icon.is_mounted:
            return
        width = 16 if self.size.width < 60 or self.size.height < 28 else 24
        icon = self._ending_icon
        icon.styles.height = width // 2
        try:
            path = runtime_ending_ansi(self.app.ts_path, self.ending, width, True)
            icon.update(load_ending_icon(str(path), path.stat().st_mtime_ns, width).copy())
            self.icon_error = None
        except (OSError, ValueError) as exc:
            self.icon_error = str(exc)
            icon.update(Text("Нет иконки", style="dim"))

    def play_completion_sound(self):
        if self.is_mounted and self.app.screen is self and not self._sound_played:
            self._sound_played = True
            self.app.audio.execute("play sfx sfx_achievement")

    def action_ignore(self):
        pass

    def action_return_to_menu(self):
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-ending-menu":
            event.stop()
            self.action_return_to_menu()
