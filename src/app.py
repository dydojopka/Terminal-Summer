"""Связывает интерфейс, сценарий и подсистемы игры в приложении Textual."""

import asyncio
import hashlib
import re
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image
from rich.text import Text
from textual import _time, events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual.scrollbar import ScrollBar, ScrollBarCorner
from textual.widget import Widget
from textual.widgets import Footer, Label, ListView, Static

from audio.catalog import validate_audio_assets
from audio.manager import AudioManager, NullAudioBackend, PygameAudioBackend, normalize_audio_settings
from cards.game import Phase
from cards.session import CardSession
from cards.table import CardTable
from credits import CREDIT_PAGES, CreditsTimeline
from endings_catalog import current_ending
from file_io import atomic_output
from gallery_catalog import load_gallery_catalog, resolve_gallery_image
from paths import get_frozen_bundle_dir, get_resource_path, get_ts_path, get_user_data_dir
from rendering.art import render_art
from rendering.cache import file_signature
from rendering.jobs import SceneRenderer
from rendering.preload import ScriptPreloader
from rendering.scene import RenderSprite, SceneRenderSnapshot
from rendering.sprites import (
    compose_layers,
    load_yaml_dict as load_sprite_resources_yaml,
    parse_show_like,
    resolve_sprite,
)
from storage import saves, settings as settings_storage
from storage.progress import (
    ending_unlock_time, merge_ending_dates, normalize_ending_dates, read_progress, write_progress,
)
from storage.save_view import validate_save_view
from story.card_commands import RESULTS
from story.locale import load_interface_locale
from story.parser import ScriptParser, format_script_state, TIMES_OF_DAY

from ui.menus.endings import EndingResult, EndingsList, EndingsMenu
from ui.menus.gallery import GalleryMenu
from ui.menus.main_menu import MainMenu
from ui.menus.music_room import MusicRoom
from ui.menus.pause import PauseMenu, PauseMenuContainer
from ui.menus.saves import OutdatedSaveDialog, SaveMenu
from ui.menus.settings import LANGUAGE_NAMES, LanguageDialog, SettingsMenu
from ui.novel.camp_map import CampMap, map_render_width
from ui.novel.choices import ChoiceBar
from ui.novel.dialogue import LogMenu, NovelMenu, TextBar
from ui.novel.header import ScriptStateHeader
from ui.novel.loading import ScriptLoadingOverlay
from ui.novel.window import NovelWindow
from ui.screen import PerformanceScreen
from ui.widgets.console_button import ConsoleButton as Button
from ui.widgets.console_scrollbar import ConsoleScrollBarRender
from ui.widgets.terminal_size import MINIMUM_TERMINAL_SIZE, TerminalSizeWarning


CSS_PATH = get_resource_path("gameUI.tcss")
MENU_LOGO_PATH = get_resource_path("menu_logo.ansi")
APP_VERSION = "1.0.0"
# Original game/options.rpy: config.main_menu_music = "sound/music/blow_with_the_fires.ogg".
MENU_MUSIC_KEY = "blow_with_the_fires"

# Только сценарные фильтры; полноэкранные записки и opening-слои ими не являются.
SCENE_FILTER_IDS = frozenset({"prologue_filter"})


class TerminalSummer(App):
    """Основное приложение новеллы"""
    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = "#btn-start-game"
    CSS_PATH = str(CSS_PATH)
    TITLE = f"Terminal Summer {APP_VERSION}"
    SUB_TITLE = format_script_state()

    CONFIG_FILE = get_user_data_dir() / "settings.json"
    PERSISTENT_FILE = get_user_data_dir() / "persistent.json"
    DEFAULT_SETTINGS = settings_storage.DEFAULT_SETTINGS

    def __init__(self):
        super().__init__()
        self.settings = self.DEFAULT_SETTINGS.copy()
        self._settings_read_error = False
        self._persistent_read_error = False

        self.ts_path = get_ts_path()
        bundle_dir = get_frozen_bundle_dir()
        self.bundled_text_path = bundle_dir / "TS" / "text" if bundle_dir is not None else None
        self.interface_locale: dict[str, str] = {}
        self.endings_locale: dict[str, str] = {}
        self.runtime_ui: dict[str, str] = {}
        self.audio = AudioManager(self.ts_path)
        self._menu_music_active = False
        self.ending_dates = {}
        self._new_ending_flags: set[str] = set()
        self._credits: CreditsTimeline | None = None
        self._credits_script: ScriptParser | None = None
        self._credit_ending = None

        self._sprite_resources = None
        self._sprite_resources_signature = None
        self._sprite_assets_root = self.ts_path / "images"
        self._sprite_runtime_dir = self.ts_path / "images/sprites/generated_runtime"
        self._active_sprites = {}
        self._sprite_order_seq = 0
        self.current_time = "day"
        self.current_text_mode = "adv"
        self._interface_hidden = False
        self._next_scene_in_progress = False
        self._text_animating = False
        self._text_animating_since = None
        self._text_animating_until = 0.0
        self._input_blocked = False
        self._input_blocked_since = None
        self._input_blocked_until = 0.0
        self._space_last_event_at = 0.0
        self._space_idle_gap = 0.12
        self._space_require_idle = False
        self.skipping = False
        self._skip_last_event_at = 0.0
        self._skip_input_after = _time.get_time()
        self._skip_next_advance_at = 0.0
        self._skip_timer = None
        self._skip_binding_available = None
        self._script_advance_task: asyncio.Task | None = None
        self._script_delay_event: asyncio.Event | None = None
        self._script_delay_kind: str | None = None
        self._script_delay_skippable = False
        self._script_delay_generation = 0
        self._game_paused = False
        self._terminal_too_small = False
        self._terminal_size_focus = None
        self._game_pause_changed_event = asyncio.Event()
        self.scene_dirty = False
        self._scene_generation = 0
        self._renderer = SceneRenderer()
        self._preloader = ScriptPreloader(self._renderer)
        self._loading_restore_novel = False
        self._preload_after_settings = False
        self.gallery_images = []
        self._gallery_catalog = None
        self._gallery_error = None
        self.card_session: CardSession | None = None
        self._card_auto_key = None
        self._card_move_due = 0.0
        self._card_art_key = None
        self._card_render_generation = 0

    text_speed = "0.025" # Скорость текста 0.04 | 0.025 | 0.01 | 0

    gallery_mode = "cg"
    gallery_size = "150" # small - 50 | medium - 150 | large - 200
    gallery_style = "ANSI"
    gallery_index = 0
    gallery_images = []

    BINDINGS = [
        Binding(
            "escape",
            "pause_game",
            "Пауза",
            show=True,
            key_display = "ESC",
            id="bind-pause"),
        Binding(
            "space",
            "",
            "Далее",
            show=True,
            key_display = "SPACE",
            id="bind-next"),
        Binding(
            "s,ы,S,Ы",
            "toggle_skipping",
            "Пропуск",
            key_display="S",
            id="bind-skip"),
        Binding(
            "h, р",
            "log",
            "История",
            show=True,
            key_display = "H",
            id="bind-log"),
        Binding(
            "f, а",
            "toggle_interface",
            "Скрыть интерфейс",
            key_display = "F",
            show=True,
            id="bind-toggle-interface"),
    ]

    TEXT_MODES = {"adv", "nvl"}
    current_time = reactive("day", repaint=False)

    def watch_current_time(self, time_of_day: str) -> None:
        """Палитра интерфейса следует time, а не фильтрам изображения/спрайтов."""
        for name in TIMES_OF_DAY:
            self.set_class(time_of_day == name, f"time-{name}")

    def _start_widget(self, parent: Widget, widget: Widget) -> None:
        # Системные полосы и их угол Textual создаёт в обход обычного CSS-монтажа.
        if isinstance(widget, ScrollBar):
            widget.renderer = ConsoleScrollBarRender
        elif isinstance(widget, ScrollBarCorner):
            widget.styles.visibility = "hidden"
        super()._start_widget(parent, widget)

    def get_default_screen(self) -> Screen:
        return PerformanceScreen(id="_default")

    def compose(self) -> ComposeResult:
        yield ScriptStateHeader(show_clock=True, classes="hidden")
        yield Footer(classes="hidden")

        yield MainMenu(MENU_LOGO_PATH, id="main-menu")
        yield NovelWindow(self.ts_path, id="novel-window", classes="hidden")
        yield NovelMenu(   id="novel-menu",    classes="hidden")
        yield LogMenu(     id="log-menu",      classes="hidden")
        yield PauseMenu(   id="pause-menu",    classes="hidden")
        yield SettingsMenu(id="settings-menu", classes="hidden")
        yield GalleryMenu( id="gallery-menu",  classes="hidden")
        yield EndingsMenu( id="endings-menu",  classes="hidden")
        yield SaveMenu(    id="save-menu",     classes="hidden")
        yield ScriptLoadingOverlay(id="script-loading", classes="hidden")
        yield TerminalSizeWarning()

    def set_novel_menu_visible(self, visible: bool) -> None:
        """Показывает или скрывает панель диалога вместе с подсказками клавиш."""
        self.query_one("#novel-menu").set_class(not visible, "hidden")
        self.query_one(Footer).set_class(not visible, "hidden")

    def set_text_mode(self, mode: str) -> None:
        """Сохраняет режим текста и обновляет его отображение."""
        normalized_mode = mode.lower().strip()
        next_mode = (
            normalized_mode if normalized_mode in self.TEXT_MODES else "adv"
        )
        if next_mode != self.current_text_mode:
            # Первая NVL-реплика не должна дописываться к последней ADV-реплике.
            try:
                text_bar = self.query_one("#text-bar", Widget)
                text_bar.text = ""
                text_bar.border_title = ""
                text_bar.refresh()
            except Exception:
                # До mount виджеты ещё не существуют; режим всё равно сохраняем.
                pass
        self.current_text_mode = next_mode
        self.sync_text_mode_display()

    def sync_text_mode_display(self) -> None:
        """Синхронизирует оформление NVL и видимость сцены с состоянием UI."""
        novel_menu = self.query_one("#novel-menu", Widget)
        novel_window = self.query_one("#novel-window", Widget)
        bg_cg = self.query_one("#bg-cg", Widget)
        choice_bar = self.query_one("#choice-bar", Widget)
        is_nvl = self.current_text_mode == "nvl"
        is_choosing = not choice_bar.has_class("hidden")

        if self._interface_hidden:
            self.set_novel_menu_visible(False)
        novel_menu.set_class(is_choosing, "choice-mode")
        novel_menu.set_class(is_nvl and not is_choosing, "nvl-mode")
        novel_window.set_class(
            is_nvl
            and not self._interface_hidden
            and choice_bar.has_class("hidden"),
            "hidden",
        )
        bg_cg.set_class(
            (is_nvl and not self._interface_hidden)
            or not choice_bar.has_class("hidden"),
            "hidden",
        )
        if self.card_session is not None:
            novel_window.remove_class("hidden")
            bg_cg.add_class("hidden")
        self.sync_card_view()

    async def execute_card_command(self, command, script, pc):
        """Возвращает False, когда выполнение TXT ждёт игрового действия."""
        if script is not getattr(self, "script", None):
            raise ValueError("Карточная команда от неактивного сценария")
        self.stop_skipping()
        if command.action in {"tutorial", "play"}:
            if self.card_session is not None:
                raise ValueError("Предыдущая карточная партия не завершена")
            self.card_session = CardSession.start(command, pc)
            table = self.query_one(CardTable)
            table.replace_game(self.card_session.game)
            self._card_art_key = None
        elif self.card_session is None:
            raise ValueError("Карточная партия не начата")
        elif command.action == "end":
            if not self.card_session.tutorial or self.card_session.playing:
                raise ValueError("Нельзя завершить незаконченный карточный ход")
            self.close_card_game()
        elif command.action == "reveal":
            if not self.card_session.tutorial or self.card_session.playing:
                raise ValueError("Нельзя открыть карты во время активного хода")
            self.card_session.player_visible = True
        else:
            self.card_session.wait(command, pc)
        self.sync_text_mode_display()
        await self.flush_scene_render()
        return self.card_session is None or not self.card_session.playing

    def close_card_game(self):
        self.card_session = None
        self._card_auto_key = self._card_art_key = None
        self._card_render_generation += 1
        self.query_one(CardTable).add_class("hidden")
        self.query_one("#novel-menu").remove_class("card-mode")
        self.mark_scene_dirty()

    def _card_save_data(self):
        if self.card_session is None:
            return None
        self.card_session.selection = self.query_one(CardTable).swap_first
        return self.card_session.to_save_data()

    def sync_card_view(self):
        if not self.is_running:
            return
        table = self.query_one(CardTable)
        session = self.card_session
        table.set_class(session is None, "hidden")
        self.query_one("#novel-menu").set_class(session is not None, "card-mode")
        if session is None:
            return
        table.card_style = self.settings["style"]
        table.player_visible = session.player_visible
        table.targets_visible = session.targets_visible
        table.rival_name = self.runtime_ui.get("card.tutorial", "Пробная игра") if session.tutorial else None
        table.query_one("#card-sidebar").set_class(self._interface_hidden, "hidden")
        table.input_enabled = self.is_card_input_ready()
        table.sync()
        if table.input_enabled:
            self.call_after_refresh(self._focus_cards_if_playing)

    def is_card_input_ready(self):
        return (self.card_session is not None and self.card_session.playing
                and self.is_gameplay_context() and not self._next_scene_in_progress
                and not self.script.failed and not self.script.has_diagnostic)

    def _focus_cards_if_playing(self):
        if not self.is_running:
            return
        table = self.query_one(CardTable)
        if (self.card_session is not None and table.input_enabled and self.is_gameplay_context()
                and (self.focused is None or table not in self.focused.ancestors_with_self)):
            table.focus_active_hand()

    async def on_card_table_scene_resized(self, event: CardTable.SceneResized):
        event.stop()
        if self.is_running and self.card_session is not None:
            await self.refresh_card_scene()

    async def refresh_card_scene(self):
        session = self.card_session
        if session is None:
            return
        table = self.query_one(CardTable)
        snapshot = replace(self._capture_scene_snapshot(),
                           width=min(table.scene_width, int(self.settings["quality"])))
        if snapshot.key == self._card_art_key:
            return
        generation = self._scene_generation
        self._card_render_generation += 1
        card_generation = self._card_render_generation
        art = await self._get_render_async(snapshot)
        if (self.is_running and session is self.card_session and generation == self._scene_generation
                and card_generation == self._card_render_generation):
            table.query_one("#card-scenery", Static).update(art)
            self._card_art_key = snapshot.key

    def on_card_table_changed(self, event: CardTable.Changed):
        event.stop()
        session = self.card_session
        if session is None or event.game is not session.game:
            return
        session.selection = self.query_one(CardTable).swap_first
        if session.finish_wait():
            self.sync_card_view()
            self._start_script_advance()

    def on_card_table_finished(self, event: CardTable.Finished):
        event.stop()

    def on_card_table_result_accepted(self, event: CardTable.ResultAccepted):
        event.stop()
        self.accept_card_result(event.game)

    def accept_card_result(self, game):
        session = self.card_session
        if (session is None or game is not session.game or not self.is_card_input_ready()
                or session.command is None or session.command.action != "play"
                or game.phase != Phase.RESULT):
            return
        label = session.command.labels[RESULTS.index(game.result)]
        self.script.jump_to_label(label)
        self.close_card_game()
        self.sync_text_mode_display()
        self._start_script_advance()

    def _card_tick(self):
        if not self.is_running:
            return
        session = self.card_session
        if session is not None:
            enabled = self.is_card_input_ready()
            if self.query_one(CardTable).input_enabled != enabled:
                self.sync_card_view()
        if (not self.is_card_input_ready()
                or session.game.phase not in {Phase.RIVAL_TAKE, Phase.RIVAL_DEFEND, Phase.PLAYER_TAKE}):
            self._card_auto_key = None
            return
        game = session.game
        key = id(session), game.round, game.phase, game.swaps_left, game.opponent_target
        if key != self._card_auto_key:
            self._card_auto_key = key
            self._card_move_due = _time.get_time() + 0.65
        elif _time.get_time() >= self._card_move_due:
            self.query_one(CardTable).confirm()
            self._card_auto_key = None



    # ============ Функции - on_ ============
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._terminal_too_small:
            event.stop()
            return
        button_id = event.button.id or ""
        match button_id:
            case "btn-next":
                await self._advance_from_button()
            case "btn-log":
                self.action_log()
            case "btn-continue":
                self.action_pause_game()
            case "btn-save":
                self.open_save_menu("pause")
            case "btn-menu":
                self.reset_game_view()
                self.action_open_menu()
            case "btn-exit-pause" | "btn-exit-menu":
                self.exit()
            case "btn-settings-pause" | "btn-settings-menu":
                source = "pause" if button_id == "btn-settings-pause" else "menu"
                self.query_one(SettingsMenu).set_opened_from(source)
                self.action_open_settings()
            case "btn-close-settings":
                self._close_settings_from_button()
            case "btn-start-game":
                self.start_new_game()
            case "btn-save-load":
                self.open_save_menu("menu")
            case "btn-gallery" | "btn-close-gallery":
                self.action_open_gallery()
            case "btn-achievements" | "btn-close-endings":
                self.action_open_endings()
            case "btn-language-menu":
                self.push_screen(LanguageDialog(self.settings["language"]), self.set_language)
            case "btn-close-save-menu":
                self.close_save_menu()
            case "btn-save-delete":
                self.delete_selected_save()
            case "btn-save-load-game":
                self.load_selected_save()
            case "btn-save-save":
                self.save_to_selected_slot()
            case _:
                if self._handle_gallery_button(button_id):
                    return
                if self.query_one(SaveMenu).handle_selection(button_id):
                    return
                menu = self.query_one(SettingsMenu)
                if change := menu.setting_change(button_id, self.settings):
                    await self._apply_setting_change(menu, *change)

    async def _apply_setting_change(self, menu: SettingsMenu, key: str, value: str | float | bool) -> None:
        if key == "language":
            self.set_language(str(value))
            return

        if key == "header":
            self.query_one("Header").set_class(not value, "hidden")
            menu.sync_header_buttons(bool(value))
        elif key == "quality":
            menu.sync_quality_buttons(str(value))
        elif key == "text_speed":
            menu.sync_speed_buttons(str(value))

        self.settings[key] = value
        if key in {"header_lp_points", "header_flags"}:
            menu.sync_header_filter_buttons(self.settings)
            self.update_script_header()
        elif key == "style":
            menu.sync_art_style_buttons(str(value))
        elif key == "scene_filters_enabled":
            menu.sync_scene_filter_buttons(bool(value))
        elif key.startswith("audio_"):
            self.apply_audio_settings()

        self.save_settings()
        if key in {"quality", "style", "scene_filters_enabled"}:
            await self.update_current_scene_art()
        elif key == "text_speed":
            self.apply_settings()

    def _close_settings_from_button(self) -> None:
        menu = self.query_one(SettingsMenu)
        if menu.has_class("open-from-pause"):
            self.action_open_settings()
        elif menu.has_class("open-from-menu"):
            self.action_open_menu()
            menu.remove_class("open-from-menu")

    def start_new_game(self) -> None:
        self.cancel_script_advance()
        self.stop_credits()
        self._new_ending_flags.clear()
        self._menu_music_active = False
        self.audio.reset()

        # Скрытие главного меню
        self.action_open_menu()
        self.clear_log()
        self._interface_hidden = False
        self.current_time = "prologue"
        self.set_text_mode("adv")

        # Сброс всех глобальных переменных
        from story.parser import reset_globals
        reset_globals()
        self.update_script_header()

        # Запуск новой игры (всегда пролог)
        prologue_path = self.ts_path / "text" / "prologue.txt"
        self.script = ScriptParser(prologue_path, self)

        # Отображение NovelMenu
        self.set_novel_menu_visible(True)
        self.query_one("#novel-window").remove_class("hidden")
        self.start_script_preload(self.script)

        # Фокус на кнопке "Вперёд" в игровом меню
        self.query_one("#btn-next", Button).focus()

    def on_mount(self) -> None:
        """Загрузка настроек при запуске"""
        # Headless UI tests never open a real device. Backend tests opt in explicitly.
        if self.is_headless and self.audio.backend_factory is PygameAudioBackend:
            self.audio.backend_factory = NullAudioBackend
        self.load_persistent_state()
        self.load_settings()
        self.apply_settings()
        self.start_menu_music()
        self.set_interval(0.5, self.poll_audio_errors)
        self._skip_timer = self.set_interval(0.05, self._skip_tick)
        self.set_interval(0.1, self._card_tick)
        self.app_suspend_signal.subscribe(
            self, lambda _: self.stop_skipping(), immediate=True
        )
        self.screen_change_signal.subscribe(self, lambda _: self.sync_terminal_size())
        self.sync_terminal_size()
        if not self.is_headless:
            errors = validate_audio_assets(self.ts_path, self.audio.catalog)
            if errors:
                self.notify(
                    self.runtime_ui.get("audio.missing",
                        "Часть аудиофайлов отсутствует. Установите TS/sound из нового архива ассетов."),
                    title=self.runtime_ui.get("audio.title", "Звук"), severity="warning", timeout=10,
                )

    def on_resize(self, event: events.Resize) -> None:
        self.sync_terminal_size(event.size)

    def sync_terminal_size(self, size=None) -> None:
        """Скрывает все экраны, не меняя состояния меню, фокуса и обычной паузы."""
        size = self.size if size is None else size
        too_small = (size.width < MINIMUM_TERMINAL_SIZE.width
                     or size.height < MINIMUM_TERMINAL_SIZE.height)
        # Отладочный Header уступает место маленькому арту, а не увеличивает
        # минимальный размер окна на семь дополнительных строк.
        for header in self.query(ScriptStateHeader):
            header.styles.max_height = min(8, max(1, size.height - MINIMUM_TERMINAL_SIZE.height + 1))
        changed = too_small != self._terminal_too_small
        if changed:
            if too_small and self.focused is not None:
                self._terminal_size_focus = self.focused
            self._terminal_too_small = too_small
            self.stop_skipping()
            self._space_require_idle = True
            self._space_last_event_at = _time.get_time()
            self._signal_game_pause_changed()
        for screen in self.screen_stack:
            screen.set_class(too_small, "terminal-too-small")
            # 27 + 27 — боковые панели; 50 + 2 — текст с рамкой.
            screen.set_class(size.width < 106, "compact-terminal")
            warnings = screen.query(TerminalSizeWarning)
            if not warnings:
                # В том числе встроенные экраны Textual, например Ctrl+P.
                screen.call_after_refresh(self._ensure_terminal_size_warning, screen)
            for warning in warnings:
                warning.update_size(size)
        if changed:
            self.refresh_bindings()
            if not too_small:
                self.call_after_refresh(self._restore_terminal_size_focus)

    def _ensure_terminal_size_warning(self, screen: Screen) -> None:
        if screen.is_mounted and screen in self.screen_stack and not screen.query(TerminalSizeWarning):
            screen.mount(TerminalSizeWarning())

    def _restore_terminal_size_focus(self) -> None:
        if self._terminal_too_small:
            return
        focused = self._terminal_size_focus
        self._terminal_size_focus = None
        focus_chain = self.screen.focus_chain
        if focused in focus_chain:
            focused.focus(scroll_visible=False)
        elif focused is None and self.screen.id == "_default":
            default = self.query_one("#btn-start-game", Button)
            if default in focus_chain:
                default.focus()
            elif self.focused not in focus_chain:
                self.screen.focus_next()
        elif self.focused not in focus_chain:
            self.set_focus(None)
            self.screen.focus_next()

    async def on_event(self, event: events.Event) -> None:
        # Перехват до фокуса и priority-bindings модальных экранов: невидимые
        # кнопки/выборы не получают ввод. Resize и события фокуса проходят.
        if self._terminal_too_small and isinstance(event, (events.InputEvent, events.Paste)):
            if isinstance(event, events.Key) and event.key == "ctrl+q":
                self.exit()
            event.stop()
            event.prevent_default()
            return
        if self.is_card_input_ready() and isinstance(event, events.Key):
            if event.key == "space":
                if self.card_session.game.phase == Phase.RESULT:
                    self.accept_card_result(self.card_session.game)
                elif self.card_session.game.phase == Phase.DEFEND:
                    self.query_one(CardTable).confirm()
                event.stop()
                event.prevent_default()
                return
            if event.key in tuple("1234567"):
                self.query_one(CardTable).action_number(int(event.key) - 1)
                event.stop()
                event.prevent_default()
                return
        await super().on_event(event)

    def poll_audio_errors(self) -> None:
        errors = self.audio.drain_errors()
        if errors:
            self.notify(self.runtime_ui.get("audio.error", "\n".join(errors[:3])),
                        title=self.runtime_ui.get("audio.title", "Звук"), severity="warning", timeout=10)

    async def on_unmount(self) -> None:
        self.cancel_script_advance()
        self.clear_script_cache()
        if self._skip_timer is not None:
            self._skip_timer.stop()
        await asyncio.to_thread(self.audio.close)

    def on_app_blur(self) -> None:
        self.stop_skipping()

    async def on_camp_map_viewport_changed(self, event: CampMap.ViewportChanged) -> None:
        event.stop()
        await self.refresh_camp_map()

    async def refresh_camp_map(self) -> None:
        """Общий кэш сцен готовит фон; навигация меняет только рамку и номера."""
        bar = self.query_one(ChoiceBar)
        view = bar.query_one(CampMap)
        if bar.has_class("hidden") or not view.zones or not bar.is_on_screen:
            return
        width = map_render_width(
            view.content_size.width, view.content_size.height, int(self.settings["quality"])
        )
        if not width:
            return
        snapshot = replace(self._make_scene_snapshot("cg", "map", {}), width=width)
        view.request_key = snapshot.key
        if snapshot.key == view.art_key:
            return
        revision = view.revision
        art = await self._get_render_async(snapshot)
        if (self.is_running and not bar.has_class("hidden") and view.zones
                and revision == view.revision and view.request_key == snapshot.key
                and snapshot.cache_epoch == self._renderer.cache.epoch):
            view.set_art(art, snapshot.key, snapshot.style)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Обработка выбора из меню"""
        if self._terminal_too_small:
            event.stop()
            return
        choice_bar = self.query_one("#choice-bar")
        if event.list_view is not choice_bar.query_one(ListView):
            return
        pending_choices = getattr(self, "pending_choices", None)
        if choice_bar.has_class("hidden") or not pending_choices:
            return

        choice = pending_choices.get(event.item.name)
        if choice is None:
            return

        self.stop_skipping()
        self.script.select_choice(choice)

        # Очищаем pending_choices до продолжения сценария.
        self.pending_choices = None

        # Скрываем меню выбора и возвращаем видимость, подходящую текущему режиму.
        choice_bar.close()
        self.set_novel_menu_visible(True)
        self.sync_text_mode_display()

        # Продолжаем сценарий с выбранного неизменяемого диапазона. Само
        # выполнение уходит в отдельную задачу, чтобы не задерживать очередь UI.
        await self._advance_script_line()


    # ============ Функции - action_ ============
    async def action_next_scene(self) -> None:
        """Переключение по bind(space)."""
        await self._advance_script_line()

    def action_log(self) -> None:
        """Открытие меню истории"""
        if self._credits is not None:
            return
        self.stop_skipping()
        if not self.query_one("#endings-menu").has_class("hidden"):
            return
        log_menu = self.query_one("#log-menu")
        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")

        # Открываем историю только из novel_menu, закрытие доступно всегда
        if log_menu.has_class("hidden"):
            if novel_menu.has_class("hidden"):
                return

            # Скрываем сцену и диалог, но оставляем подсказки для выхода из истории.
            novel_menu.add_class("hidden")
            novel_window.add_class("hidden")

            # Показ меню истории
            log_menu.remove_class("hidden")
        else:
            # Cкрытие меню истории
            log_menu.add_class("hidden")

            # Показ bc, cg, text и кнопок
            self.set_novel_menu_visible(True)
            novel_window.remove_class("hidden")
            self.sync_text_mode_display()
            choice_bar = self.query_one("#choice-bar")
            if not choice_bar.has_class("hidden"):
                choice_bar.query_one(ListView).focus()

    def action_toggle_interface(self) -> None:
        """Показывает или скрывает интерфейс новеллы, оставляя сцену видимой."""
        self.stop_skipping()
        if not hasattr(self, "script"):
            return

        main_menu = self.query_one("#main-menu")
        choice_bar = self.query_one("#choice-bar")
        blocked_menus = (
            self.query_one("#log-menu"),
            self.query_one("#pause-menu"),
            self.query_one("#settings-menu"),
            self.query_one("#save-menu"),
            self.query_one("#gallery-menu"),
            self.query_one("#endings-menu"),
        )
        if (
            not main_menu.has_class("hidden")
            or not choice_bar.has_class("hidden")
            or any(not menu.has_class("hidden") for menu in blocked_menus)
        ):
            return

        novel_menu = self.query_one("#novel-menu")
        novel_window = self.query_one("#novel-window")
        if self._interface_hidden:
            self._interface_hidden = False
            self.set_novel_menu_visible(True)
            self.sync_text_mode_display()
            return

        if novel_menu.has_class("hidden"):
            return

        self._interface_hidden = True
        self.set_novel_menu_visible(False)
        novel_window.remove_class("hidden")
        if self.card_session is None:
            self.query_one("#bg-cg").remove_class("hidden")
        else:
            self.sync_card_view()

    def action_pause_game(self) -> None:
        """Открытие меню паузы"""
        self.stop_skipping()
        # Preload временно скрывает игровой интерфейс и затем самостоятельно
        # восстанавливает его. Не позволяем Escape открыть PauseMenu под
        # полноэкранным оверлеем и получить два конкурирующих состояния UI.
        if not self.query_one("#script-loading", Widget).has_class("hidden"):
            return

        pause_menu = self.query_one("#pause-menu")
        novel_window = self.query_one("#novel-window")
        settings_menu = self.query_one(SettingsMenu)
        main_menu = self.query_one("#main-menu")
        gallery_menu = self.query_one("#gallery-menu")
        save_menu = self.query_one(SaveMenu)
        choice_bar = self.query_one("#choice-bar")
        log_menu = self.query_one("#log-menu")

        if not log_menu.has_class("hidden"):
            self.action_log()
            return
        if not settings_menu.has_class("hidden"):
            self.action_open_settings()
            return

        # Escape закрывает сохранения и возвращает пользователя туда, откуда
        # меню было открыто: в главное меню или в окно новеллы.
        if not save_menu.has_class("hidden"):
            self.close_save_menu()
            return

        if not self.query_one("#endings-menu").has_class("hidden"):
            self.action_open_endings()
            return

        # Галерея всегда открывается из главного меню.
        if not gallery_menu.has_class("hidden"):
            self.action_open_gallery()
            return
        

        if not main_menu.has_class("hidden") or not choice_bar.has_class("hidden"):
            return
        if pause_menu.has_class("hidden"):
            self.set_game_paused(True)
            self.set_novel_menu_visible(False)
            novel_window.add_class("hidden")
            pause_menu.remove_class("hidden")
            self.query_one("#btn-continue", Button).focus()
        else:
            self.set_game_paused(False)
            pause_menu.add_class("hidden")
            self.set_novel_menu_visible(True)
            novel_window.remove_class("hidden")
            self.sync_text_mode_display()
            self.query_one("#btn-next", Button).focus()

    def start_menu_music(self) -> None:
        """Запускает фон меню один раз, не перезапуская его в дочерних разделах."""
        if self._menu_music_active or hasattr(self, "script"):
            return
        self.audio.play_menu(MENU_MUSIC_KEY)
        self._menu_music_active = True

    def start_music_preview(self, key, *, repeat=False):
        self._menu_music_active = False
        self.audio.start_preview(key, repeat=repeat)

    def leave_music_preview(self):
        if self.audio.music_status()["owner"] == "preview":
            self.audio.stop_preview()
            self.start_menu_music()

    def switch_gallery_tab(self, mode):
        if mode != "music":
            self.leave_music_preview()
        self.gallery_mode = mode
        self.query_one(GalleryMenu).select_tab(mode)
        if mode != "music":
            self.load_gallery_images()
            self.update_gallery_display()

    def _handle_gallery_button(self, button_id: str) -> bool:
        if button_id in GalleryMenu.TAB_BUTTONS:
            self.switch_gallery_tab(GalleryMenu.TAB_BUTTONS[button_id])
        elif button_id in {"btn-back-gallery", "btn-next-gallery"}:
            step = -1 if button_id == "btn-back-gallery" else 1
            index = self.gallery_index + step
            if 0 <= index < len(self.gallery_images):
                self.gallery_index = index
                self.update_gallery_display()
        elif button_id in GalleryMenu.SIZE_BUTTONS:
            self.gallery_size, _ = GalleryMenu.SIZE_BUTTONS[button_id]
            self.query_one(GalleryMenu).update_size_selection(self.gallery_size)
            self.load_gallery_images()
            self.update_gallery_display()
        elif button_id in GalleryMenu.STYLE_BUTTONS:
            style = GalleryMenu.STYLE_BUTTONS[button_id]
            if style != self.gallery_style:
                self.gallery_style = style
                self.query_one(GalleryMenu).update_style_selection(style)
                self.update_gallery_display()
        else:
            return False
        return True

    def action_open_menu(self) -> None:
        """Открытие главного меню"""
        self.stop_skipping()
        pause_menu = self.query_one("#pause-menu")
        settings_menu = self.query_one(SettingsMenu)
        main_menu = self.query_one("#main-menu")

        if main_menu.has_class("hidden"):
            # Скрытие предыдущего меню:
            if not pause_menu.has_class("hidden"):      # Из паузы
                pause_menu.add_class("hidden")
            elif not settings_menu.has_class("hidden"): # Из настроек
                settings_menu.add_class("hidden")

            # Показ главного меню
            main_menu.remove_class("hidden")
            self.start_menu_music()

            # Фокус на кнопке "Начать игру"
            self.query_one("#btn-start-game", Button).focus()
        else:
            # Скрытие главного меню
            main_menu.add_class("hidden")

    def action_open_settings(self) -> None:
        """Открытие меню настроек"""
        self.stop_skipping()
        settings_menu = self.query_one(SettingsMenu)
        pause_menu = self.query_one("#pause-menu")
        main_menu = self.query_one("#main-menu")
        novel_window = self.query_one("#novel-window")

        # Переключение видимости элементов
        if settings_menu.has_class("hidden"):
            if settings_menu.has_class("open-from-pause"): # Если открыто из паузы
                # Скрытие меню паузы
                pause_menu.add_class("hidden")
            elif settings_menu.has_class("open-from-menu"): # Если открыто из меню
                # Скрытие главного меню
                main_menu.add_class("hidden")

            settings_menu.show(self.settings["language"])
        else:
            # Cкрытие меню настроек
            settings_menu.add_class("hidden")

            if settings_menu.has_class("open-from-pause"): # Если открыто из паузы
                self.set_game_paused(False)
                # Удаление класса-флага
                settings_menu.remove_class("open-from-pause")

                # Показ диологового окна, кнопок перемотки и задника
                self.set_novel_menu_visible(True)
                novel_window.remove_class("hidden")
                self.sync_text_mode_display()

                if self._preload_after_settings and hasattr(self, "script"):
                    self._preload_after_settings = False
                    self.start_script_preload(self.script)

                # Возвращаем фокус на кнопку "Вперёд" в игровом меню 
                self.query_one("#btn-next", Button).focus()
            elif settings_menu.has_class("open-from-menu"): # Если открыто из меню
                # Удаление класса-флага
                settings_menu.remove_class("open-from-menu")

                # Показ главного меню
                main_menu.remove_class("hidden")

                # Возвращаем фокус на кнопку "Начать игру" в главном меню 
                self.query_one("#btn-start-game", Button).focus()

    def action_open_gallery(self) -> None:
        """Открытие меню галереи"""
        self.stop_skipping()
        gallery_menu = self.query_one(GalleryMenu)

        if gallery_menu.has_class("hidden"):
            # Скрываем главное меню
            self.action_open_menu()

            # Показываем меню галереи
            gallery_menu.remove_class("hidden")

            # Устанавливаем фокус на первую кнопку в меню галереи
            gallery_menu.focus_back_button()

            # Загружаем иллюстрации
            self.gallery_size = "150"
            self.gallery_index = 0
            self.switch_gallery_tab("cg")

            gallery_menu.update_size_selection(self.gallery_size)
        else:
            self.leave_music_preview()
            # Скрываем меню галереи
            gallery_menu.add_class("hidden")

            # Показываем главное меню
            self.action_open_menu()

    def action_open_endings(self) -> None:
        """Самостоятельное меню только из главного экрана, без изменения аудио."""
        self.stop_skipping()
        menu = self.query_one(EndingsMenu)
        main_menu = self.query_one("#main-menu")
        if menu.has_class("hidden"):
            if main_menu.has_class("hidden"):
                return
            main_menu.add_class("hidden")
            menu.remove_class("hidden")
            menu.refresh_progress()
            menu.query_one(EndingsList).focus()
        else:
            menu.add_class("hidden")
            main_menu.remove_class("hidden")
            self.query_one("#btn-achievements", Button).focus()

    # ============ Сохранения ============
    def is_savable_game_state(self) -> bool:
        """Проверка: можно ли сохраняться в текущем состоянии.

        Запрещает сохранение во время анимации текста, блокировки ввода,
        показа меню выбора или отсутствия запущенного сценария.
        """
        if self._terminal_too_small or self._credits is not None:
            return False
        if self._text_animating:
            return False
        if self._input_blocked:
            return False
        if self._script_delay_event is not None:
            return False
        if self._next_scene_in_progress:
            return False
        if not hasattr(self, "script") or not self.script or self.script.finished:
            return False
        if self.script.failed or self.script.has_diagnostic:
            return False
        if not self.query_one("#choice-bar").has_class("hidden"):
            return False
        return True

    def open_save_menu(self, opened_from: str) -> None:
        """Открытие меню сохранений"""
        self.stop_skipping()
        save_menu = self.query_one(SaveMenu)
        pause_menu = self.query_one("#pause-menu")
        main_menu = self.query_one("#main-menu")
        novel_window = self.query_one("#novel-window")

        save_menu.prepare(opened_from)
        save_menu.all_saves = saves.get_all_saves()

        # Скрытие предыдущего меню
        if opened_from == "pause":
            pause_menu.add_class("hidden")
        elif opened_from == "menu":
            main_menu.add_class("hidden")

        # Скрытие игровых элементов
        self.set_novel_menu_visible(False)
        novel_window.add_class("hidden")

        save_menu.show()

    def close_save_menu(self) -> None:
        """Закрытие меню сохранений"""
        self.stop_skipping()
        save_menu = self.query_one(SaveMenu)
        save_menu.add_class("hidden")

        opened_from = save_menu.opened_from

        if opened_from == "pause":
            self.set_game_paused(False)
            self.set_novel_menu_visible(True)
            self.query_one("#novel-window").remove_class("hidden")
            self.sync_text_mode_display()
            self.query_one("#btn-next", Button).focus()
        elif opened_from == "menu":
            self.query_one("#main-menu").remove_class("hidden")
            self.query_one("#btn-start-game", Button).focus()

    def update_save_menu_display(self) -> None:
        self.query_one(SaveMenu).update_slots()

    def switch_save_page(self, page: int) -> None:
        self.query_one(SaveMenu).select_page(page)

    def select_save_slot(self, slot_id: str) -> None:
        self.query_one(SaveMenu).select_slot(slot_id)

    def delete_selected_save(self) -> None:
        """Удаление выбранного сохранения"""
        save_menu = self.query_one(SaveMenu)
        if not save_menu.selected_slot:
            return

        slot_index = int(save_menu.selected_slot.split("-")[-1])
        page = save_menu.current_page

        try:
            saves.delete_save(page, slot_index)
        except OSError as exc:
            self._show_load_error(str(exc), key="delete.error")
            return
        save_menu.all_saves = saves.get_all_saves()
        save_menu.selected_slot = None
        self.update_save_menu_display()

    def _show_load_error(self, detail: str, *, key: str | None = None) -> None:
        strings = self.query_one(SaveMenu).strings
        self.sub_title = f"[Load error] {detail}"
        self.notify(strings.get(key, detail), title=strings.get("load.error", "Ошибка загрузки"),
                    severity="error", timeout=8)

    def _offer_outdated_save(self, page: int, slot: int) -> None:
        if isinstance(self.screen, OutdatedSaveDialog):
            return
        try:
            signature = saves.slot_digest(page, slot)
        except OSError:
            signature = None

        def confirmed(remove: bool) -> None:
            if not remove:
                return
            try:
                if signature is None or saves.slot_digest(page, slot) != signature:
                    self._show_load_error("Слот изменился; сохранение не удалено", key="outdated.changed")
                    return
                saves.delete_save(page, slot)
            except (OSError, ValueError) as exc:
                self._show_load_error(str(exc), key="delete.error")
                return
            menu = self.query_one("#save-menu")
            menu.all_saves = saves.get_all_saves()
            if menu.current_page == page and menu.selected_slot == f"save-slot-{slot}":
                menu.selected_slot = None
            self.update_save_menu_display()

        self.push_screen(OutdatedSaveDialog(strings=self.query_one(SaveMenu).strings, id="outdated-save"), confirmed)

    def load_selected_save(self) -> None:
        """Загрузка выбранного сохранения"""
        # Повторное нажатие, уже стоящее в очереди, не обрабатывается под модальным окном.
        if isinstance(self.screen, OutdatedSaveDialog):
            return
        save_menu = self.query_one(SaveMenu)
        if not save_menu.selected_slot:
            return

        slot_index = int(save_menu.selected_slot.split("-")[-1])
        page = save_menu.current_page

        try:
            game_state = saves.load_game_state(page, slot_index)
        except (OSError, ValueError, UnicodeError) as exc:
            self._show_load_error(str(exc), key="load.failed")
            return
        if game_state is None:
            return
        if not isinstance(game_state, dict):
            self._show_load_error("Invalid game state")
            return
        version = game_state.get("save_format")
        if type(version) is not int or version not in (3, 4):
            self._show_load_error("Unsupported save format; expected 3 or 4")
            if version is None or (type(version) is int and version < 3):
                self._offer_outdated_save(page, slot_index)
            return
        if (version == 4) != (game_state.get("cards") is not None):
            self._show_load_error("Карточные позиции требуют save format 4 с секцией cards", key="load.cards")
            return

        variables = game_state.get("variables", {})
        scene = game_state.get("scene", {})
        sprites_data = game_state.get("sprites", {})
        dialogue = game_state.get("dialogue", {})
        if not all(
            isinstance(section, dict)
            for section in (variables, scene, sprites_data, dialogue)
        ):
            self._show_load_error("Invalid save section")
            return
        if not isinstance(variables.get("state"), dict):
            self._show_load_error("Invalid script variables")
            return
        from story.parser import normalize_script_state
        try:
            restored_variables = normalize_script_state(variables["state"])
            restored_ending_dates = normalize_ending_dates(game_state.get("ending_dates", {}), restored_variables)
            restored_audio = self.audio.validate_snapshot(game_state.get("audio"))
            scene, sprites_data, dialogue = validate_save_view(game_state)
        except (TypeError, ValueError) as exc:
            self._show_load_error(str(exc), key="load.failed")
            return

        # До изменения текущей игры полностью проверяем файл и runtime-state.
        # Иначе несовпавший hash оставлял новый parser на pc=0 и позволял
        # повторно выполнить уже начисленные поинты.
        script_runtime = game_state.get("script", {})
        if not isinstance(script_runtime, dict):
            self._show_load_error("Invalid script runtime")
            return
        script_filename = script_runtime.get("filename", "")
        if not isinstance(script_filename, str) or not script_filename:
            self._show_load_error("Save has no script filename")
            return

        try:
            if not Path(script_filename).is_absolute():
                script_filename = str(self.ts_path / script_filename)
            loaded_script = ScriptParser(script_filename, self)
            if not loaded_script.restore_runtime_state(script_runtime):
                self._show_load_error(loaded_script.runtime_error,
                                      key="outdated.load" if loaded_script.runtime_outdated else "load.failed")
                if loaded_script.runtime_outdated:
                    self._offer_outdated_save(page, slot_index)
                return
            restored_cards = CardSession.from_save_data(
                game_state.get("cards"), lines=loaded_script.lines, pc=loaded_script.index,
                labels=loaded_script.labels)
            for sprite in sprites_data["active_sprites"].values():
                built = self._build_sprite_png(sprite["show_line"])
                if built is None:
                    raise ValueError(f"Не удалось восстановить спрайт: {sprite['character']}")
                sprite["image_path"] = str(built[1])
        except (OSError, TypeError, ValueError, UnicodeError) as exc:
            self._show_load_error(str(exc), key="load.failed")
            return

        # Закрытие меню сохранений
        from story.parser import get_persistent_state, update_persistent_state
        previous_progress = get_persistent_state()
        self.close_save_menu()

        # Сброс текущего состояния
        self.reset_game_view()

        # Восстановление состояния сценария.
        from story.parser import set_script_state
        set_script_state(restored_variables)
        update_persistent_state(previous_progress)
        # Persistent-флаги не должны откатываться загрузкой старого слота.
        self.load_persistent_state()
        merged_dates = merge_ending_dates(self.ending_dates, restored_ending_dates)
        self.ending_dates = merged_dates
        # Новые флаги могут прийти из старого save без дат.
        self.save_persistent_state()
        self.update_script_header()

        # Восстановление сцены
        self.current_scene = scene.get("current_scene", "")
        self.current_scene_category = scene.get("current_scene_category", "")
        self.current_time = scene.get("current_time", "day")
        self._interface_hidden = False
        self.set_text_mode(scene.get("current_text_mode", "adv"))

        # Восстановление спрайтов
        self._active_sprites = sprites_data["active_sprites"]
        self._sprite_order_seq = sprites_data["sprite_order_seq"]

        # Проверенный выше parser становится активным только после сброса.
        self.script = loaded_script
        self.card_session = restored_cards
        if restored_cards is not None:
            self.query_one(CardTable).replace_game(restored_cards.game)
            self.query_one(CardTable).swap_first = restored_cards.selection
        self.audio.restore(restored_audio)

        # Скрытие главного меню (если загрузка из главного меню)
        if save_menu.opened_from == "menu":
            self.query_one("#main-menu").add_class("hidden")

        # Показ игровых элементов и точное восстановление window show/hide.
        novel_menu = self.query_one("#novel-menu", Widget)
        self.set_novel_menu_visible(True)
        self.query_one("#novel-window").remove_class("hidden")
        novel_menu.set_class(
            not bool(scene.get("window_visible", True)),
            "invisible",
        )
        self.sync_text_mode_display()

        # Восстановление текста и имени персонажа
        text_bar = self.query_one("#text-bar", Widget)
        text_bar.remove_class(*[
            cls for cls in text_bar.classes if cls != "text-bar"
        ])
        text_bar.border_title = dialogue.get("speaker", "")
        text_bar.text = dialogue.get("text", "")
        saved_speaker_id = dialogue.get("speaker_id")
        if saved_speaker_id:
            text_bar.add_class(saved_speaker_id)
        text_bar.refresh()

        # Отрисовка и прогрев выполняются под полноэкранным оверлеем.
        self.mark_scene_dirty()
        self.start_script_preload(self.script)

        # Фокус на кнопку "Вперёд"
        self.query_one("#btn-next", Button).focus()

    def save_to_selected_slot(self) -> None:
        """Сохранение в выбранный слот"""
        save_menu = self.query_one(SaveMenu)
        if not save_menu.selected_slot:
            return

        # Сохранение доступно только из паузы
        if save_menu.opened_from != "pause":
            return

        slot_index = int(save_menu.selected_slot.split("-")[-1])
        page = save_menu.current_page

        # Проверка: можно ли сохранять в текущем состоянии
        if not self.is_savable_game_state():
            return

        from story.parser import get_script_state

        # Текущий текст и имя персонажа из текстового бара
        text_bar = self.query_one("#text-bar", Widget)
        current_speaker = str(text_bar.border_title) if text_bar.border_title else ""
        current_text = text_bar.text if text_bar.text else ""
        # speaker_id - CSS-класс персонажа (sl, un, dv и т.д.)
        speaker_classes = [cls for cls in text_bar.classes if cls != "text-bar"]
        speaker_id = speaker_classes[0] if speaker_classes else None

        # Сбор состояния игры
        script_runtime = self.script.get_runtime_state() if hasattr(self, "script") else {}
        if script_runtime:
            try:
                script_runtime["filename"] = str(
                    Path(script_runtime["filename"]).resolve().relative_to(self.ts_path.resolve())
                )
            except ValueError:
                # Внешний сценарий сохраняем абсолютным путём как крайний случай.
                pass

        game_state = {
            # Старый executable обязан отклонить позицию с картами, а не
            # проигнорировать новую секцию и продолжить TXT после партии.
            "save_format": 4 if self.card_session is not None else 3,
            "ending_dates": self.ending_dates.copy(),
            "audio": self.audio.snapshot(),
            "cards": self._card_save_data(),
            "script": script_runtime,
            "variables": {
                "state": get_script_state(),
            },
            "scene": {
                "current_scene": getattr(self, "current_scene", ""),
                "current_scene_category": getattr(self, "current_scene_category", ""),
                "current_time": getattr(self, "current_time", "day"),
                "current_text_mode": getattr(self, "current_text_mode", "adv"),
                "window_visible": not self.query_one(
                    "#novel-menu", Widget
                ).has_class("invisible"),
            },
            "sprites": {
                "active_sprites": self._active_sprites,
                "sprite_order_seq": self._sprite_order_seq,
            },
            "dialogue": {
                "speaker": current_speaker,
                "speaker_id": speaker_id,
                "text": current_text,
            },
        }

        from datetime import datetime
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        try:
            saves.save_game_state(page, slot_index, game_state, timestamp)
        except (OSError, ValueError, TypeError) as exc:
            strings = save_menu.strings
            self.notify(strings.get("save.failed", str(exc)),
                        title=strings.get("save.error", "Не удалось сохранить игру"), severity="error")
            return

        # Обновление отображения
        save_menu.all_saves = saves.get_all_saves()
        self.update_save_menu_display()

    # ============ Функции - прочие ============
    def on_key(self, event: events.Key) -> None:
        # Обычное всплытие: Input сначала получает буквы сам. Binding нужен
        # Footer, но не должен второй раз исполнить уже обработанное событие.
        if event.key not in {"s", "ы", "S", "Ы"}:
            return
        event.stop()
        event.prevent_default()
        now = event.time
        idle_for = now - self._skip_last_event_at
        self._skip_last_event_at = max(now, self._skip_last_event_at)
        if now <= self._skip_input_after or idle_for < 0.12:
            return
        self.toggle_skipping()

    def _is_script_loading(self) -> bool:
        return self._preloader.running or not self.query_one("#script-loading").has_class("hidden")

    def is_gameplay_context(self, *, allow_preload: bool = False) -> bool:
        """Игровой контекст, независимо от печати/занятости parser-task."""
        if (
            not self.is_running
            or not self.screen_stack
            or not isinstance(getattr(self, "script", None), ScriptParser)
            or not self.app_focus
            or self.screen.id != "_default"
            or self._game_paused
            or self._terminal_too_small
            or self._interface_hidden
            or getattr(self, "pending_choices", None) is not None
        ):
            return False
        if any(not self.query_one(selector).has_class("hidden") for selector in (
            "#main-menu", "#pause-menu", "#log-menu", "#settings-menu",
            "#save-menu", "#gallery-menu", "#endings-menu", "#choice-bar",
        )):
            return False
        if self._is_script_loading():
            return allow_preload
        # NVL скрывает novel-window, а window hide задаёт invisible, не hidden.
        return not self.query_one("#novel-menu").has_class("hidden")

    def can_start_skipping(self) -> bool:
        return self.card_session is None and self._credits is None and self.is_gameplay_context() and not (
            self.script.failed or self.script.finished or self.script.has_diagnostic
        )

    def set_skipping(self, enabled: bool) -> None:
        if not enabled:
            self.stop_skipping()
        elif not self.skipping and self.can_start_skipping():
            self.skipping = True
            self._skip_next_advance_at = _time.get_time() + 0.1
            self._refresh_skip_binding()

    def toggle_skipping(self) -> None:
        self.set_skipping(not self.skipping)

    def action_toggle_skipping(self) -> None:
        self.toggle_skipping()

    def stop_skipping(self) -> None:
        """Не отменяет исполняемый DSL; отсекает ввод из старого контекста."""
        self.skipping = False
        self._skip_input_after = _time.get_time()
        self._refresh_skip_binding()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self._terminal_too_small and action != "quit":
            return False
        if action == "toggle_skipping":
            return self.skipping or self.can_start_skipping()
        return super().check_action(action, parameters)

    def _refresh_skip_binding(self) -> None:
        if not self.is_running or not self.screen_stack:
            return
        available = self.skipping or self.can_start_skipping()
        if available == self._skip_binding_available:
            return
        self._skip_binding_available = available
        self.refresh_bindings()

    def _skip_tick(self) -> None:
        self._refresh_skip_binding()
        if not self.skipping:
            return
        if self._credits is not None or not self.is_gameplay_context(allow_preload=True) or (
            self.script.failed or self.script.finished or self.script.has_diagnostic
        ):
            self.stop_skipping()
            return
        if self._is_script_loading():
            return
        if self.skip_script_delay(automatic=True):
            return
        if self._input_blocked or self._text_animating:
            return
        if _time.get_time() >= self._skip_next_advance_at:
            self._start_script_advance()

    async def key_space(self, event: events.Key) -> None:
        """Обработка пробела как перехода с фильтрацией ввода во время анимации."""
        if (not self.query_one("#gallery-menu").has_class("hidden")
                or not self.query_one("#endings-menu").has_class("hidden")):
            return
        if self._credits is not None:
            self.action_skip_credits()
            event.stop()
            event.prevent_default()
            return
        now = getattr(event, "time", None) or _time.get_time()
        idle_for = now - self._space_last_event_at
        self._space_last_event_at = now

        # Пропуск задержки всегда имеет приоритет над фильтром анимации:
        # <w> находится внутри показа реплики, а pause помечается блокировкой.
        if self.skip_script_delay():
            # Не позволяем автоповтору того же удерживаемого пробела перейти
            # дальше после того, как фоновая задача продолжит сценарий.
            self._space_require_idle = True
            return

        if self._space_require_idle:
            if idle_for < self._space_idle_gap:
                return
            self._space_require_idle = False

        if self._is_space_event_during_animation(event):
            return
        await self.action_next_scene()

    def _load_sprite_resources(self):
        """Ленивая загрузка resources.yaml для сборщика спрайтов."""
        resource_candidates = (
            (self.ts_path / "resources.yaml", self.ts_path / "images"),
            (Path("resources.yaml"), self.ts_path / "images"),
        )
        for candidate, assets_root in resource_candidates:
            if not candidate.exists():
                continue

            try:
                signature = (str(candidate.resolve()), file_signature(candidate))
                if signature == self._sprite_resources_signature:
                    return self._sprite_resources
                self._sprite_resources = load_sprite_resources_yaml(candidate)
                self._sprite_assets_root = assets_root
                self._sprite_resources_signature = signature
            except Exception as e:
                self._sprite_resources = None
                self.sub_title = f"Sprite resources error: {e}"
            return self._sprite_resources

        self._sprite_resources = None
        self.sub_title = "Sprite resources not found"
        return None

    def _sorted_active_sprites(self, active_sprites: dict | None = None) -> list[dict]:
        """Возвращает активные спрайты в порядке от заднего к переднему."""
        source = self._active_sprites if active_sprites is None else active_sprites
        sprites = sorted(source.values(), key=lambda item: item.get("order", 0))
        if len(sprites) <= 1:
            return sprites

        # Учитываем `behind <character>`.
        guard = 0
        max_passes = len(sprites) * len(sprites)
        while guard < max_passes:
            changed = False
            for idx, item in enumerate(list(sprites)):
                behind_id = item.get("behind")
                if not behind_id:
                    continue

                target_idx = next(
                    (i for i, candidate in enumerate(sprites) if candidate.get("character") == behind_id),
                    None,
                )
                if target_idx is None:
                    continue

                if idx > target_idx:
                    sprites.insert(target_idx, sprites.pop(idx))
                    changed = True
                    break

            if not changed:
                break
            guard += 1

        return sprites

    def mark_scene_dirty(self) -> None:
        """Помечает логическую сцену изменённой и инвалидирует старый UI-рендер."""
        self.scene_dirty = True
        self._scene_generation += 1

    def _make_scene_snapshot(
        self,
        category: str,
        name: str,
        active_sprites: dict,
    ) -> SceneRenderSnapshot:
        sprites = tuple(
            RenderSprite(
                character=str(sprite.get("character", "")),
                show_line=str(sprite.get("show_line", "")),
                image_path=str(sprite.get("image_path", "")),
                at=str(sprite.get("at") or "center"),
                size=str(sprite.get("size") or "normal"),
                behind=sprite.get("behind"),
                order=int(sprite.get("order", 0)),
            )
            for sprite in self._sorted_active_sprites(active_sprites)
            if self.settings.get("scene_filters_enabled", True)
            or sprite.get("character") not in SCENE_FILTER_IDS
        )
        return SceneRenderSnapshot(
            category=category,
            name=name,
            sprites=sprites,
            width=int(self.settings.get("quality", 150)),
            style=str(self.settings.get("style", "ANSI")),
            cache_epoch=self._renderer.cache.epoch,
            diagnostics=(
                self.runtime_ui.get("scene.unknown-color", "Неизвестный цвет сцены"),
                self.runtime_ui.get("scene.missing", "Файл не найден"),
                self.runtime_ui.get("scene.error"),
            ),
        )

    def _capture_scene_snapshot(self) -> SceneRenderSnapshot:
        return self._make_scene_snapshot(
            getattr(self, "current_scene_category", ""),
            getattr(self, "current_scene", ""),
            {key: value.copy() for key, value in self._active_sprites.items()},
        )

    async def _get_render_async(self, snapshot: SceneRenderSnapshot) -> Text:
        return await self._renderer.get(snapshot, self.ts_path)

    def _snapshot_after_visual_commands(
        self, commands: tuple[str, ...]
    ) -> SceneRenderSnapshot | None:
        """Строит снимок будущего кадра без изменения настоящей сцены."""
        category = getattr(self, "current_scene_category", "")
        name = getattr(self, "current_scene", "")
        active = {key: value.copy() for key, value in self._active_sprites.items()}
        order_seq = self._sprite_order_seq

        for line in commands:
            color_match = re.search(
                r"scene\s+color\s+([a-zA-Z0-9_#]+)", line
            )
            if color_match:
                category = "color"
                name = color_match.group(1).lower()
                active.clear()
                order_seq = 0
                continue
            scene_match = re.search(
                r"scene\s+(cg|bg)\s+([a-zA-Z0-9_]+)", line
            )
            if scene_match:
                category, name = scene_match.groups()
                active.clear()
                order_seq = 0
                continue
            if line.startswith("show "):
                built = self._build_sprite_png(line)
                if built is None:
                    continue
                request, out_path = built
                previous = active.get(request.character)
                if previous is None:
                    order_seq += 1
                    order = order_seq
                else:
                    order = previous.get("order", 0)
                active[request.character] = {
                    "character": request.character,
                    "show_line": line,
                    "image_path": str(out_path),
                    "at": request.at or (previous.get("at") if previous else "center"),
                    "size": request.size or (
                        previous.get("size") if previous else "normal"
                    ),
                    "behind": request.extras.get("behind") if request.extras else None,
                    "order": order,
                }
                continue
            hide_match = re.search(r"hide\s+([a-zA-Z0-9_]+)", line)
            if hide_match:
                active.pop(hide_match.group(1), None)

        if not name or not category:
            return None
        return self._make_scene_snapshot(category, name, active)

    def prefetch_next_scene(self, script: ScriptParser) -> None:
        """Готовит следующий детерминированный кадр, пока читается диалог."""
        commands = script.predict_visual_commands()
        self._renderer.prefetch(self._snapshot_after_visual_commands(commands), self.ts_path)

    def prefetch_choice_scenes(self, script: ScriptParser, choices) -> None:
        """Готовит первый кадр каждой доступной ветки во время выбора."""
        for choice in choices:
            commands = script.predict_choice_visual_commands(choice)
            self._renderer.prefetch(self._snapshot_after_visual_commands(commands), self.ts_path)

    async def flush_scene_render(self) -> None:
        """Рендерит сцену только в момент, когда её действительно увидит игрок."""
        if self.card_session is not None:
            self.sync_card_view()
            generation = self._scene_generation
            await self.refresh_card_scene()
            if generation == self._scene_generation:
                self.scene_dirty = False
            return
        if not self.scene_dirty:
            return
        if not getattr(self, "current_scene", ""):
            self.query_one("#bg-cg", Widget).update("")
            self.scene_dirty = False
            return
        generation = self._scene_generation
        snapshot = self._capture_scene_snapshot()
        art = await self._get_render_async(snapshot)
        if generation != self._scene_generation:
            return
        self.query_one("#bg-cg", Widget).update(art)
        self.scene_dirty = False

    def start_script_preload(self, script: ScriptParser) -> asyncio.Task[None]:
        """Неблокирующе прогревает чистые фоны активного сценарного файла."""
        return self._preloader.start(
            script.filename, lambda generation: self._preload_script_scenes(script, generation),
        )

    def clear_script_cache(self) -> None:
        """Останавливает прогрев и освобождает кэш при выходе из игры."""
        self._preloader.clear()
        self._loading_restore_novel = False
        try:
            self.query_one("#script-loading", Widget).add_class("hidden")
        except Exception:
            pass

    async def _preload_script_scenes(self, script: ScriptParser, generation: int) -> None:
        overlay = self.query_one("#script-loading", Widget)
        label = self.query_one("#script-loading-text", Label)
        scenes = script.resource_manifest.get("scenes", ())
        show_lines = script.resource_manifest.get("show_lines", ())
        novel_menu = self.query_one("#novel-menu", Widget)
        novel_window = self.query_one("#novel-window", Widget)
        self._loading_restore_novel = (
            not novel_menu.has_class("hidden") or not novel_window.has_class("hidden")
        )
        if self._loading_restore_novel:
            self.set_novel_menu_visible(False)
            novel_window.add_class("hidden")
        overlay.remove_class("hidden")

        def report(phase: str, number: int, total: int) -> None:
            if phase == "scenes":
                title = self.runtime_ui.get("preload.story", "Подготовка сценария")
            else:
                title = self.runtime_ui.get("preload.sprites", "Подготовка спрайтов")
            label.update(f"{title}: {number}/{total}")

        try:
            await self._preloader.warm_resources(
                generation, scenes, show_lines, ts_path=self.ts_path,
                make_snapshot=lambda category, name: self._make_scene_snapshot(category, name, {}),
                build_sprite=self._build_sprite_png, report=report,
            )
            if self._preloader.is_current(generation):
                current_snapshot = self._capture_scene_snapshot()
                if current_snapshot.name and current_snapshot.category:
                    label.update(self.runtime_ui.get("preload.current", "Подготовка текущего кадра…"))
                    current_art = await self._get_render_async(current_snapshot)
                    if self._preloader.is_current(generation):
                        self.query_one("#bg-cg", Widget).update(current_art)
                        self.scene_dirty = False
                label.update(self.runtime_ui.get("preload.next", "Подготовка следующего кадра…"))
                snapshot = self._snapshot_after_visual_commands(
                    script.predict_visual_commands()
                )
                if snapshot is not None:
                    await self._get_render_async(snapshot)
        finally:
            if self.is_running and self._preloader.is_current(generation):
                if not self.skipping:
                    # Запоздавшая S, введённая под оверлеем, не запускает skip
                    # после прогрева. Активному режиму оставляем возможность stop.
                    self._skip_input_after = _time.get_time()
                overlay.add_class("hidden")
                if self._loading_restore_novel:
                    self.set_novel_menu_visible(True)
                    novel_window.remove_class("hidden")
                    self.sync_text_mode_display()
                    self.query_one("#btn-next", Button).focus()
                self._loading_restore_novel = False

    def show_sprite_from_script_line(self, show_line: str):
        """Собирает PNG спрайта из show-строки и обновляет активный набор спрайтов."""
        built = self._build_sprite_png(show_line)
        if built is None:
            return None
        request, out_path = built

        previous = self._active_sprites.get(request.character)
        if previous is None:
            self._sprite_order_seq += 1
            order = self._sprite_order_seq
        else:
            order = previous.get("order", 0)

        self._active_sprites[request.character] = {
            "character": request.character,
            "show_line": show_line,
            "image_path": str(out_path),
            "at": request.at or (previous.get("at") if previous else "center"),
            "size": request.size or (previous.get("size") if previous else "normal"),
            "behind": request.extras.get("behind") if request.extras else None,
            "order": order,
        }

        return None

    def _build_sprite_png(self, show_line: str, generation: int | None = None):
        """Собирает или получает из кэша PNG, не изменяя состояние сцены."""
        cache = self._renderer.cache
        epoch = cache.epoch
        if generation is not None and not self._preloader.is_current(generation):
            return None
        resources = self._load_sprite_resources()
        if not resources:
            return None

        try:
            request = parse_show_like(show_line)
            resolved = resolve_sprite(resources, request, self._sprite_assets_root)
            root = self._sprite_assets_root.resolve()
            if any(not pick.absolute_path.resolve().is_relative_to(root) for pick in resolved.picks):
                raise ValueError("Слой спрайта выходит за пределы TS/images")
            layers = [(pick.layer_name, pick.part_name, str(pick.absolute_path.resolve()),
                        cache.asset_fingerprint(pick.absolute_path, epoch)) for pick in resolved.picks]
            digest = hashlib.sha256(repr(("sprite-v3", show_line, layers)).encode("utf-8")).hexdigest()
            runtime_dir = self._sprite_runtime_dir
            try:
                runtime_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                temporary_root = Path("/tmp/opencode") if Path("/tmp/opencode").is_dir() else Path(tempfile.gettempdir())
                runtime_dir = temporary_root / "terminal-summer-sprites/generated_runtime"
                runtime_dir.mkdir(parents=True, exist_ok=True)
            out_path = runtime_dir / f"{request.character}_{digest}.png"
            if not cache.valid_generated_sprite(out_path, epoch):
                sprite_img = compose_layers(resolved.picks, request.extras.get("spritecolor"))
                try:
                    with atomic_output(out_path) as target:
                        sprite_img.save(target, format="PNG")
                finally:
                    sprite_img.close()
        except Exception as e:
            self.sub_title = f"Sprite build error: {e}"
            return None
        return request, out_path

    def hide_sprite_by_id(self, character_id: str):
        """Удаляет персонажа со сцены."""
        self._active_sprites.pop(character_id, None)
        return None

    def clear_active_sprites(self):
        """Очищает активные спрайты сцены."""
        self._active_sprites.clear()
        self._sprite_order_seq = 0

    def load_persistent_state(self) -> bool:
        """Загружает общие для всех прохождений сценарные флаги."""
        try:
            progress = read_progress(self.PERSISTENT_FILE)
            if progress is None:
                self._persistent_read_error = False
                return False
            from story.parser import update_persistent_state

            flags, dates = progress
            update_persistent_state(flags)
            self.ending_dates = merge_ending_dates(self.ending_dates, dates)
            self._persistent_read_error = False
            self.update_script_header()
            return True
        except (OSError, ValueError, TypeError) as exc:
            self._persistent_read_error = True
            self.sub_title = f"[Persistent state error] {exc}"
            return False

    def record_ending_unlock(self, flag: str) -> None:
        """Вызывается только при сценарном переходе False → True, не при загрузке."""
        from story.parser import ENDING_STATE_KEYS, get_persistent_state

        if flag in ENDING_STATE_KEYS and get_persistent_state().get(flag) is True:
            self._new_ending_flags.add(flag)
            if flag not in self.ending_dates:
                self.ending_dates[flag] = ending_unlock_time()

    def save_persistent_state(self) -> None:
        """Атомарно сохраняет persistent-флаги рядом с настройками."""
        from story.parser import get_persistent_state

        try:
            write_progress(self.PERSISTENT_FILE, get_persistent_state(), self.ending_dates,
                           backup_invalid=self._persistent_read_error)
            self._persistent_read_error = False
        except OSError as exc:
            self.sub_title = f"[Persistent state error] {exc}"
            self.notify(self.runtime_ui.get("file.write-error", str(exc)),
                        title=self.runtime_ui.get("progress.error", "Не удалось сохранить прогресс"), severity="error")

    def update_script_header(self) -> None:
        """Обновляет Header согласно выбранным группам сценарных переменных."""
        self.sub_title = format_script_state(
            include_lp_points=bool(
                self.settings.get("header_lp_points", True)
            ),
            include_flags=bool(self.settings.get("header_flags", True)),
        )

    def load_settings(self):
        """Дополняет старый config; ошибочный файл заменяет полными defaults."""
        self._settings_read_error = False
        try:
            self.settings, needs_write = settings_storage.read_settings(self.CONFIG_FILE, self.DEFAULT_SETTINGS)
            if needs_write:
                self.save_settings()
        except (OSError, ValueError, UnicodeError) as exc:
            self.settings = self.DEFAULT_SETTINGS.copy()
            self._settings_read_error = True
            self.save_settings()
            detail = ("Используются настройки по умолчанию; файл не удалось перезаписать."
                      if self._settings_read_error else "Файл настроек сброшен к значениям по умолчанию.")
            self.notify(f"{detail} {exc}", title="Ошибка настроек", severity="warning", timeout=10)
    
    def save_settings(self):
        """Сохранение настроек"""
        try:
            settings_storage.write_settings(self.CONFIG_FILE, self.settings, backup_invalid=self._settings_read_error)
            self._settings_read_error = False
        except (OSError, ValueError, TypeError) as exc:
            self.notify(self.runtime_ui.get("file.write-error", str(exc)),
                        title=self.runtime_ui.get("settings.error", "Не удалось сохранить настройки"), severity="error")

    def apply_settings(self):
        """Применение настроек при старте"""
        self.apply_language()
        self.apply_audio_settings()
        menu = self.query_one(SettingsMenu)
        header = self.settings["header"]
        self.query_one("Header").set_class(not header, "hidden")
        menu.sync_header_buttons(header)
        menu.sync_header_filter_buttons(self.settings)
        self.update_script_header()

        menu.sync_quality_buttons(self.settings["quality"], clear_others=False)
        menu.sync_art_style_buttons(self.settings["style"])
        menu.sync_scene_filter_buttons(self.settings["scene_filters_enabled"])

        text_speed = self.settings["text_speed"]
        self.text_speed = float(text_speed)
        menu.sync_speed_buttons(text_speed, clear_others=False)

    def set_language(self, language: str | None) -> None:
        if language is None or language not in LANGUAGE_NAMES or language == self.settings["language"]:
            return
        self.settings["language"] = language
        self.apply_language()
        self.save_settings()

    def apply_language(self) -> None:
        language = self.settings["language"]
        roots = [self.ts_path / "text"]
        if self.bundled_text_path is not None:
            roots.append(self.bundled_text_path)
        self.interface_locale = load_interface_locale(language, *roots)
        self.runtime_ui = load_interface_locale(language, *roots, filename="runtime-ui.json")
        pause = self.query_one(PauseMenuContainer)
        pause.border_title = self.runtime_ui.get("pause.title", PauseMenuContainer.BORDER_TITLE)
        self.query_one("#script-loading-text", Label).update(
            self.runtime_ui.get("preload.initial", "Подготовка сценария…")
        )
        for warning in self.query(TerminalSizeWarning):
            warning.update_size(self.size)
        announcements = load_interface_locale(language, *roots, filename="main-menu.json")
        settings_copy = load_interface_locale(language, *roots, filename="settings-menu.json")
        self.endings_locale = load_interface_locale(language, *roots, filename="endings-menu.json")
        settings_menu = self.query_one(SettingsMenu)
        settings_menu.apply_language(settings_copy)
        self.query_one(EndingsMenu).apply_language(self.endings_locale)
        self.query_one(SaveMenu).apply_language(load_interface_locale(language, *roots, filename="save-menu.json"))
        self.update_save_menu_display()
        self.query_one(GalleryMenu).apply_language(load_interface_locale(language, *roots, filename="gallery-menu.json"))
        self.apply_footer_language(load_interface_locale(language, *roots, filename="footer.json"))
        main_menu = self.query_one(MainMenu)
        main_menu.sync_language_button(language)
        settings_menu.sync_language_buttons(language)
        main_menu.apply_language(language, announcements)
        self.query_one(NovelMenu).apply_language(language)
        pause.apply_language(language)

    def apply_footer_language(self, strings: dict[str, str]) -> None:
        # Keep Textual's active bindings, keyboard aliases and keymap behavior intact.
        originals = {binding.id: binding.description for binding in self.BINDINGS}
        bindings = self._bindings.key_to_bindings
        changed = False
        for key, entries in bindings.items():
            updated = [
                replace(binding, description=strings.get(binding.id, originals[binding.id]))
                if binding.id in originals else binding
                for binding in entries
            ]
            if updated != entries:
                bindings[key] = updated
                changed = True
        if changed:
            self.refresh_bindings()

    def apply_audio_settings(self) -> None:
        self.settings.update(normalize_audio_settings(self.settings))
        self.audio.set_settings(self.settings)
        self.query_one(SettingsMenu).sync_audio_controls(self.settings)
        self.query_one(MusicRoom).update_player()

    def load_gallery_images(self):
        """Загружает явно выбранные изображения из общего каталога TS/images."""
        previous_id = (
            self.gallery_images[self.gallery_index].id
            if self.gallery_images and 0 <= self.gallery_index < len(self.gallery_images)
            else None
        )
        try:
            if self._gallery_catalog is None:
                self._gallery_catalog = load_gallery_catalog(
                    get_resource_path("gallery_manifest.json")
                )
            self.gallery_images = list(self._gallery_catalog[self.gallery_mode])
            self._gallery_error = None
        except (OSError, ValueError, KeyError) as exc:
            self.gallery_images = []
            self._gallery_error = f"Ошибка каталога галереи: {exc}"
        self.gallery_index = next(
            (index for index, image in enumerate(self.gallery_images) if image.id == previous_id),
            0,
        )

    def update_gallery_display(self):
        """Показывает текущее изображение в выбранном размере и формате."""
        gallery = self.query_one(GalleryMenu)
        strings = gallery.strings
        if not self.gallery_images:
            if self._gallery_error:
                gallery.show_art(Text(strings.get("gallery.catalog-error", self._gallery_error)))
                title = strings.get("gallery.error-title", "Ошибка")
            else:
                gallery.show_art(Text(strings.get("gallery.empty", "[Ничего не найдено]")))
                title = strings.get("gallery.empty-title", "Пусто")
            gallery.set_art_title(title)
            return

        image = self.gallery_images[self.gallery_index]

        def image_error(key: str, reason: str) -> None:
            fallback = f"[Ошибка изображения {image.id}: {reason}]"
            gallery.show_art(Text(strings.get(key, fallback).replace("{image}", image.id)))

        try:
            image_path = resolve_gallery_image(self.ts_path / "images", image)
            with Image.open(image_path) as img:
                art = render_art(img, width=int(self.gallery_size), alpha=True, style=self.gallery_style)
            gallery.show_art(art)
        except FileNotFoundError:
            image_error("gallery.image-missing", "файл не найден")
        except PermissionError:
            image_error("gallery.image-permission", "нет доступа к файлу")
        except OSError:
            image_error("gallery.image-read", "не удалось прочитать файл изображения")
        except Exception:
            image_error("gallery.image-render", "не удалось загрузить или преобразовать изображение")
        gallery.set_art_title(image.id)

    async def update_current_scene_art(self):
        """Перерисовывает текущий арт при смене размера или стиля."""
        await self.refresh_camp_map()
        if not hasattr(self, "current_scene") or not self.current_scene:
            return
        if not hasattr(self, "current_scene_category") or not self.current_scene_category:
            return

        self.mark_scene_dirty()
        await self.flush_scene_render()

        # Для новых параметров ANSI/ASCII прогреваем только активный файл.
        if hasattr(self, "script"):
            settings_menu = self.query_one("#settings-menu", Widget)
            if settings_menu.has_class("hidden"):
                self.start_script_preload(self.script)
            else:
                self._preload_after_settings = True

    def start_credits(self, script: ScriptParser, duration: float) -> None:
        from story.parser import get_script_state

        ending = current_ending(get_script_state())
        timeline = CreditsTimeline(duration)
        self._credit_ending = ending
        self._credits_script = script
        self._credits = timeline
        self.stop_skipping()
        self._interface_hidden = False
        self.set_text_mode("adv")
        menu = self.query_one("#novel-menu")
        menu.remove_class("hidden", "invisible")
        menu.add_class("credits-mode")
        menu.screen.add_class("rolling-credits")
        self.show_credit_page()
        # Скрытые сюжетные кнопки больше не должны удерживать фокус.
        self.set_focus(None)

    def show_credit_page(self) -> None:
        if self._credits is None:
            return
        bar = self.query_one("#text-bar", TextBar)
        bar.remove_class(*list(bar.classes))
        bar.border_title = ""
        page = self._credits.page
        bar.text = self.endings_locale.get(f"credits.{page}", CREDIT_PAGES[page])
        bar.scroll_home(animate=False)
        bar.refresh()

    async def wait_credit_pause(
        self, script: ScriptParser, seconds: float, *, skippable: bool = True
    ) -> None:
        timeline = self._credits
        remaining = seconds
        while (remaining > 1e-6 and timeline is not None
               and self._credits_script is script and not script.credits_skipped):
            page = timeline.page
            delay = timeline.next_delay(remaining)
            await self.wait_script_delay(
                delay, "pause" if skippable else "hard_pause", skippable=skippable
            )
            if (self._credits is not timeline or self._credits_script is not script
                    or script.credits_skipped):
                return
            timeline.advance(delay)
            remaining -= delay
            if timeline.page != page:
                self.show_credit_page()

    def action_skip_credits(self) -> None:
        if self._credits_script is None or not self.is_gameplay_context():
            return
        script = self._credits_script
        if script.skip_credits():
            self.stop_skipping()
            self.cancel_script_delay()
            if not self._next_scene_in_progress:
                self._start_script_advance()

    def stop_credits(self) -> None:
        self._credits = None
        self._credits_script = None
        self._credit_ending = None
        menu = self.query_one("#novel-menu")
        menu.remove_class("credits-mode")
        menu.screen.remove_class("rolling-credits")

    def finish_game(self, script: ScriptParser) -> None:
        if self._credits_script is not script:
            return
        ending = self._credit_ending
        newly_unlocked = ending.flag in self._new_ending_flags
        self._new_ending_flags.discard(ending.flag)
        self.stop_skipping()
        self.stop_credits()
        self.set_novel_menu_visible(False)
        self._menu_music_active = False
        self.audio.reset()
        self.push_screen(
            EndingResult(ending, newly_unlocked=newly_unlocked, date=self.ending_dates.get(ending.flag),
                         strings=self.endings_locale),
            self.return_from_ending,
        )

    def return_from_ending(self, result=None) -> None:
        self.reset_game_view()
        self.action_open_menu()

    def reset_game_view(self):
        """Сбрасывает визуальное состояние игры перед выходом в меню"""
        self.stop_credits()
        self.close_card_game()
        self._new_ending_flags.clear()
        self._menu_music_active = False
        self.audio.reset()
        self.query_one("#gallery-menu").add_class("hidden")
        self.query_one("#endings-menu").add_class("hidden")
        self.set_game_paused(False)
        self.cancel_script_advance()
        # Отменённый парсер больше не считается активным: его finally-блоки
        # не смогут восстановить элементы UI уже сброшенной или новой игры.
        if hasattr(self, "script"):
            del self.script

        # Получаем элементы
        text_bar = self.query_one("#text-bar", Widget)
        bg_cg = self.query_one("#bg-cg", Widget)
        novel_menu = self.query_one("#novel-menu", Widget)
        novel_window = self.query_one("#novel-window", Widget)
        next_button = self.query_one("#btn-next", Button)
        self.query_one("#settings-menu").remove_class(
            "open-from-pause", "open-from-menu"
        )

        # Очистка текста и имени персонажа
        text_bar.text = ""
        text_bar.border_title = ""
        text_bar.refresh()

        # Во время анимации реплики кнопка скрыта. Отменённый старый parser-task
        # не должен менять UI загруженного сценария, поэтому нормализуем кнопку
        # здесь явно до восстановления сохранения или запуска новой игры.
        next_button.remove_class("invisible")
        next_button.disabled = False

        # Очистка ASCII-фона
        bg_cg.update("")
        self.clear_active_sprites()
        self.current_scene = ""
        self.current_scene_category = ""
        self.current_time = "day"
        self.scene_dirty = False
        self.clear_script_cache()

        # Очистка pending_choices
        if hasattr(self, "pending_choices"):
            self.pending_choices = None
        self.query_one(ChoiceBar).close()

        # Очистка истории диалогов
        self.clear_log()

        # Сброс блокировки перехода по строкам
        self._next_scene_in_progress = False
        self._text_animating = False
        self._text_animating_since = None
        self._text_animating_until = 0.0
        self._input_blocked = False
        self._input_blocked_since = None
        self._input_blocked_until = 0.0
        self._space_last_event_at = 0.0
        self._space_require_idle = False
        self._interface_hidden = False
        self.set_text_mode("adv")
        novel_menu.remove_class("invisible")
        self.set_novel_menu_visible(False)
        novel_window.add_class("hidden")

    def can_advance_scene(self) -> bool:
        """Можно ли переходить к следующей строке по пользовательскому вводу."""
        if self._terminal_too_small or self._next_scene_in_progress:
            return False
        if self.card_session is not None and self.card_session.playing:
            return False
        if self._text_animating:
            return False
        if not hasattr(self, "script"):
            return False

        if self.query_one("#novel-menu").has_class("hidden"):
            return False
        if not self.query_one("#choice-bar").has_class("hidden"):
            return False
        if self.query_one("#btn-next", Button).has_class("invisible"):
            return False

        return True
    
    async def _advance_from_button(self) -> None:
        """Переключение по кнопке (без анти-repeat логики клавиатуры)."""
        await self._advance_script_line()

    def _is_space_event_during_animation(self, event: events.Key) -> bool:
        """True если событие пробела было сгенерировано во время блокировки ввода."""
        if self._text_animating or self._input_blocked:
            return True

        event_time = getattr(event, "time", None)
        if event_time is None:
            return False

        if (
            self._text_animating_since is not None
            and self._text_animating_since <= event_time <= self._text_animating_until
        ):
            return True

        if (
            self._input_blocked_since is not None
            and self._input_blocked_since <= event_time <= self._input_blocked_until
        ):
            return True

        return False

    async def _advance_script_line(self) -> None:
        """Запрашивает выполнение следующей строки без блокировки очереди UI."""
        if self._credits is not None:
            return
        if self.skip_script_delay():
            return
        self._start_script_advance()

    def _start_script_advance(self) -> bool:
        """Запускает единственную фоновую цепочку выполнения сценария."""
        if self._next_scene_in_progress:
            return False
        if not hasattr(self, "script"):
            return False
        if not self.can_advance_scene():
            return False

        self._next_scene_in_progress = True
        # Любой успешный запрос, включая ручной, отодвигает следующий skip-шаг.
        self._skip_next_advance_at = _time.get_time() + 0.1
        task = asyncio.create_task(self.script.next_line())
        self._script_advance_task = task
        task.add_done_callback(self._on_script_advance_done)
        return True

    def _on_script_advance_done(self, task: asyncio.Task) -> None:
        """Освобождает переход после завершения только актуальной задачи."""
        is_current = self._script_advance_task is task
        if is_current:
            self._script_advance_task = None
            self._next_scene_in_progress = False
            self.sync_card_view()

        if task.cancelled():
            return

        try:
            task.result()
        except Exception as exc:
            # Исключение уже извлечено из Task и не останется незамеченным.
            if is_current:
                self.script._report_script_error(str(exc))
                self.sync_card_view()

    def set_game_paused(self, paused: bool) -> None:
        """Меняет состояние паузы и будит ожидающие сценарные задачи."""
        paused = bool(paused)
        if paused:
            self.stop_skipping()
        if self._game_paused == paused:
            return
        self._game_paused = paused
        self._signal_game_pause_changed()

    def _signal_game_pause_changed(self) -> None:
        previous_event = self._game_pause_changed_event
        self._game_pause_changed_event = asyncio.Event()
        previous_event.set()

    async def wait_until_game_resumed(self) -> None:
        """Не даёт сценарию и анимации текста идти под меню паузы."""
        while self._game_paused or self._terminal_too_small:
            pause_changed = self._game_pause_changed_event
            await pause_changed.wait()

    async def wait_script_delay(
        self, seconds: float, kind: str, *, skippable: bool = True
    ) -> bool:
        """Ждёт задержку; skippable ограничивает только ручное «Далее»."""
        if seconds <= 0:
            return False

        delay_event = asyncio.Event()
        self._script_delay_generation += 1
        generation = self._script_delay_generation
        self._script_delay_event = delay_event
        self._script_delay_kind = kind
        self._script_delay_skippable = skippable
        self._input_blocked = True
        self._input_blocked_since = _time.get_time()
        self._input_blocked_until = self._input_blocked_since

        remaining = seconds
        try:
            await self.wait_until_game_resumed()
            if self.skipping and not self._is_script_loading():
                await asyncio.sleep(0)
                await self.wait_until_game_resumed()
                if self.skipping:
                    return True
            while remaining > 0:
                await self.wait_until_game_resumed()
                started_at = _time.get_time()
                pause_changed = self._game_pause_changed_event
                delay_task = asyncio.create_task(delay_event.wait())
                pause_task = asyncio.create_task(pause_changed.wait())
                try:
                    done, pending = await asyncio.wait(
                        (delay_task, pause_task),
                        timeout=remaining,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for task in (delay_task, pause_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        delay_task, pause_task, return_exceptions=True
                    )

                elapsed = max(0.0, _time.get_time() - started_at)
                remaining = max(0.0, remaining - elapsed)
                if delay_event.is_set():
                    return True
                if not done:
                    return False
            return False
        finally:
            # Старая отменённая задача не должна очищать состояние новой паузы.
            if (
                self._script_delay_event is delay_event
                and self._script_delay_generation == generation
            ):
                self._script_delay_event = None
                self._script_delay_kind = None
                self._script_delay_skippable = False
                self._input_blocked = False
                self._input_blocked_until = _time.get_time()

    def skip_script_delay(self, *, automatic: bool = False) -> bool:
        """Завершает задержку; активный автопропуск разрешает и hard pause."""
        delay_event = self._script_delay_event
        if (
            self._game_paused
            or self._terminal_too_small
            or delay_event is None
            or (not self._script_delay_skippable and not (automatic and self.skipping))
            or delay_event.is_set()
        ):
            return False
        delay_event.set()
        return True

    def cancel_script_delay(self) -> None:
        """Сбрасывает ожидание при отмене или смене сценария."""
        delay_event = self._script_delay_event
        self._script_delay_generation += 1
        self._script_delay_event = None
        self._script_delay_kind = None
        self._script_delay_skippable = False
        self._input_blocked = False
        self._input_blocked_since = None
        self._input_blocked_until = _time.get_time()
        if delay_event is not None:
            delay_event.set()

    def cancel_script_advance(self) -> None:
        """Отменяет старое выполнение сценария и его активную задержку."""
        self.stop_skipping()
        task = self._script_advance_task
        self._script_advance_task = None
        self._next_scene_in_progress = False
        self.cancel_script_delay()
        if task is not None and not task.done():
            task.cancel()

    def add_log_entry(
        self,
        text: str,
        speaker: str = "",
        speaker_id: str | None = None,
    ) -> None:
        if not text:
            return
        self.query_one("#log-menu", LogMenu).add_dialogue_entry(
            text=text,
            speaker=speaker,
            speaker_id=speaker_id,
        )

    def clear_log(self) -> None:
        self.query_one("#log-menu", LogMenu).clear()
