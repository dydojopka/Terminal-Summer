"""Переиспользуемый карточный стол. Не знает про DSL, saves и persistent."""

from pathlib import Path

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from card_faces import render_card, render_card_legend
from card_game import CardGame, Phase, RIVAL_NAMES, SUIT_NAMES, score_hand
from card_scene import CardScene, render_card_scene, render_portrait
from console_button import ConsoleButton as Button


class CardSlot(Widget):
    can_focus = True
    ALLOW_SELECT = False
    BINDINGS = [
        Binding("enter", "pick", show=False),
        Binding("left", "move(-1, 0)", show=False),
        Binding("right", "move(1, 0)", show=False),
        Binding("up", "move(0, -1)", show=False),
        Binding("down", "move(0, 1)", show=False),
    ]

    def __init__(self, row: str, index: int):
        classes = "card-slot last-card" if index == 6 else "card-slot"
        super().__init__(id=f"card-{row}-{index}", classes=classes)
        self.row = row
        self.index = index

    @property
    def table(self) -> "CardTable":
        return next(node for node in self.ancestors if isinstance(node, CardTable))

    def render(self) -> Text:
        table = self.table
        game = table.game
        hand = game.player if self.row == "player" else game.opponent
        target = game.player_target if self.row == "player" else game.opponent_target
        grouped = game.phase == Phase.RESULT and hand[self.index] is not None and (
            hand[self.index].rank in {rank for _, rank in score_hand(hand).groups})
        return render_card(
            hand[self.index], style=table.card_style, position=self.index + 1,
            compact=table.compact, hidden=(
                self.row == "opponent" and game.phase != Phase.RESULT
                or self.row == "player" and not table.player_visible),
            targeted=table.targets_visible and (target == self.index or grouped),
            selected=self.row == "player" and table.swap_first == self.index,
            focused=self.has_focus or self.mouse_hover,
            moved=game.last_swap is not None and self.index in game.last_swap and (
                self.row == "player" and game.phase in {Phase.DEFEND, Phase.RIVAL_TAKE}
                or self.row == "opponent" and game.phase == Phase.SELECT),
        )

    def on_focus(self):
        self.refresh()

    def on_blur(self):
        self.refresh()

    def on_enter(self):
        self.refresh()

    def on_leave(self):
        self.refresh()

    def on_click(self, event: events.Click):
        if not self.table.input_enabled:
            return  # Клик во время реплики продолжает диалог, не ход.
        event.stop()
        self.focus()
        self.action_pick()

    def action_pick(self):
        self.table.pick(self.row, self.index)

    def action_move(self, horizontal: int, vertical: int):
        if not self.table.input_enabled:
            return
        row = ("player" if vertical > 0 else "opponent") if vertical else self.row
        self.table.query_one(f"#card-{row}-{(self.index + horizontal) % 7}").focus()


class CardTable(Vertical):
    """Changed сообщает изменение партии; сюжет остаётся владельцем реплик."""

    class Changed(Message):
        def __init__(self, game):
            super().__init__()
            self.game = game

    class Finished(Message):
        def __init__(self, result: str):
            super().__init__()
            self.result = result

    class ResultAccepted(Message):
        def __init__(self, game):
            super().__init__()
            self.game = game

    class SceneResized(Message):
        pass

    BINDINGS = [Binding(str(i), f"number({i - 1})", show=False) for i in range(1, 8)]

    def __init__(self, game: CardGame, *, ts_path: Path, style: str = "ANSI",
                 show_scenery: bool = True, external_scenery: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.game = game
        self.ts_path = ts_path
        self.card_style = style
        self.show_scenery = show_scenery
        self.external_scenery = external_scenery
        self.input_enabled = True
        self.player_visible = True
        self.targets_visible = True
        self.scene = CardScene()
        self.rival_name: str | None = None
        self.compact = True
        self.swap_first: int | None = None
        self.asset_note = ""
        self._art_key = None

    def compose(self):
        with Horizontal(id="card-layout"):
            with Vertical(id="card-hands"):
                with Horizontal(classes="card-row"):
                    for index in range(7):
                        yield CardSlot("opponent", index)
                with Vertical(id="card-center"):
                    yield Static("", id="card-scenery", markup=False)
                    with Vertical(id="card-result-row", classes="hidden"):
                        yield Button("", id="card-result")
                with Horizontal(classes="card-row"):
                    for index in range(7):
                        yield CardSlot("player", index)
            with Vertical(id="card-sidebar"):
                yield Static("", id="card-portrait", markup=False)
                yield Static("", id="card-rival-name", markup=False)
                yield Static("", id="card-counters", markup=False)
                yield Button("Закончить защиту", id="card-pass")
                yield Static("", id="card-legend", markup=False)

    def on_mount(self):
        self.sync()
        self.call_after_refresh(self.focus_active_hand)

    def on_resize(self, event: events.Resize):
        self.compact = event.size.width < 102 or event.size.height < 25
        self.set_class(self.compact, "compact-cards")
        if self.is_mounted:
            self.sync()

    def replace_game(self, game: CardGame):
        self.game = game
        self.swap_first = None
        self.sync()
        self.call_after_refresh(self.focus_active_hand)

    def focus_active_hand(self):
        if not self.input_enabled or not self.is_on_screen:
            return
        game = self.game
        row = "opponent" if game.phase == Phase.SELECT else "player"
        indices = game.allowed_takes if row == "opponent" else tuple(
            i for i, card in enumerate(game.player) if card is not None)
        self.query_one(f"#card-{row}-{indices[0]}").focus()

    def action_number(self, index: int):
        if not self.input_enabled or self.screen.has_class("terminal-too-small"):
            return
        row = "opponent" if self.game.phase == Phase.SELECT else "player"
        self.query_one(f"#card-{row}-{index}").focus()
        self.pick(row, index)

    def pick(self, row: str, index: int):
        if not self.input_enabled or self.screen.has_class("terminal-too-small"):
            return
        game = self.game
        previous = game.phase
        if row == "player" and game.phase == Phase.DEFEND:
            if self.swap_first is None:
                self.swap_first = index
            elif self.swap_first == index:
                self.swap_first = None
            else:
                game.swap_defence(self.swap_first, index)
                self.swap_first = None
        elif row == "player" and game.phase == Phase.GIVE and game.player[index] is not None:
            game.give(index)
        elif row == "opponent" and index in game.allowed_takes:
            game.select(index)
        else:
            return
        self.sync()
        self.post_message(self.Changed(game))
        if previous != game.phase:
            self.focus_active_hand()

    def confirm(self):
        if not self.input_enabled or self.screen.has_class("terminal-too-small"):
            return
        game = self.game
        if game.phase == Phase.DEFEND:
            self.swap_first = None
            game.finish_defence()
        elif game.phase in {Phase.RIVAL_TAKE, Phase.RIVAL_DEFEND, Phase.PLAYER_TAKE}:
            game.advance()
        else:
            return
        self.sync()
        self.post_message(self.Changed(game))
        if game.phase == Phase.RESULT:
            self.post_message(self.Finished(game.result))
        else:
            self.focus_active_hand()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if event.button.id == "card-pass":
            self.confirm()
        elif event.button.id == "card-result":
            self.post_message(self.ResultAccepted(self.game))

    def sync(self):
        game = self.game
        strings = getattr(self.app, "runtime_ui", {})
        tr = strings.get
        names = getattr(self.app, "interface_locale", {})
        reveal = game.phase == Phase.RESULT
        name = self.rival_name or names.get(game.rival, RIVAL_NAMES[game.rival])
        self.query_one("#card-rival-name", Static).update(f"{tr('card.opponent', 'Соперник')}: {name}")
        if reveal:
            turn = "---"
        elif game.phase in {Phase.RIVAL_TAKE, Phase.RIVAL_DEFEND}:
            turn = tr("card.turn.opponent", "Чужой")
        else:
            turn = tr("card.turn.player", "Твой")
        phase = {
            Phase.GIVE: ("card.phase.take", "Захват"),
            Phase.DEFEND: ("card.phase.defend", "Защита"),
            Phase.RIVAL_TAKE: ("card.phase.draw", "Вытягивание"),
            Phase.SELECT: ("card.phase.take", "Захват"),
            Phase.RIVAL_DEFEND: ("card.phase.defend", "Защита"),
            Phase.PLAYER_TAKE: ("card.phase.draw", "Вытягивание"),
            Phase.RESULT: ("card.phase.result", "Итоги"),
        }[game.phase]
        swaps = game.swaps_left if not reveal and game.swaps_left else "---"
        self.query_one("#card-counters", Static).update(
            f"{tr('card.turn', 'Чей ход')}: {turn}\n{tr('card.phase', 'Фаза игры')}: {tr(*phase)}\n"
            f"{tr('card.rounds', 'Кругов осталось')}: {0 if reveal else 4 - game.round}\n"
            f"{tr('card.swaps', 'Обменов осталось')}: {swaps}")
        self.query_one("#card-legend", Static).update(
            render_card_legend(self.card_style, compact=self.compact, strings=strings)
        )
        result = self.query_one("#card-result", Button)
        self.query_one("#card-result-row").set_class(not reveal, "hidden")
        result.label = tr(f"card.{game.result}", {"win": "Победа", "fail": "Поражение",
                                                "draw": "Ничья"}.get(game.result, ""))
        finish = self.query_one("#card-pass", Button)
        finish.display = game.phase == Phase.DEFEND
        finish.disabled = not self.input_enabled
        finish.label = tr("card.pass", "Закончить защиту")
        finish.tooltip = finish.label.plain
        for slot in self.query(CardSlot):
            hand = game.player if slot.row == "player" else game.opponent
            card = hand[slot.index]
            visible = slot.row == "player" and self.player_visible or reveal
            if card and visible:
                description = f"{card.label}, {tr(f'card.suit.{card.suit}', SUIT_NAMES[card.suit])}"
            else:
                description = tr("card.hidden", "Закрытая карта") if card else tr("card.empty", "Пустое место")
            slot.tooltip = f"{slot.index + 1}: {description}"
            slot.refresh()
        self._sync_art()

    def _sync_art(self):
        if self.has_class("hidden"):
            return
        center_height = max(0, self.size.height - (10 if self.compact else 14))
        scene_width = self.scene_width
        portrait_width = 6 if self.compact else 16
        self.query_one("#card-scenery").display = self.show_scenery and center_height > 1 and self.game.phase != Phase.RESULT
        key = self.game.rival, self.card_style, scene_width, portrait_width, self.scene
        if key == self._art_key:
            return
        self._art_key = key
        self.asset_note = ""
        if self.external_scenery:
            self.post_message(self.SceneResized())
        for identity, renderer, args in (
            ("card-portrait", render_portrait, (self.ts_path, key[0], key[1], portrait_width)),
            ("card-scenery", render_card_scene, (self.ts_path, self.scene, key[1], key[2])),
        ):
            if identity == "card-scenery" and (self.external_scenery or not self.query_one("#card-scenery").display):
                continue
            try:
                art = renderer(*args).copy()
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                art = Text("")
                self.asset_note = f"Декорации недоступны: {exc}"
            self.query_one(f"#{identity}", Static).update(art)

    @property
    def scene_width(self):
        center_height = max(0, self.size.height - (10 if self.compact else 14))
        return min(100, max(1, self.size.width - 25), max(1, int(center_height * 32 / 9)))
