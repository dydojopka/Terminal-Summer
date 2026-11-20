"""Тонкие консольные полосы прокрутки со штатным управлением Textual."""

from math import ceil

from rich.color import Color
from rich.segment import Segment, Segments
from rich.style import Style
from textual.scrollbar import ScrollBarRender


class ConsoleScrollBarRender(ScrollBarRender):
    @classmethod
    def render_bar(
        cls,
        size: int = 25,
        virtual_size: float = 50,
        window_size: float = 20,
        position: float = 0,
        thickness: int = 1,
        vertical: bool = True,
        back_color: Color = Color.parse("#555555"),
        bar_color: Color = Color.parse("#d8d5c8"),
    ) -> Segments:
        # Без bgcolor и reverse фон берётся у панели, включая её полупрозрачную заливку.
        style = Style(color=bar_color)
        before = style + Style(meta={"@mouse.up": "scroll_up"})
        after = style + Style(meta={"@mouse.up": "scroll_down"})
        handle = style + Style(meta={"@mouse.down": "grab"})
        size = max(0, size)
        has_arrows = size >= 2
        track_size = size - 2 if has_arrows else size
        scrollable = 0 < window_size < virtual_size
        cells = [(" ", style)] * track_size
        if scrollable and track_size:
            thumb_size = min(track_size, max(1, ceil(track_size * window_size / virtual_size)))
            ratio = min(1, max(0, position / (virtual_size - window_size)))
            start = round((track_size - thumb_size) * ratio)
            glyph = "┃" if vertical else "━"
            cells = (
                [(" ", before)] * start
                + [(glyph, handle)] * thumb_size
                + [(" ", after)] * (track_size - start - thumb_size)
            )
        if has_arrows:
            first, last = ("↑", "↓") if vertical else ("←", "→")
            cells = [
                (first, before if scrollable else style),
                *cells,
                (last, after if scrollable else style),
            ]
        if vertical:
            return Segments(
                [Segment(glyph * thickness, cell_style) for glyph, cell_style in cells],
                new_lines=True,
            )
        row = [Segment(glyph, cell_style) for glyph, cell_style in cells]
        return Segments((row + [Segment.line()]) * thickness, new_lines=False)
