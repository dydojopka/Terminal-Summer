"""Единая строгая грамматика карточных команд для runtime и валидатора."""

from dataclasses import dataclass
import re

from card_game import RIVAL_NAMES


WAIT_TARGETS = ("defend", "select", "rival_defend", "next_round")
RESULTS = ("win", "fail", "draw")


@dataclass(frozen=True)
class CardCommand:
    action: str
    argument: str = ""
    labels: tuple[str, ...] = ()


def parse_card_command(line: str) -> CardCommand:
    if line in ("cards tutorial", "cards reveal", "cards end"):
        return CardCommand(line.split()[1])
    match = re.fullmatch(r"cards wait (\w+)", line)
    if match and match[1] in WAIT_TARGETS:
        return CardCommand("wait", match[1])
    match = re.fullmatch(
        r"cards play (\w+) ([a-zA-Z0-9_]+) ([a-zA-Z0-9_]+) ([a-zA-Z0-9_]+)", line)
    if match and match[1] in RIVAL_NAMES:
        return CardCommand("play", match[1], tuple(match.groups()[1:]))
    raise ValueError(f"Некорректная карточная команда: {line}")


def validate_card_labels(command: CardCommand, labels) -> None:
    for label in command.labels:
        if label not in labels:
            raise ValueError(f"Неизвестная метка карточной игры: {label}")
