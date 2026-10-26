"""Преобразование готового кадра новеллы в три терминальных стиля."""

from PIL import Image
import pil2ansi
from rich.color import Color
from rich.style import Style
from rich.text import Text


ART_STYLES = ("ANSI", "ASCII", "COLOR_ASCII")


def render_art(image: Image.Image, *, width: int, style: str, alpha: bool) -> Text:
    """Полный кадр: размер терминала не обрезает данные и не входит в кэш.

    Textual сам отображает доступную часть при resize/прокрутке. Читаем пиксели
    через Pillow.load, не через удаляемый Image.getdata из pil2ansi.convert_img.
    """
    if style not in ART_STYLES:
        raise ValueError(f"Неизвестный стиль артов: {style}")
    if width <= 0:
        raise ValueError("Ширина ASCII-арта должна быть положительной")
    height = max(1, round(width * (image.height / image.width)))
    art = Text(no_wrap=True, overflow="crop")
    with image.convert("RGBA") as rgba, rgba.resize(
        (width, height), resample=Image.Resampling.NEAREST
    ) as resized, resized.convert("LA") as gray:
        pixels = resized.load()
        luminance = gray.load()
        for y in range(height):
            # ASCII сохраняет последнюю нечётную строку, как палитра pil2ansi.
            if y % 2 and (style == "ANSI" or y != height - 1):
                continue
            if y:
                art.append("\n")
            for x in range(width):
                r, g, b, a = pixels[x, y]
                if style == "ANSI":
                    r2, g2, b2, a2 = pixels[x, min(y + 1, height - 1)]
                    visible_top = not alpha or a != 0
                    visible_bottom = y + 1 < height and (not alpha or a2 != 0)
                    if not visible_top and not visible_bottom:
                        art.append(" ")
                    elif not visible_top:
                        art.append("▄", Style(color=Color.from_rgb(r2, g2, b2)))
                    else:
                        art.append("▀", Style(color=Color.from_rgb(r, g, b),
                            bgcolor=Color.from_rgb(r2, g2, b2) if visible_bottom else None))
                elif alpha and a == 0:
                    art.append(" ")
                else:
                    value, _ = luminance[x, y]
                    pixel = (value, 255)
                    glyph = pil2ansi.Palettes.ascii.pixel_to_color(pixel, pixel)
                    art.append(glyph, Style(color=Color.from_rgb(r, g, b)) if style == "COLOR_ASCII" else None)
    return art
