"""Чтение готовых ANSI-иконок, без Pillow и преобразования изображений."""

import re
from pathlib import Path

from rich.text import Text


SGR_RE = re.compile(r"\x1b\[([0-9;]+)m")


def read_ending_ansi(path: Path, width: int) -> Text:
    content = path.read_text(encoding="utf-8")
    if len(content) > 100_000:
        raise ValueError(f"Слишком большая ANSI-иконка: {path}")
    for match in SGR_RE.finditer(content):
        codes = [int(value) for value in match[1].split(";")]
        if codes == [0]:
            continue
        if len(codes) not in (5, 10):
            raise ValueError(f"Недопустимый ANSI-код иконки: {path}")
        for offset in range(0, len(codes), 5):
            channel, mode, *rgb = codes[offset:offset + 5]
            if channel not in (38, 48) or mode != 2 or any(not 0 <= value <= 255 for value in rgb):
                raise ValueError(f"Недопустимый ANSI-цвет иконки: {path}")
    plain = SGR_RE.sub("", content)
    lines = plain.split("\n")
    if len(lines) != width // 2 or any(line != "▀" * width for line in lines):
        raise ValueError(f"Ожидается ANSI-иконка размером {width}×{width // 2}: {path}")
    art = Text.from_ansi(content)
    if not art.spans:
        raise ValueError(f"ANSI-иконка не содержит цветов: {path}")
    art.no_wrap = True
    art.overflow = "crop"
    return art
