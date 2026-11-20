"""Состояние вызова мини-игры из DSL, включая продолжение после save/load."""

from dataclasses import dataclass

from cards.game import CardGame, Phase
from story.card_commands import CardCommand, parse_card_command, validate_card_labels


@dataclass
class CardSession:
    game: CardGame
    tutorial: bool
    origin_pc: int
    player_visible: bool = True
    targets_visible: bool = True
    command: CardCommand | None = None
    wait_pc: int | None = None
    selection: int | None = None

    @classmethod
    def start(cls, command, pc, *, seed=None):
        tutorial = command.action == "tutorial"
        return cls(CardGame("un" if tutorial else command.argument, seed=seed),
                   tutorial, pc, not tutorial, not tutorial,
                   None if tutorial else command, None if tutorial else pc)

    @property
    def playing(self):
        return self.command is not None

    @property
    def reached(self):
        if self.command is None or self.command.action == "play":
            return False
        target = self.command.argument
        return (self.game.round == 2 if target == "next_round" else self.game.phase.value == target)

    def wait(self, command, pc):
        if not self.tutorial or self.playing:
            raise ValueError("Нельзя прервать активную карточную партию")
        if command.argument == "defend":
            self.targets_visible = True
        self.command, self.wait_pc = command, pc
        return self.finish_wait()

    def finish_wait(self):
        if not self.reached:
            return False
        self.command = self.wait_pc = None
        self.selection = None
        return True

    def to_save_data(self):
        return {"version": 1, "tutorial": self.tutorial, "origin_pc": self.origin_pc,
                "wait_pc": self.wait_pc, "player_visible": self.player_visible,
                "targets_visible": self.targets_visible, "selection": self.selection,
                "game": self.game.to_save_data()}

    @classmethod
    def from_save_data(cls, data, *, lines, pc, labels):
        if type(pc) is not int or not 0 <= pc <= len(lines):
            raise ValueError("Некорректная позиция карточного сценария")
        active_tutorial = None
        for index, line in enumerate(lines[:pc]):
            if line == "cards tutorial":
                active_tutorial = index
            elif line == "cards end":
                active_tutorial = None
        if data is None:
            previous = parse_card_command(lines[pc - 1]) if pc and lines[pc - 1].startswith("cards") else None
            if active_tutorial is not None or previous is not None and previous.action in {"play", "wait"}:
                raise ValueError("В сохранении потеряна карточная партия")
            return None
        if (not isinstance(data, dict) or type(data.get("version")) is not int
                or data["version"] != 1):
            raise ValueError("Неизвестный формат сохранения карт")
        for field in ("tutorial", "player_visible", "targets_visible"):
            if type(data.get(field)) is not bool:
                raise ValueError(f"Некорректное поле карт: {field}")
        origin, wait_pc = data.get("origin_pc"), data.get("wait_pc")
        if type(origin) is not int or not 0 <= origin < len(lines):
            raise ValueError("Некорректное начало карточной партии")
        opening = parse_card_command(lines[origin])
        tutorial = data["tutorial"]
        if opening.action != ("tutorial" if tutorial else "play") or pc <= origin:
            raise ValueError("Карточная партия не соответствует сценарию")
        validate_card_labels(opening, labels)
        if tutorial and active_tutorial != origin:
            raise ValueError("Учебная партия уже закрыта в сценарии")
        game = CardGame.from_save_data(data.get("game"))
        if game.rival != ("un" if tutorial else opening.argument):
            raise ValueError("Соперница не соответствует сценарию")
        if tutorial and game.round > 2:
            raise ValueError("Учебная партия не может дойти до третьего круга или результата")
        command = None
        if wait_pc is not None:
            if type(wait_pc) is not int or not origin <= wait_pc < len(lines) or pc != wait_pc + 1:
                raise ValueError("Некорректное продолжение карточной партии")
            command = parse_card_command(lines[wait_pc])
            if (tutorial and command.action != "wait"
                    or not tutorial and (wait_pc != origin or command != opening)):
                raise ValueError("Карточное ожидание не соответствует сценарию")
        elif not tutorial:
            raise ValueError("Потеряно продолжение карточной партии")
        selection = data.get("selection")
        if selection is not None and (
                type(selection) is not int or not 0 <= selection < 7 or game.phase != Phase.DEFEND):
            raise ValueError("Некорректная выбранная карта")
        session = cls(game, tutorial, origin, data["player_visible"],
                      data["targets_visible"], command, wait_pc, selection)
        if (not tutorial and not (session.player_visible and session.targets_visible)
                or session.playing and not (session.player_visible and session.targets_visible)
                or session.reached):
            raise ValueError("Несогласованная карточная остановка")
        return session
