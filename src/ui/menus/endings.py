"""Полноэкранное меню концовок"""

from functools import lru_cache
from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from endings.ansi import read_ending_ansi
from endings.catalog import load_endings_catalog, runtime_ending_ansi
from story.parser import get_persistent_state
from storage.progress import format_ending_date
from ui.widgets.console_button import ConsoleButton as Button


def ending_labels(ending, strings: dict[str, str]) -> tuple[Text, Text]:
    return (
        Text(strings.get(f"route.{ending.id}", ending.ending)),
        Text(strings.get(f"title.{ending.id}", ending.title)),
    )


@lru_cache(maxsize=128)
def load_ending_icon(path: str, mtime_ns: int, width: int) -> Text:
    """Кеширует чтение готового ассета"""
    return read_ending_ansi(Path(path), width)


class EndingsList(ListView):
    BINDINGS = [
        Binding("home", "first", show=False),
        Binding("end", "last", show=False),
    ]

    def action_cursor_up(self) -> None:
        if self.index is None or self.index == 0:
            self.screen.query_one("#btn-close-endings", Button).focus()
        else:
            super().action_cursor_up()

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
        self.strings: dict[str, str] = {}

    def compose(self):
        yield Static("", classes="ending-icon")
        with Horizontal(classes="ending-details"):
            yield Label(Text(self.ending.ending), classes="ending-route")
            with Vertical(classes="ending-caption"):
                yield Label(Text(self.ending.title), classes="ending-title")
                yield Label("Не открыта", classes="ending-status")
                yield Label("", classes="ending-date hidden")

    def update_progress(self, state, dates=None, strings=None):
        self.strings = strings or {}
        self.unlocked = state.get(self.ending.flag) is True
        self.set_class(self.unlocked, "ending-unlocked")
        route, title = ending_labels(self.ending, self.strings)
        self.query_one(".ending-route", Label).update(route)
        self.query_one(".ending-title", Label).update(title)
        status = (self.strings.get("status.unlocked", "Открыта") if self.unlocked
                  else self.strings.get("status.locked", "Не открыта"))
        self.query_one(".ending-status", Label).update(status)
        date = self.query_one(".ending-date", Label)
        date.set_class(not self.unlocked, "hidden")
        date.update(format_ending_date((dates or {}).get(self.ending.flag), self.strings)
                    if self.unlocked else "")
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
            icon.update(Text(self.strings.get("icon.missing", "Нет иконки"), style="dim"))


class EndingsMenu(Vertical):
    BORDER_TITLE = "Концовки"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.endings = ()
        self.catalog_error = None
        self.strings: dict[str, str] = {}

    def compose(self):
        with Horizontal(id="endings-toolbar"):
            yield Button("Назад", id="btn-close-endings")
            yield Label("Открыто: 0/13", id="endings-progress")
        yield Static("", id="endings-error", classes="hidden")
        yield EndingsList(id="endings-list")

    async def on_mount(self):
        try:
            self.endings = load_endings_catalog()
        except ValueError as exc:
            self.catalog_error = str(exc)
            self.update_catalog_error()
            self.query_one("#endings-error").remove_class("hidden")
        listing = self.query_one(EndingsList)
        await listing.extend(EndingRow(ending) for ending in self.endings)
        listing.index = 0 if self.endings else None
        self.refresh_progress()

    def apply_language(self, strings: dict[str, str]) -> None:
        self.strings = strings
        self.border_title = strings.get("menu.title", self.BORDER_TITLE)
        self.query_one("#btn-close-endings", Button).label = strings.get("menu.back", "Назад")
        if self.catalog_error is not None:
            self.update_catalog_error()
        self.refresh_progress()

    def update_catalog_error(self) -> None:
        self.query_one("#endings-error", Static).update(
            Text(self.strings.get("menu.error", self.catalog_error))
        )

    def refresh_progress(self):
        state = get_persistent_state()
        opened = sum(state.get(ending.flag) is True for ending in self.endings)
        progress = self.strings.get("menu.progress", "Открыто: {opened}/{total}")
        self.query_one("#endings-progress", Label).update(
            progress.replace("{opened}", str(opened)).replace("{total}", str(len(self.endings)))
        )
        for row in self.query(EndingRow):
            row.update_progress(state, self.app.ending_dates, self.strings)

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

    def __init__(self, ending, *, newly_unlocked: bool, date: str | None,
                 strings: dict[str, str] | None = None):
        super().__init__(id="ending-result")
        self.ending = ending
        self.newly_unlocked = newly_unlocked
        self.date = date
        self.strings = strings or {}
        self.icon_error = None
        self._sound_played = False
        self._ending_icon = Static("", id="ending-result-icon")
        self._menu_button = Button(self.strings.get("result.back", "В главное меню"), id="btn-ending-menu")

    def compose(self):
        route, title = ending_labels(self.ending, self.strings)
        status = (self.strings.get("status.new", "Впервые открыта") if self.newly_unlocked
                  else self.strings.get("status.previously_unlocked", "Уже открыта"))
        with Vertical(id="ending-result-panel"):
            yield Label(self.strings.get("result.heading", "Игра окончена"), id="ending-result-heading")
            with VerticalScroll(id="ending-result-content"):
                yield self._ending_icon
                yield Label(route, id="ending-result-route")
                yield Label(title, id="ending-result-title")
                yield Label(status, id="ending-result-status")
                yield Label(format_ending_date(self.date, self.strings), id="ending-result-date")
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
            icon.update(Text(self.strings.get("icon.missing", "Нет иконки"), style="dim"))

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
