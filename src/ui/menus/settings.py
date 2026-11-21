"""Настройки игры и диалог выбора языка."""

from collections.abc import Mapping

from textual import events
from textual.binding import Binding
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from ui.widgets.console_button import ConsoleButton as Button


LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}


class LanguageDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, active: str):
        super().__init__()
        self.active = active

    def compose(self):
        with Vertical(id="language-panel"):
            yield Label("Язык / Language", id="language-dialog-title")
            with HorizontalGroup():
                for code, name in LANGUAGE_NAMES.items():
                    yield Button(name, id=f"quick-language-{code}",
                                 variant="success" if code == self.active else "default")
                yield Button("×", id="quick-language-cancel", tooltip="Отмена / Cancel")

    def on_mount(self) -> None:
        self.query_one(f"#quick-language-{self.active}", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        code = (event.button.id or "").removeprefix("quick-language-")
        self.dismiss(code if code in LANGUAGE_NAMES else None)


class SettingsMenu(VerticalScroll):
    """Виджет меню настроек"""
    BORDER_TITLE = "Настройки"
    PANEL_IDS = ("settings-menu", "setting-language", "setting-header", "setting-quality",
                 "setting-art-style", "setting-scene-filters", "setting-text-speed", "setting-audio")
    BUTTON_IDS = ("btn-header-on", "btn-header-off", "btn-header-lp-points", "btn-header-flags",
                  "btn-small", "btn-medium", "btn-large", "btn-ASCII", "btn-COLOR-ASCII",
                  "btn-scene-filters-on", "btn-scene-filters-off", "btn-speed-slow",
                  "btn-speed-medium", "btn-speed-fast", "btn-speed-instantly", "btn-audio-mute",
                  "btn-close-settings")
    COPY_IDS = ("setting-language-description", "header-content-label", "setting-header-description",
                "setting-quality-description", "setting-art-style-description",
                "setting-scene-filters-description", "setting-text-speed-description",
                "audio-master-title", "audio-music-title", "audio-environment-title", "audio-effects-title")
    QUALITY_BUTTONS = {
        "btn-small": ("50", "error"),
        "btn-medium": ("150", "warning"),
        "btn-large": ("200", "success"),
    }
    SPEED_BUTTONS = {
        "btn-speed-slow": ("0.04", "error"),
        "btn-speed-medium": ("0.025", "warning"),
        "btn-speed-fast": ("0.01", "success"),
        "btn-speed-instantly": ("0", "primary"),
    }
    HEADER_FILTER_BUTTONS = {
        "btn-header-lp-points": "header_lp_points",
        "btn-header-flags": "header_flags",
    }

    def compose(self):
        yield SettingLanguage(id="setting-language", classes="setting-with-description hidden")
        yield SettingHeader(id="setting-header", classes="setting-with-description")
        yield SettingQuality(id="setting-quality", classes="setting-with-description")
        yield SettingASCIIorANSI(id="setting-art-style", classes="setting-with-description")
        yield SettingSceneFilters(id="setting-scene-filters", classes="setting-with-description")
        yield SettingTextSpeed(id="setting-text-speed", classes="setting-with-description")
        yield SettingAudio(id="setting-audio")
        yield Button("Назад", id="btn-close-settings")

    def apply_language(self, strings: dict[str, str]) -> None:
        panels = {key: self if key == self.id else self.query_one(f"#{key}") for key in self.PANEL_IDS}
        buttons = {key: self.query_one(f"#{key}", Button) for key in self.BUTTON_IDS}
        copy = {key: self.query_one(f"#{key}", Static) for key in self.COPY_IDS}
        if not hasattr(self, "_russian_copy"):
            self._russian_copy = {
                **{key: panel.border_title for key, panel in panels.items()},
                **{key: button.label for key, button in buttons.items()},
                **{key: widget.content for key, widget in copy.items()},
            }
        for key, panel in panels.items():
            panel.border_title = strings.get(key, self._russian_copy[key])
        for key, button in buttons.items():
            button.label = strings.get(key, self._russian_copy[key])
        for key, widget in copy.items():
            widget.update(strings.get(key, self._russian_copy[key]))

    def setting_change(
        self, button_id: str, settings: Mapping[str, str | float | bool],
    ) -> tuple[str, str | float | bool] | None:
        """Переводит нажатие в новое значение; применяет его приложение."""
        if button_id in ("btn-language-ru", "btn-language-en"):
            if self.has_class("open-from-menu"):
                return "language", button_id.rsplit("-", 1)[1]
        elif button_id in ("btn-header-on", "btn-header-off"):
            return "header", button_id == "btn-header-on"
        elif button_id in self.HEADER_FILTER_BUTTONS:
            key = self.HEADER_FILTER_BUTTONS[button_id]
            return key, not settings.get(key, True)
        elif button_id in self.QUALITY_BUTTONS:
            return "quality", self.QUALITY_BUTTONS[button_id][0]
        elif button_id in SettingASCIIorANSI.STYLE_BUTTONS:
            return "style", SettingASCIIorANSI.STYLE_BUTTONS[button_id]
        elif button_id in SettingSceneFilters.BUTTON_VALUES:
            enabled = SettingSceneFilters.BUTTON_VALUES[button_id]
            if settings["scene_filters_enabled"] != enabled:
                return "scene_filters_enabled", enabled
        elif button_id in self.SPEED_BUTTONS:
            return "text_speed", self.SPEED_BUTTONS[button_id][0]
        elif button_id == "btn-audio-mute":
            return "audio_muted", not settings["audio_muted"]
        elif button_id.startswith("btn-audio-"):
            group, _, direction = button_id.removeprefix("btn-audio-").rpartition("-")
            if group in SettingAudio.GROUPS and direction in ("minus", "plus"):
                key = f"audio_{group}"
                delta = 0.1 if direction == "plus" else -0.1
                return key, max(0.0, min(1.0, round(float(settings[key]) + delta, 2)))
        return None

    def set_opened_from(self, source: str) -> None:
        self.set_class(source == "menu", "open-from-menu")
        self.set_class(source == "pause", "open-from-pause")

    def show(self, language: str) -> None:
        from_menu = self.has_class("open-from-menu")
        self.query_one("#setting-language").set_class(not from_menu, "hidden")
        self.remove_class("hidden")
        first_button = f"#btn-language-{language}" if from_menu else "#btn-header-on"
        self.query_one(first_button, Button).focus()

    def sync_language_buttons(self, language: str) -> None:
        for code in LANGUAGE_NAMES:
            self.query_one(f"#btn-language-{code}", Button).variant = (
                "success" if code == language else "default"
            )

    def sync_header_buttons(self, enabled: bool) -> None:
        self.query_one("#btn-header-on", Button).variant = "success" if enabled else "default"
        self.query_one("#btn-header-off", Button).variant = "default" if enabled else "error"

    def sync_header_filter_buttons(self, settings: Mapping[str, str | float | bool]) -> None:
        for button_id, key in self.HEADER_FILTER_BUTTONS.items():
            self.query_one(f"#{button_id}", Button).variant = (
                "success" if settings.get(key, True) else "default"
            )

    def sync_art_style_buttons(self, selected: str) -> None:
        for button_id, style in SettingASCIIorANSI.STYLE_BUTTONS.items():
            self.query_one(f"#{button_id}", Button).variant = (
                "primary" if style == selected else "default"
            )

    def sync_scene_filter_buttons(self, enabled: bool) -> None:
        self.query_one("#btn-scene-filters-on", Button).variant = "success" if enabled else "default"
        self.query_one("#btn-scene-filters-off", Button).variant = "default" if enabled else "error"

    def sync_quality_buttons(self, selected: str, *, clear_others: bool = True) -> None:
        self._sync_selection(self.QUALITY_BUTTONS, selected, clear_others)

    def sync_speed_buttons(self, selected: str, *, clear_others: bool = True) -> None:
        self._sync_selection(self.SPEED_BUTTONS, selected, clear_others)

    def _sync_selection(
        self, buttons: dict[str, tuple[str, str]], selected: str, clear_others: bool,
    ) -> None:
        for button_id, (value, variant) in buttons.items():
            if value == selected or clear_others:
                self.query_one(f"#{button_id}", Button).variant = (
                    variant if value == selected else "default"
                )

    def sync_audio_controls(self, settings: Mapping[str, str | float | bool]) -> None:
        for group in SettingAudio.GROUPS:
            percent = round(float(settings[f"audio_{group}"]) * 100)
            self.query_one(f"#audio-{group}-level", Label).update(f"{percent}%")
        self.query_one("#btn-audio-mute", Button).variant = (
            "error" if settings["audio_muted"] else "default"
        )

    def on_key(self, event: events.Key) -> None:
        focused = self.screen.focused
        if event.key not in {"up", "down"} or not isinstance(focused, Button):
            return
        event.stop()
        event.prevent_default()
        sign = -1 if event.key == "up" else 1
        x, y = focused.region.center
        candidates = []
        for button in self.screen.focus_chain:
            if not isinstance(button, Button) or self not in button.ancestors or not button.region:
                continue
            bx, by = button.region.center
            distance = sign * (by - y)
            if distance > 0:
                candidates.append((distance, abs(bx - x), button))
        if candidates:
            # Настройки идут рядами сверху вниз: ближайший ряд важнее колонки,
            # иначе правая кнопка перескакивает блоки с одной левой колонкой.
            min(candidates, key=lambda item: item[:2])[2].focus()


class SettingLanguage(HorizontalGroup):
    BORDER_TITLE = "Язык"

    def compose(self):
        with HorizontalGroup(id="language-controls", classes="setting-controls setting-controls-wide"):
            for code, name in LANGUAGE_NAMES.items():
                yield Button(name, id=f"btn-language-{code}")
        yield Label("Язык сюжета и меню.", id="setting-language-description", classes="setting-description")


class SettingAudio(Vertical):
    """Независимые пользовательские уровни, не сценарные volume-команды."""
    BORDER_TITLE = "Звук"
    GROUPS = {"master": "Общая громкость", "music": "Музыка",
              "environment": "Окружение", "effects": "Разовые эффекты"}

    def compose(self):
        for group, title in self.GROUPS.items():
            with HorizontalGroup(classes="audio-setting-row"):
                yield Label(title, id=f"audio-{group}-title", classes="audio-setting-title")
                yield Button("−10%", id=f"btn-audio-{group}-minus")
                yield Label("", id=f"audio-{group}-level", classes="audio-setting-level")
                yield Button("+10%", id=f"btn-audio-{group}-plus")
        yield Button("Без звука", id="btn-audio-mute")

class SettingHeader(HorizontalGroup):
    """Виджет с настройкой Header"""
    BORDER_TITLE = "Верхняя панель(Header)"
    def compose(self):
        with Vertical(id="header-controls", classes="setting-controls setting-controls-wide"):
            with HorizontalGroup(classes="header-setting-row"):
                yield Button("Включить", variant="default", id="btn-header-on")
                yield Button("Выключить", variant="error", id="btn-header-off")
            yield Label("Показывать в Header:", id="header-content-label")
            with HorizontalGroup(classes="header-setting-row"):
                yield Button("LP-поинты", id="btn-header-lp-points")
                yield Button("Флаги", id="btn-header-flags")
        yield DescriptionSettingHeader(id="setting-header-description", classes="setting-description")


class SettingDescription(Static):
    TEXT = ""

    def __init__(self, **kwargs):
        super().__init__(self.TEXT, markup=False, **kwargs)


class DescriptionSettingHeader(SettingDescription):
    """Описание настройки 'Верхняя панель(Header)'"""
    TEXT = """Верхняя панель будет отображать:
название программы, выбранные группы переменных и системное время.\n
LP-поинты и флаги можно включать независимо.
(может слегка уменьшить обзор)"""

class SettingQuality(HorizontalGroup):
    """Виджет с настройкой размера ASCII-артов"""
    BORDER_TITLE = "Размер ANSI/ASCII артов"
    def compose(self):
        with Vertical(classes="setting-controls"):
            yield Button("маленький\n(50)", variant="default", id="btn-small")
            yield Button("Средний\n(150)", variant="default", id="btn-medium")
            yield Button("ОГРОМНЫЙ\n(200)", variant="default", id="btn-large")
        yield DescriptionSettingQuality(id="setting-quality-description", classes="setting-description")

class DescriptionSettingQuality(SettingDescription):
    """Описание настройки 'Размер ANSI/ASCII артов'"""
    TEXT = """Размер артов лучше подбирать по размеру окна консоли,
с сильно большим размером изображение может не поместиться.\n 
Можно так же попробовать уменьшить размер шрифта самой консоли 
(Обычно это Ctrl+"+" и Ctrl+"-")"""

class SettingASCIIorANSI(HorizontalGroup):
    """Виджет с настройкой стиля артов"""
    BORDER_TITLE = "Стиль артов"
    STYLE_BUTTONS = {
        "btn-ANSI": "ANSI",
        "btn-ASCII": "ASCII",
        "btn-COLOR-ASCII": "COLOR_ASCII",
    }

    def compose(self):
        with Vertical(classes="setting-controls"):
            yield Button("ANSI", variant="default", id="btn-ANSI")
            yield Button("ЧБ ASCII", variant="default", id="btn-ASCII")
            yield Button("Цветной ASCII", variant="default", id="btn-COLOR-ASCII")
        yield DescriptionSettingASCIIorANSI(id="setting-art-style-description", classes="setting-description")

class DescriptionSettingASCIIorANSI(SettingDescription):
    """Описание настройки 'Стиль артов'"""
    TEXT = """ANSI — цветные блоки
ЧБ ASCII — одноцветные символы .,:+*?%@
Цветной ASCII — те же символы в цветах изображения"""

class SettingSceneFilters(HorizontalGroup):
    """Пользовательская видимость фильтров, независимо от стиля артов."""
    BORDER_TITLE = "Фильтры изображения"
    BUTTON_VALUES = {
        "btn-scene-filters-on": True,
        "btn-scene-filters-off": False,
    }

    def compose(self):
        with HorizontalGroup(id="scene-filter-controls", classes="setting-controls setting-controls-wide"):
            yield Button("Включить", id="btn-scene-filters-on")
            yield Button("Выключить", id="btn-scene-filters-off")
        yield Static(
            "В ASCII фильтры можно отключить для лучшей различимости изображения. "
            "Персонажи и их тонировка сохраняются.",
            id="setting-scene-filters-description",
            classes="setting-description scene-filter-description",
        )


class SettingTextSpeed(HorizontalGroup):
    """Виджет с настройкой скорости текста"""
    BORDER_TITLE = "Скорость текста"
    def compose(self):
        with Vertical(classes="setting-controls"):
            yield Button("Медленно", variant="default", id="btn-speed-slow")
            yield Button("Средне", variant="default", id="btn-speed-medium")
            yield Button("Быстро", variant="default", id="btn-speed-fast")
            yield Button("Моментально", variant="default", id="btn-speed-instantly")
        yield DescriptionSettingTextSpeed(id="setting-text-speed-description", classes="setting-description")

class DescriptionSettingTextSpeed(SettingDescription):
    """Описание настройки 'Скорость текста'"""
    TEXT = """Скорость появления текста в текстовом окне.\n
Медленно    - 0.04
Средне      - 0.025
Быстро      - 0.01
Моментально - 0"""
