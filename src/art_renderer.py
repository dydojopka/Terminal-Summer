"""Преобразование готового кадра новеллы в три терминальных стиля."""

from PIL import Image
import pil2ansi
from rich.color import Color
from rich.style import Style
from rich.text import Text


ART_STYLES = ("ANSI", "ASCII", "COLOR_ASCII")


def render_art(image: Image.Image, *, width: int, style: str, alpha: bool) -> Text:
    if style == "ANSI":
        palette = pil2ansi.Palettes.color
    elif style == "ASCII":
        palette = pil2ansi.Palettes.ascii
    elif style == "COLOR_ASCII":
        return _render_color_ascii(image, width=width, alpha=alpha)
    else:
        raise ValueError(f"Неизвестный стиль артов: {style}")
    return Text.from_ansi(
        pil2ansi.convert_img(image, width=width, palette=palette, alpha=alpha)
    )


def _render_color_ascii(image: Image.Image, *, width: int, alpha: bool) -> Text:
    if width <= 0:
        raise ValueError("Ширина ASCII-арта должна быть положительной")
    height = max(1, round(width * (image.height / image.width)))
    art = Text()
    # Как в pil2ansi: сначала resize, затем обрезка, а не сжатие до окна.
    columns = min(width, pil2ansi.TERMINAL_WIDTH)
    with image.convert("RGBA") as rgba, rgba.resize(
        (width, height), resample=Image.Resampling.NEAREST
    ) as resized, resized.convert("LA") as gray:
        pixels = resized.load()
        luminance = gray.load()
        for y in range(height):
            # pil2ansi сохраняет и последнюю строку с нечётным индексом.
            if y % 2 != 0 and y != height - 1:
                continue
            if y:
                art.append("\n")
            for x in range(columns):
                r, g, b, a = pixels[x, y]
                if alpha and a == 0:
                    art.append(" ")
                else:
                    value, _ = luminance[x, y]
                    pixel = (value, 255)
                    glyph = pil2ansi.Palettes.ascii.pixel_to_color(pixel, pixel)
                    art.append(glyph, Style(color=Color.from_rgb(r, g, b)))
    return art
