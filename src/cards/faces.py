"""Читаемые карты без внешних картинок и шрифтов.

ASCII действительно состоит из ASCII-символов. ANSI использует полублоки
того же render_art, что и сцены, но номинал не растрируется.
"""

from functools import lru_cache

from PIL import Image, ImageDraw
from rich.text import Text

from art_renderer import ART_STYLES, render_art
from cards.game import Card, SUIT_NAMES


SUIT_COLORS = {"S": "#71b9ed", "H": "#f07e78", "D": "#e4ba62", "C": "#8dc99a"}
SUIT_INK = {"S": "#173c69", "H": "#a52d35", "D": "#885714", "C": "#205b3b"}
SUIT_SYMBOLS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
ASCII_PIPS = {
    "S": ("  ^  ", " /#\\ ", "  |  "),
    "H": ("(v v)", " \\ / ", "  v  "),
    "D": ("  ^  ", " < > ", "  v  "),
    "C": ("  o  ", " oOo ", "  |  "),
}
PAPER = "#eee8d5"


def render_card_legend(style: str, *, compact: bool = False, strings: dict[str, str] | None = None) -> Text:
    if style not in ART_STYLES:
        raise ValueError("Неизвестный стиль карт")
    tr = (strings or {}).get
    suits = {suit: tr(f"card.suit.{suit}", name) for suit, name in SUIT_NAMES.items()}
    legend = Text(no_wrap=True)
    if compact:
        for first, second in (("S", "H"), ("D", "C")):
            for suit in (first, second):
                legend.append(f"{suit}{SUIT_SYMBOLS[suit]} {suits[suit]}  ",
                              SUIT_COLORS[suit] if style != "ASCII" else None)
            legend.rstrip()
            legend.append("\n")
        legend.append(tr("card.legend.compact", "v цель/итог; * выбор\n~ обмен; фон — фокус"))
        return legend
    for suit, name in suits.items():
        color = SUIT_COLORS[suit] if style != "ASCII" else None
        legend.append(f"{suit} / {SUIT_SYMBOLS[suit]} — {name}\n", color)
    accent = "#e3b778" if style != "ASCII" else None
    legend.append("v1v", accent)
    legend.append(tr("card.legend.target", " — цель, комбинация\n"))
    legend.append("*1*", accent)
    legend.append(tr("card.legend.selected", " — первая карта\n"))
    legend.append(tr("card.legend.swapped", "~~~ — переставлены\n"))
    legend.append(tr("card.legend.invert", "инверсия"), "reverse")
    legend.append(tr("card.legend.focus", " — фокус"))
    return legend


@lru_cache(maxsize=8)
def _ansi_pip(suit: str, width: int, height: int) -> tuple[Text, ...]:
    """Небольшая процедурная масть: 2 вертикальных пикселя на ячейку."""
    with Image.new("RGB", (50, 40), PAPER) as image:
        draw = ImageDraw.Draw(image)
        ink = SUIT_INK[suit]
        if suit == "D":
            draw.polygon(((25, 1), (43, 19), (25, 38), (7, 19)), fill=ink)
        elif suit == "H":
            draw.ellipse((4, 2, 26, 24), fill=ink)
            draw.ellipse((24, 2, 46, 24), fill=ink)
            draw.polygon(((5, 16), (45, 16), (25, 38)), fill=ink)
        elif suit == "S":
            draw.polygon(((25, 0), (5, 21), (45, 21)), fill=ink)
            draw.ellipse((5, 13, 26, 31), fill=ink)
            draw.ellipse((24, 13, 45, 31), fill=ink)
            draw.polygon(((25, 22), (17, 38), (33, 38)), fill=ink)
        else:
            for box in ((16, 0, 34, 19), (4, 13, 25, 32), (25, 13, 46, 32)):
                draw.ellipse(box, fill=ink)
            draw.polygon(((25, 23), (17, 38), (33, 38)), fill=ink)
        # render_art сохраняет геометрию image, поэтому явно задаём aspect.
        with image.resize((width, height * 2), Image.Resampling.NEAREST) as sized:
            return tuple(render_art(sized, width=width, style="ANSI", alpha=False).split("\n"))


def render_card(card: Card | None, *, style: str, position: int, compact: bool = False,
                hidden: bool = False, targeted: bool = False, selected: bool = False,
                focused: bool = False, moved: bool = False) -> Text:
    if style not in ART_STYLES:
        raise ValueError("Неизвестный стиль карт")
    width, height = (7, 5) if compact else (9, 7)
    inner = width - 2
    marker = f"v{position}v" if targeted else f"*{position}*" if selected else str(position)
    top = marker.center(inner, "-")
    frame = None if style == "ASCII" else "#e3b778" if targeted or selected else "#9d9687"
    face = Text(no_wrap=True, overflow="crop")
    face.append("+" + top + "+", frame)
    if focused:
        face.stylize("bold reverse", 0, width)
    face.append("\n")
    if card is None:
        rows = [" " * inner for _ in range(height - 2)]
    elif hidden:
        rows = [(":/:" * inner)[:inner] for _ in range(height - 2)]
        rows[len(rows) // 2] = " ? ".center(inner, ":")
    else:
        suit = SUIT_SYMBOLS[card.suit] if style == "ANSI" else card.suit
        rows = [f"{card.label} {suit}".ljust(inner)]
        if compact:
            rows.append(suit.center(inner))
        else:
            rows.extend(row.center(inner) for row in ASCII_PIPS[card.suit])
        rows.append(f"{suit} {card.label}".rjust(inner))
    for y, row in enumerate(rows):
        face.append("|", frame)
        if style == "ANSI":
            background = "#344b60" if hidden and card else PAPER if card else "#252b29"
            ink = "#e4d8b8" if hidden or card is None else SUIT_INK[card.suit]
            if card and not hidden and 0 < y < len(rows) - 1:
                pip = _ansi_pip(card.suit, inner, len(rows) - 2)[y - 1]
                face.append_text(pip)
            else:
                face.append(row, f"bold {ink} on {background}")
        else:
            ink = (SUIT_COLORS[card.suit] if card and not hidden else "#8a9eac") \
                if style == "COLOR_ASCII" else None
            face.append(row, ink)
        face.append("|\n", frame)
    bottom = ("~" if moved else "-") * inner
    face.append("+" + bottom + "+", frame)
    return face
