"""Правила карточной игры второго дня, независимо от Textual и сценария.

Источник: Everlasting-Source/game/cardgame/{card_game_engine,rivals}.rpy.
Это НЕ стандартный покер: сравниваются группы одинаковых номиналов.
"""

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import random


SUITS = ("S", "H", "D", "C")
SUIT_NAMES = dict(zip(SUITS, ("пики", "червы", "бубны", "трефы")))
RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}
RIVAL_NAMES = {"un": "Лена", "us": "Ульяна", "dv": "Алиса"}
SLOTS = 7
CYCLES = 3
DEFENCE_SWAPS = 2


@dataclass(frozen=True)
class Card:
    rank: int
    suit: str

    def __post_init__(self):
        if type(self.rank) is not int or not 2 <= self.rank <= 14:
            raise ValueError("Номинал карты должен быть от 2 до 14")
        if self.suit not in SUITS:
            raise ValueError("Неизвестная масть")

    @property
    def label(self) -> str:
        return RANK_NAMES.get(self.rank, str(self.rank))

    @property
    def name(self) -> str:
        return f"{self.label}, {SUIT_NAMES[self.suit]}"


@dataclass(frozen=True)
class HandScore:
    groups: tuple[tuple[int, int], ...]

    @property
    def key(self) -> tuple:
        # Оригинальные what_category / compare_sets: сначала число карт
        # в группах, затем меньшее число групп, затем длины и номиналы.
        return sum(size for size, _ in self.groups), -len(self.groups), self.groups


def score_hand(cards) -> HandScore:
    counts = Counter(card.rank for card in cards if card is not None)
    if not counts:
        raise ValueError("Нельзя оценить пустую руку")
    groups = tuple(sorted(((count, rank) for rank, count in counts.items() if count > 1),
                          reverse=True))
    return HandScore(groups or ((1, max(counts)),))


class Phase(str, Enum):
    GIVE = "give"                    # Ульяна: сами выбираем, что отдать.
    DEFEND = "defend"                # До двух перестановок своей руки.
    RIVAL_TAKE = "rival_take"        # Видим окончательный выбор соперницы.
    SELECT = "select"                # Выбор карты соперницы.
    RIVAL_DEFEND = "rival_defend"    # Одна видимая перестановка, не обе сразу.
    PLAYER_TAKE = "player_take"
    RESULT = "result"


class CardGame:
    """Одна партия. Каждое действие атомарно; UI не меняет правила.

    По 7 позиций, но только 6 карт. Соперница сначала забирает карту
    в пустое место, затем игрок возвращает число карт к 6:6.
    Промежуточные фазы оставлены явными для показа перемещений.
    """

    def __init__(self, rival: str = "un", *, seed: int | None = None):
        if rival not in RIVAL_NAMES:
            raise ValueError("Неизвестная соперница")
        self.rival = rival
        self.rng = random.Random(seed)
        deck = [Card(rank, suit) for rank in range(2, 15) for suit in SUITS]
        dealt = self.rng.sample(deck, 14)
        # Как generate_cards: две из 14 карт заменены пустыми местами.
        self.opponent = [None, *dealt[1:7]]
        self.player = [None, *dealt[8:14]]
        self.round = 1
        self.swaps_left = DEFENCE_SWAPS
        self.hot: set[Card | None] = set()
        self.player_target: int | None = None
        self.opponent_target: int | None = None
        self.last_swap: tuple[int, int] | None = None
        self.result: str | None = None
        self._start_round()

    def _require(self, *phases):
        if self.phase not in phases:
            raise ValueError(f"Действие недоступно в фазе {self.phase.value}")

    @staticmethod
    def _index(index):
        if type(index) is not int or not 0 <= index < SLOTS:
            raise ValueError("Позиция карты должна быть от 0 до 6")

    def _pick_player(self, excluded: Card | None = None):
        candidates = [i for i, card in enumerate(self.player)
                      if card is not None and (self.rival != "un" or card != excluded)]
        if self.rival == "dv":
            recent = [i for i in candidates if self.player[i] in self.hot]
            candidates = recent or candidates
        self.player_target = self.rng.choice(candidates)

    def _start_round(self):
        self.swaps_left = DEFENCE_SWAPS
        self.opponent_target = None
        self.last_swap = None
        if self.rival == "us":
            self.player_target = None
            self.phase = Phase.GIVE
        else:
            self._pick_player()
            self.phase = Phase.DEFEND

    def _swap(self, hand, first, second):
        self.hot = {hand[first], hand[second]}
        hand[first], hand[second] = hand[second], hand[first]
        self.last_swap = first, second

    def swap_defence(self, first: int, second: int):
        self._require(Phase.DEFEND)
        self._index(first)
        self._index(second)
        if first == second:
            raise ValueError("Для перестановки нужны две разные позиции")
        previous = self.player[self.player_target]
        self._swap(self.player, first, second)
        self.swaps_left -= 1
        # Лена не берёт ранее отмеченную карту; Алиса следит за hot.
        self._pick_player(excluded=previous)
        if self.swaps_left == 0:
            self.phase = Phase.RIVAL_TAKE

    def give(self, index: int):
        self._require(Phase.GIVE)
        self._index(index)
        if self.player[index] is None:
            raise ValueError("Нельзя отдать пустое место")
        self.player_target = index
        self.phase = Phase.RIVAL_TAKE

    def finish_defence(self):
        self._require(Phase.DEFEND)
        self.phase = Phase.RIVAL_TAKE

    @property
    def allowed_takes(self) -> tuple[int, ...]:
        if self.phase != Phase.SELECT:
            return ()
        if self.rival == "us":
            return (self.opponent_target,)
        return tuple(i for i, card in enumerate(self.opponent) if card is not None)

    def select(self, index: int):
        self._require(Phase.SELECT)
        self._index(index)
        if index not in self.allowed_takes:
            raise ValueError("Эту карту сейчас нельзя взять")
        self.opponent_target = index
        self.phase = Phase.RIVAL_DEFEND

    def advance(self):
        """Подтверждение видимого хода, без таймеров и гонок с клавиатурой."""
        self._require(Phase.RIVAL_TAKE, Phase.RIVAL_DEFEND, Phase.PLAYER_TAKE)
        if self.phase == Phase.RIVAL_TAKE:
            destination = max(i for i, card in enumerate(self.opponent) if card is None)
            self._transfer(self.player, self.player_target, self.opponent, destination)
            self.swaps_left = DEFENCE_SWAPS
            self.phase = Phase.SELECT
            if self.rival == "us":
                # Ульяна не отдаёт только что полученную карту (hot).
                self.opponent_target = self.rng.choice(
                    [i for i, card in enumerate(self.opponent) if card not in self.hot])
        elif self.phase == Phase.RIVAL_DEFEND:
            if self.rival == "us" or self.swaps_left == 0:
                self.phase = Phase.PLAYER_TAKE
            else:
                if self.rival == "dv":
                    first = self.opponent_target
                    second = self.rng.choice([i for i in range(SLOTS) if i != first])
                else:
                    first, second = self.rng.sample(range(SLOTS), 2)
                self._swap(self.opponent, first, second)
                # Стрелка остаётся над ПОЗИЦИЕЙ. Игрок сам отслеживает карту.
                self.swaps_left -= 1
                self.phase = Phase.SELECT
        else:
            destination = max(i for i, card in enumerate(self.player) if card is None)
            self._transfer(self.opponent, self.opponent_target, self.player, destination)
            if self.round == CYCLES:
                self.player.sort(key=lambda card: card.rank if card else 0)
                self.opponent.sort(key=lambda card: card.rank if card else 0)
                mine, theirs = score_hand(self.player).key, score_hand(self.opponent).key
                self.result = "win" if mine > theirs else "fail" if mine < theirs else "draw"
                self.phase = Phase.RESULT
                self.player_target = self.opponent_target = None
            else:
                self.round += 1
                self._start_round()

    def _transfer(self, source, index, target, destination):
        self.hot = {source[index], target[destination]}
        source[index], target[destination] = target[destination], source[index]
        self.player_target = self.opponent_target = None
        self.last_swap = None

    def to_save_data(self) -> dict:
        def encode(card):
            return [card.rank, card.suit] if card is not None else None
        return {
            "rival": self.rival, "player": list(map(encode, self.player)),
            "opponent": list(map(encode, self.opponent)), "round": self.round,
            "phase": self.phase.value, "swaps_left": self.swaps_left,
            "player_target": self.player_target, "opponent_target": self.opponent_target,
            "last_swap": list(self.last_swap) if self.last_swap is not None else None,
            "hot": [encode(card) for card in sorted(self.hot, key=lambda c: (c.rank, c.suit) if c else (0, ""))],
            "result": self.result,
            "rng": [3, list(self.rng.getstate()[1]), None],
        }

    @classmethod
    def from_save_data(cls, data) -> "CardGame":
        """Проверяет всю позицию, включая RNG, до её публикации в приложении."""
        if (not isinstance(data, dict) or not isinstance(data.get("rival"), str)
                or data["rival"] not in RIVAL_NAMES):
            raise ValueError("Некорректная карточная позиция")
        def decode(value):
            if value is None:
                return None
            if not isinstance(value, list) or len(value) != 2 or not isinstance(value[1], str):
                raise ValueError("Некорректная карта в сохранении")
            return Card(*value)
        def bounded(value, low, high):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Некорректный счётчик карточной игры")
            return value
        def target(value):
            return None if value is None else bounded(value, 0, SLOTS - 1)
        hands = []
        for key in ("player", "opponent"):
            values = data.get(key)
            if not isinstance(values, list) or len(values) != SLOTS:
                raise ValueError("В карточной руке должно быть семь позиций")
            hands.append(list(map(decode, values)))
        player, opponent = hands
        cards = [card for card in player + opponent if card is not None]
        if len(cards) != 12 or len(set(cards)) != 12:
            raise ValueError("Повторяющиеся или потерянные карты")
        try:
            phase = Phase(data.get("phase"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Неизвестная фаза карточной игры") from exc
        round_number = bounded(data.get("round"), 1, CYCLES)
        swaps = bounded(data.get("swaps_left"), 0, DEFENCE_SWAPS)
        mine, theirs = target(data.get("player_target")), target(data.get("opponent_target"))
        before_take = phase in {Phase.GIVE, Phase.DEFEND, Phase.RIVAL_TAKE, Phase.RESULT}
        if (player.count(None), opponent.count(None)) != ((1, 1) if before_take else (2, 0)):
            raise ValueError("Число карт не соответствует фазе")
        rival = data["rival"]
        if (phase == Phase.GIVE and rival != "us"
                or phase == Phase.DEFEND and (rival == "us" or swaps == 0)):
            raise ValueError("Фаза защиты не соответствует сопернице")
        needs_mine = phase in {Phase.DEFEND, Phase.RIVAL_TAKE}
        if needs_mine != (mine is not None) or mine is not None and player[mine] is None:
            raise ValueError("Некорректная цель соперницы")
        needs_theirs = phase in {Phase.RIVAL_DEFEND, Phase.PLAYER_TAKE} or phase == Phase.SELECT and rival == "us"
        if (needs_theirs and theirs is None
                or before_take and theirs is not None
                or theirs is not None and opponent[theirs] is None):
            raise ValueError("Некорректная цель игрока")
        hot_data = data.get("hot")
        if not isinstance(hot_data, list) or len(hot_data) > 2:
            raise ValueError("Некорректные перемещённые карты")
        hot = list(map(decode, hot_data))
        if len(set(hot)) != len(hot) or any(card is not None and card not in cards for card in hot):
            raise ValueError("Неизвестная перемещённая карта")
        last = data.get("last_swap")
        if last is not None:
            if not isinstance(last, list) or len(last) != 2:
                raise ValueError("Некорректная перестановка")
            last = tuple(target(index) for index in last)
            if None in last or last[0] == last[1]:
                raise ValueError("Некорректные позиции перестановки")
        result = data.get("result")
        if phase == Phase.RESULT:
            mine_score, their_score = score_hand(player).key, score_hand(opponent).key
            expected = "win" if mine_score > their_score else "fail" if mine_score < their_score else "draw"
            if round_number != CYCLES or result != expected:
                raise ValueError("Карточный результат не соответствует рукам")
        elif result is not None:
            raise ValueError("Преждевременный карточный результат")
        rng_data = data.get("rng")
        if (not isinstance(rng_data, list) or len(rng_data) != 3
                or type(rng_data[0]) is not int or rng_data[0] != 3
                or not isinstance(rng_data[1], list) or len(rng_data[1]) != 625
                or rng_data[2] is not None):
            raise ValueError("Некорректное состояние генератора карт")
        for value in rng_data[1][:-1]:
            bounded(value, 0, 2**32 - 1)
        bounded(rng_data[1][-1], 0, 624)
        game = cls.__new__(cls)
        game.rival, game.player, game.opponent = rival, player, opponent
        game.phase, game.round, game.swaps_left = phase, round_number, swaps
        game.player_target, game.opponent_target = mine, theirs
        game.hot, game.last_swap, game.result = set(hot), last, result
        game.rng = random.Random()
        game.rng.setstate((3, tuple(rng_data[1]), None))
        return game
