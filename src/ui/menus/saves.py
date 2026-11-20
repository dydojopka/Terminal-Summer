"""Меню слотов сохранений и диалог несовместимого сохранения."""

from rich.errors import MarkupError
from rich.text import Text
from textual.binding import Binding
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from storage.saves import CORRUPT_SAVE
from ui.widgets.console_button import ConsoleButton as Button


def plain_save_text(value: str) -> str:
    """Читаемое превью без активной разметки; повреждённые теги — литералы."""
    try:
        return Text.from_markup(value).plain
    except MarkupError:
        return value


class SaveMenuLeftBtns(VerticalScroll):
    """Виджет-контейнер для кнопок сохранений слева (Назад + номера страниц)"""
    def compose(self):
        yield Button("Назад", id="btn-close-save-menu")
        with Static(id="container-save-page-btns"):
            for i in range(1, 10):
                yield Button(str(i), id=f"btn-save-page-{i}", classes="save-page-btn")


class SaveMenuMidBtns(Vertical):
    """Виджет-контейнер для слотов и кнопок действий в центре"""
    BORDER_TITLE = "Сохранения"
    def compose(self):
        with VerticalScroll(id="save-slots-scroll"):
            yield SaveMenuSlots(id="save-menu-slots")
        yield SaveMenuActionBtns(id="save-action-btns")


class SaveMenuSlots(Static):
    """Сетка из 12 слотов сохранения"""
    def compose(self):
        for row in range(3):
            with HorizontalGroup(id=f"save-row-{row}"):
                for col in range(4):
                    slot_index = row * 4 + col
                    yield Button(
                        f"Пусто\nСлот {slot_index + 1}",
                        id=f"save-slot-{slot_index}",
                        classes="save-slot save-slot-empty",
                    )


class SaveMenuActionBtns(HorizontalGroup):
    """Кнопки действий: Удалить, Загрузить, Сохранить"""
    def compose(self):
        yield Button("Удалить", id="btn-save-delete", classes="save-action-btn")
        yield Button("Загрузить", id="btn-save-load-game", classes="save-action-btn")
        yield Button("Сохранить", id="btn-save-save", classes="save-action-btn")


class SaveMenu(HorizontalGroup):
    """Меню сохранений с пагинацией и слотами"""
    BORDER_TITLE = "Сохранения"
    BUTTONS = {"btn-close-save-menu": "Назад", "btn-save-delete": "Удалить",
               "btn-save-load-game": "Загрузить", "btn-save-save": "Сохранить"}

    def __init__(self, *args, opened_from: str = "menu", **kwargs):
        super().__init__(*args, **kwargs)
        self.opened_from = opened_from  # "menu" или "pause"
        self.current_page = 0  # 0-8 (страницы 1-9)
        self.selected_slot: str | None = None  # id выбранного слота
        self.all_saves: dict[str, dict] = {}
        self.strings: dict[str, str] = {}

    def compose(self):
        yield SaveMenuLeftBtns()
        yield SaveMenuMidBtns()

    def apply_language(self, strings: dict[str, str]) -> None:
        self.strings = strings
        for key, label in self.BUTTONS.items():
            self.query_one(f"#{key}", Button).label = strings.get(key, label)
        self.update_titles()

    def update_titles(self) -> None:
        title = self.strings.get("title", self.BORDER_TITLE)
        if self.opened_from == "menu":
            title = self.strings.get("load.title", title)
        self.border_title = title
        self.query_one(SaveMenuMidBtns).border_title = title

    def update_slots(self) -> None:
        """Обновление отображения слотов на текущей странице"""
        page = self.current_page
        all_saves = self.all_saves
        strings = self.strings
        empty = strings.get("slot.empty", "Пусто")
        corrupt = strings.get("slot.corrupt", CORRUPT_SAVE)

        for slot_index in range(12):
            save_id = f"{page}/{slot_index}"
            btn_id = f"save-slot-{slot_index}"

            try:
                btn = self.query_one(f"#{btn_id}", Button)
            except Exception:
                continue

            save_data = all_saves.get(save_id)
            if save_data:
                save_data = save_data if isinstance(save_data, dict) else {"error": CORRUPT_SAVE}
                game_state = save_data.get("game_state", {})
                game_state = game_state if isinstance(game_state, dict) else {}
                dialogue = game_state.get("dialogue", {})
                dialogue = dialogue if isinstance(dialogue, dict) else {}
                speaker = dialogue.get("speaker", "")
                speaker = speaker if isinstance(speaker, str) else ""
                text = dialogue.get("text", "")
                text = text if isinstance(text, str) else corrupt
                error = save_data.get("error")
                if error is not None:
                    text = error if isinstance(error, str) and error != CORRUPT_SAVE else corrupt
                speaker, text = plain_save_text(speaker), plain_save_text(text)
                timestamp = save_data.get("timestamp", "")
                timestamp = timestamp if isinstance(timestamp, str) else ""

                # Превью не исполняет разметку из внешнего JSON.
                words = text.split()
                if len(words) > 6:
                    short_text = " ".join(words[:6]) + "..."
                else:
                    short_text = text

                # Формируем метку слота
                if speaker and short_text:
                    label = f"{speaker}: {short_text}"
                elif short_text:
                    label = short_text
                else:
                    label = empty

                btn.label = Text(f"{label}\n{timestamp}")
                btn.remove_class("save-slot-empty")
                btn.add_class("save-slot-filled")
            else:
                number = strings.get("slot.number", "Слот {number}").replace("{number}", str(slot_index + 1))
                btn.label = f"{empty}\n{number}"
                btn.remove_class("save-slot-filled")
                btn.add_class("save-slot-empty")

            # Сброс выделения
            btn.selected = False
            btn.remove_class("save-slot-selected")

        # Выделение выбранного слота
        if self.selected_slot:
            try:
                selected_btn = self.query_one(f"#{self.selected_slot}", Button)
                selected_btn.selected = True
                selected_btn.add_class("save-slot-selected")
            except Exception:
                pass

    def select_page(self, page: int) -> None:
        """Переключение страницы сохранений"""
        self.current_page = page
        self.selected_slot = None
        self.update_slots()

        self.update_page_selection()

    def update_page_selection(self) -> None:
        for i in range(1, 10):
            self.query_one(f"#btn-save-page-{i}", Button).variant = (
                "primary" if i - 1 == self.current_page else "default"
            )

    def select_slot(self, slot_id: str) -> None:
        """Выбор слота сохранения"""

        # Сброс предыдущего выделения
        if self.selected_slot:
            try:
                old_btn = self.query_one(f"#{self.selected_slot}", Button)
                old_btn.selected = False
                old_btn.remove_class("save-slot-selected")
            except Exception:
                pass

        self.selected_slot = slot_id

        # Новое выделение
        try:
            new_btn = self.query_one(f"#{slot_id}", Button)
            new_btn.selected = True
            new_btn.add_class("save-slot-selected")
        except Exception:
            pass

    def handle_selection(self, button_id: str) -> bool:
        if button_id.startswith("btn-save-page-"):
            self.select_page(int(button_id.rsplit("-", 1)[1]) - 1)
        elif button_id.startswith("save-slot-"):
            self.select_slot(button_id)
        else:
            return False
        return True

    def prepare(self, opened_from: str) -> None:
        self.opened_from = opened_from
        self.update_titles()
        self.current_page = 0
        self.selected_slot = None

    def show(self) -> None:
        self.remove_class("hidden")
        self.query_one("#btn-save-save", Button).disabled = self.opened_from != "pause"
        self.update_slots()
        self.update_page_selection()
        self.query_one("#btn-close-save-menu", Button).focus()


class OutdatedSaveDialog(ModalScreen):
    BINDINGS = [Binding("escape", "keep", show=False)]

    def __init__(self, *, strings: dict[str, str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.strings = strings or {}
        self.keep_button = Button(self.strings.get("outdated.keep", "Оставить"),
                                  id="outdated-save-keep", variant="primary")

    def compose(self):
        with Vertical(id="outdated-save-panel"):
            yield Label(self.strings.get("outdated.title", "Сохранение устарело"), id="outdated-save-title")
            yield Static(self.strings.get("outdated.message",
                                         "Оно несовместимо с текущей версией сценария.\nУдалить выбранное сохранение?"))
            with HorizontalGroup():
                yield self.keep_button
                yield Button(self.strings.get("btn-save-delete", "Удалить"),
                             id="outdated-save-delete", variant="error", classes="danger")

    def on_mount(self):
        if self.keep_button.is_mounted:
            self.keep_button.focus()

    def action_keep(self):
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss(event.button.id == "outdated-save-delete")
