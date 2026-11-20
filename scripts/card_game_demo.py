#!/usr/bin/env python3
"""Сюжетный стенд карточного турнира второго дня, без сохранения прогресса."""

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rich.text import Text
from textual import events
from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from art_renderer import ART_STYLES
from cards.game import CardGame, Phase, RIVAL_NAMES
from cards.demo_story import CardStory
from cards.table import CardTable, render_card_scene
from console_button import ConsoleButton as Button
from main import NovelMenu, TextBar
from story.parser import DISPLAY_NAMES
from terminal_size import MINIMUM_TERMINAL_SIZE, TerminalSizeWarning


class DemoDialog(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", show=False)]

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self):
        with Vertical(id="card-demo-dialog"):
            yield Static("История", id="card-demo-dialog-title")
            with VerticalScroll():
                yield Static(Text(self.text))
            yield Button("Закрыть", id="card-dialog-close")

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss()


class CardGameDemo(App):
    CSS_PATH = str(ROOT / "src/gameUI.tcss")
    TITLE = "Terminal Summer"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("space", "confirm", "Далее", priority=True),
        Binding("h", "history", "История"),
        Binding("escape", "quit", "Выход"),
        Binding("m", "style", show=False),
        Binding("r", "restart", show=False),
    ]
    COMPUTER_DELAY = 0.65

    def __init__(self, *, rival=None, style="ANSI", seed=None, decorations=True):
        super().__init__()
        self.start_rival = rival
        self.card_style = style
        self.seed = seed
        self.decorations = decorations
        self.story = CardStory(seed=seed, rival=rival)
        self._auto_key = None
        self._move_due = 0.0
        self._last_line = None
        self._was_dialogue = True
        self._scene_key = None
        self.asset_note = ""

    def compose(self):
        yield Static("", id="card-story-scene", markup=False)
        yield CardTable(self.story.game or CardGame(seed=self.seed), ts_path=ROOT / "TS",
                        style=self.card_style, show_scenery=self.decorations, id="demo-card-table")
        yield NovelMenu(id="novel-menu")
        yield Footer()
        yield TerminalSizeWarning()

    def on_mount(self):
        self.screen.add_class("card-demo-screen")
        self.sync_geometry(self.size)
        self.sync_view()
        self.set_interval(0.1, self._tick)

    @property
    def table(self) -> CardTable:
        return self.screen_stack[0].query_one(CardTable)

    def on_resize(self, event: events.Resize):
        self.sync_geometry(event.size)
        if self.screen_stack[0].query(CardTable):
            self.call_after_refresh(self.sync_view)

    def sync_geometry(self, size):
        screen = self.screen_stack[0]
        small = size.width < MINIMUM_TERMINAL_SIZE.width or size.height < MINIMUM_TERMINAL_SIZE.height
        screen.set_class(small, "terminal-too-small")
        screen.set_class(size.width < 110, "compact-terminal")
        screen.query_one(TerminalSizeWarning).update_size(size)

    def _available(self):
        return (self.is_running and not isinstance(self.screen, ModalScreen)
                and not self.screen.has_class("terminal-too-small"))

    def sync_view(self):
        story = self.story
        screen = self.screen_stack[0]
        table = self.table
        new_game = story.game is not None and table.game is not story.game
        if new_game:
            table.replace_game(story.game)
        table.display = story.on_table
        screen.set_class(story.on_table and story.dialogue is not None, "card-story-dialogue")
        table.input_enabled = story.on_table and story.dialogue is None and self._available() and not story.done
        table.player_visible = story.player_visible
        table.targets_visible = story.targets_visible
        table.scene = story.scene
        table.rival_name = "Пробная игра" if story.stage == "tutorial" else None
        table.card_style = self.card_style
        if story.on_table:
            table.sync()
        screen.query_one("#card-story-scene").display = not story.on_table
        screen.query_one("#novel-menu").set_class(story.dialogue is None, "invisible")
        night = story.scene.name.endswith("_night")
        self.set_class(not night, "time-sunset")
        self.set_class(night, "time-night")
        if story.dialogue is not None:
            current = story.dialogue
            text_bar = screen.query_one(TextBar)
            text_bar.remove_class("el", "un", "us", "dv", "me")
            if current.speaker in {"el", "un", "us", "dv", "me"}:
                text_bar.add_class(current.speaker)
            text_bar.border_title = DISPLAY_NAMES.get(current.speaker, "")
            text = f"~ {current.text} ~" if current.speaker == "th" else current.text
            text_bar.text = Text(text).markup
            if current is not self._last_line:
                text_bar.scroll_home(animate=False)
                screen.query_one("#btn-next").focus()
                self._last_line = current
            self._was_dialogue = True
        elif self._was_dialogue or new_game:
            table.focus_active_hand()
            self._was_dialogue = False
        if not story.on_table:
            self._render_scene()

    def _render_scene(self):
        available_height = max(1, self.size.height - 7)
        width = min(150, max(1, self.size.width - 2), max(1, int(available_height * 32 / 9)))
        key = self.story.scene, self.card_style, width
        if key == self._scene_key:
            return
        self._scene_key = key
        art = Text("")
        if self.decorations:
            try:
                art = render_card_scene(ROOT / "TS", *key).copy()
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                self.asset_note = str(exc)
        self.screen_stack[0].query_one("#card-story-scene", Static).update(art)

    def on_card_table_changed(self, event: CardTable.Changed):
        event.stop()
        if event.game is self.story.game:
            self.story.poll()
            self.sync_view()

    def on_card_table_finished(self, event: CardTable.Finished):
        event.stop()

    def on_card_table_result_accepted(self, event: CardTable.ResultAccepted):
        event.stop()
        self.action_confirm()

    def _tick(self):
        game = self.story.game
        if (not self._available() or self.story.dialogue is not None or not self.story.on_table
                or game is None or game.phase not in {Phase.RIVAL_TAKE, Phase.RIVAL_DEFEND, Phase.PLAYER_TAKE}):
            self._auto_key = None
            return
        key = id(game), game.round, game.phase, game.swaps_left, game.opponent_target
        if key != self._auto_key:
            self._auto_key = key
            self._move_due = time.monotonic() + self.COMPUTER_DELAY
        elif time.monotonic() >= self._move_due:
            self.table.confirm()
            self.story.poll()
            self.sync_view()
            self._auto_key = None

    def action_confirm(self):
        if not self._available():
            return
        story = self.story
        if story.dialogue is not None or story.game is not None and story.game.phase == Phase.RESULT:
            story.advance()
            story.poll()
            if story.done:
                self.exit()
                return
            self.sync_view()
        elif story.game is not None and story.game.phase == Phase.DEFEND:
            self.table.confirm()

    def on_click(self, event: events.Click):
        if self.story.dialogue is not None and event.button == 1:
            self.action_confirm()

    def action_style(self):
        if self._available():
            self.card_style = ART_STYLES[(ART_STYLES.index(self.card_style) + 1) % len(ART_STYLES)]
            self.sync_view()

    def action_restart(self):
        if self._available():
            self.story = CardStory(seed=self.seed, rival=self.start_rival)
            self._auto_key = None
            self.sync_view()

    def action_history(self):
        if self._available():
            text = "\n\n".join(
                f"{DISPLAY_NAMES.get(item.speaker, '')}: {item.text}"
                if DISPLAY_NAMES.get(item.speaker) else item.text for item in self.story.history)
            self.table.input_enabled = False
            self.push_screen(DemoDialog(text), lambda _: self.sync_view())

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == "btn-log":
            self.action_history()
        elif event.button.id == "btn-next":
            self.action_confirm()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rival", choices=tuple(RIVAL_NAMES), help="Начать с выбранного тура, без обучения")
    parser.add_argument("--style", choices=ART_STYLES, default="ANSI")
    parser.add_argument("--seed", type=int, help="Повторяемые раздачи")
    parser.add_argument("--no-background", action="store_true", help="Не показывать сюжетные изображения")
    args = parser.parse_args()
    CardGameDemo(rival=args.rival, style=args.style, seed=args.seed,
                 decorations=not args.no_background).run()


if __name__ == "__main__":
    main()
