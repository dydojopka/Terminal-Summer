"""Контейнер сцены, сюжетного выбора и карточного стола."""

from pathlib import Path

from textual.widget import Widget

from cards.game import CardGame
from cards.table import CardTable
from ui.novel.choices import ChoiceBar
from ui.widgets.ansi_view import AnsiView


class NovelWindow(Widget):
    def __init__(self, ts_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.ts_path = ts_path

    def compose(self):
        yield ChoiceBar(id="choice-bar", classes="hidden")
        yield AnsiView("", id="bg-cg", classes="mouse-passive-art")
        yield CardTable(CardGame(), ts_path=self.ts_path, external_scenery=True,
                        id="card-table", classes="hidden")
