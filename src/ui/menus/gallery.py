"""Галерея артов и музыкальная вкладка."""

from rich.text import Text
from textual.binding import Binding
from textual.containers import HorizontalGroup, ScrollableContainer, Vertical
from textual.geometry import Size
from textual.widgets import Input, ListView, Static

from ui.menus.music_room import MusicRoom
from ui.widgets.ansi_view import AnsiView
from ui.widgets.console_button import ConsoleButton as Button, directional_focus_target


class GalleryMenu(HorizontalGroup):
    """Виджет галереи"""
    BORDER_TITLE = "Галерея"
    TAB_BUTTONS = {f"btn-gallery-{mode}": mode for mode in ("music", "cg", "bg")}
    SIZE_BUTTONS = {
        "btn-small-gallery": ("50", "error"),
        "btn-medium-gallery": ("150", "warning"),
        "btn-large-gallery": ("200", "success"),
    }
    STYLE_BUTTONS = {
        "btn-gallery-ansi": "ANSI",
        "btn-gallery-ascii": "ASCII",
        "btn-gallery-color-ascii": "COLOR_ASCII",
    }
    BUTTON_LABELS = {
        "btn-close-gallery": "Назад", "btn-gallery-music": "Музыка",
        "btn-gallery-cg": "Иллюстрации", "btn-gallery-bg": "Фоны",
        "btn-small-gallery": "маленький", "btn-medium-gallery": "Средний",
        "btn-large-gallery": "ОГРОМНЫЙ",
        "btn-gallery-ansi": "ANSI", "btn-gallery-ascii": "ЧБ ASCII",
        "btn-gallery-color-ascii": "Цветной ASCII",
    }
    BINDINGS = [
        Binding(key, f"gallery_direction('{key}')", show=False, priority=True)
        for key in ("up", "down", "left", "right")
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.strings: dict[str, str] = {}

    def compose(self):
        yield GalleryMenuLeftBtns()
        yield GalleryMenuMidBtns()
        yield GalleryMenuBottomBtns()

    def apply_language(self, strings: dict[str, str]) -> None:
        self.strings = strings
        self.border_title = strings.get("gallery.title", self.BORDER_TITLE)
        for key, label in self.BUTTON_LABELS.items():
            self.query_one(f"#{key}", Button).label = strings.get(key, label)
        self.query_one(MusicRoom).apply_language(strings)

    def update_size_selection(self, width: str) -> None:
        for key, (size, variant) in self.SIZE_BUTTONS.items():
            self.query_one(f"#{key}", Button).variant = variant if size == width else "default"

    def update_style_selection(self, style: str) -> None:
        for key, value in self.STYLE_BUTTONS.items():
            self.query_one(f"#{key}", Button).variant = "primary" if value == style else "default"

    def focus_back_button(self) -> None:
        self.query_one("#btn-close-gallery", Button).focus()

    def select_tab(self, mode: str) -> None:
        music = mode == "music"
        self.query_one("#bg-cg-gallery").set_class(music, "hidden")
        self.query_one(GalleryMenuBottomBtns).set_class(music, "hidden")
        room = self.query_one(MusicRoom)
        room.set_class(not music, "hidden")
        for key, tab in self.TAB_BUTTONS.items():
            self.query_one(f"#{key}", Button).variant = "primary" if tab == mode else "default"
        if music:
            self.set_art_title(self.query_one("#btn-gallery-music", Button).label.plain)
            room.query_one("#music-list", ListView).focus()
            room.update_player()

    def set_art_title(self, title: str) -> None:
        self.query_one(GalleryMenuMidBtns).border_title = title

    def show_art(self, art: Text) -> None:
        self.query_one("#ansi-content", AnsiView).update(art)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action != "gallery_direction":
            return super().check_action(action, parameters)
        focused = self.app.focused
        direction = parameters[0]
        if isinstance(focused, Input):
            # Редактирование текста, включая ←/→ и их модификаторы, — дело Input.
            return direction in {"up", "down"}
        if isinstance(focused, ListView):
            if direction == "up":
                return focused.index in (None, 0)
            if direction == "down":
                return not focused.children or focused.index == len(focused.children) - 1
            return True
        return isinstance(focused, Button)

    def action_gallery_direction(self, direction: str) -> None:
        """Переходы между зонами; выбор трека и редактирование остаются нативными."""
        focused = self.app.focused
        available = set(self.screen.focus_chain)
        sidebar = [button for button in self.query_one(GalleryMenuLeftBtns).query(Button)
                   if button in available]
        active_tab = self.query_one(f"#btn-gallery-{self.app.gallery_mode}", Button)
        search = self.query_one("#music-search", Input)
        listing = self.query_one("#music-list", ListView)
        music = self.app.gallery_mode == "music"
        controls = self.query_one("#music-controls" if music else "GalleryMenuBottomBtns")
        buttons = [button for button in controls.query(Button) if button in available]
        target = None
        if focused in sidebar:
            if direction in {"up", "down"}:
                index = sidebar.index(focused) + (-1 if direction == "up" else 1)
                if 0 <= index < len(sidebar):
                    target = sidebar[index]
            elif direction == "right":
                target = (
                    search if focused.id == "btn-close-gallery" else listing
                ) if music else next(iter(buttons), None)
        elif focused is search:
            target = self.query_one("#btn-close-gallery") if direction == "up" else listing
        elif focused is listing:
            if direction == "up":
                target = search
            elif direction == "left":
                target = active_tab
            else:
                target = next(iter(buttons), None)
        elif focused in buttons:
            if direction in {"left", "right"}:
                # Переходим между блоками управления, включая перенос сетки музыки.
                index = buttons.index(focused) + (-1 if direction == "left" else 1)
                if 0 <= index < len(buttons):
                    target = buttons[index]
            else:
                target = directional_focus_target(focused, buttons, direction)
            if target is None:
                if direction == "left":
                    target = active_tab
                elif direction == "up":
                    target = listing if music else active_tab
        if target is not None and target in available:
            target.focus()

class GalleryMenuLeftBtns(Vertical):
    """Виджет-контейнер для кнопок галереи сверху"""
    def on_resize(self) -> None:
        self.set_class(self.size.height < 28, "short-gallery")

    def compose(self):
        labels = GalleryMenu.BUTTON_LABELS
        yield Button(labels["btn-close-gallery"], id="btn-close-gallery")
        with Static(id="container-left-btns"):
            yield Button(labels["btn-gallery-music"], variant="default", id="btn-gallery-music")
            yield Button(labels["btn-gallery-cg"], variant="primary", id="btn-gallery-cg")
            yield Button(labels["btn-gallery-bg"], variant="default", id="btn-gallery-bg")

class GalleryMenuMidBtns(Vertical):
    """Виджет-контейнер для кнопок и арт-пространства галереи в центре"""
    BORDER_TITLE=""
    def compose(self):
        with HorizontalGroup(id="gallery-art-panel"):

            with ScrollableContainer(id="bg-cg-gallery", can_focus=False, can_focus_children=False):
                yield AnsiView("", id="ansi-content", classes="mouse-passive-art")
            yield MusicRoom(id="music-room", classes="hidden")


class GalleryOptionButton(Button):
    def watch_label(self) -> None:
        # Смена языка должна заново измерить кнопку с width: auto.
        self.refresh(layout=True)

    def get_content_width(self, container: Size, viewport: Size) -> int:
        # Подпись однострочная (nowrap), поэтому запас Textual для переноса не нужен.
        return self.label.cell_length


class GalleryMenuBottomBtns(HorizontalGroup):
    """Перелистывание, размер и формат артов галереи."""
    def compose(self):
        labels = GalleryMenu.BUTTON_LABELS
        yield Button("<-", id="btn-back-gallery")
        with HorizontalGroup(id="gallery-size-controls"):
            for key, (width, variant) in GalleryMenu.SIZE_BUTTONS.items():
                variant = variant if width == self.app.gallery_size else "default"
                yield GalleryOptionButton(labels[key], variant=variant, id=key, classes="gallery-quality")
        with HorizontalGroup(id="gallery-style-controls"):
            for key, style in GalleryMenu.STYLE_BUTTONS.items():
                variant = "primary" if style == self.app.gallery_style else "default"
                yield GalleryOptionButton(labels[key], variant=variant, id=key)
        yield Button("->", id="btn-next-gallery")
