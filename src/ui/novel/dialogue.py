"""Текст диалогов, панель управления и история реплик."""

import asyncio

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Log, Static

from ui.widgets.console_button import ConsoleButton as Button


SPEAKER_NAME_COLORS = {
    "dreamgirl":   "rgb(192,192,192)",
    "sl":          "rgb(255,210,0)",
    "slp":         "rgb(255,210,0)",
    "slg":         "rgb(255,210,0)",
    "sa":          "rgb(255,210,0)",
    "un":          "rgb(185,86,255)",
    "unp":         "rgb(185,86,255)",
    "dv":          "rgb(255,170,0)",
    "dvp":         "rgb(255,170,0)",
    "dvg":         "rgb(255,170,0)",
    "el":          "rgb(255,255,0)",
    "elp":         "rgb(255,255,0)",
    "ro":          "rgb(255,255,0)",
    "us":          "rgb(255,50,0)",
    "usp":         "rgb(255,50,0)",
    "usg":         "rgb(255,50,0)",
    "mt":          "rgb(0,234,50)",
    "mtp":         "rgb(0,234,50)",
    "mt_voice":    "rgb(0,234,50)",
    "cs":          "rgb(165,165,255)",
    "csp":         "rgb(165,165,255)",
    "mz":          "rgb(114,160,255)",
    "mi":          "rgb(0,252,255)",
    "mip":         "rgb(0,252,255)",
    "ma":          "rgb(0,252,255)",
    "uv":          "rgb(78,255,0)",
    "uvp":         "rgb(78,255,0)",
    "sh":          "rgb(255,242,38)",
    "pi":          "rgb(230,0,0)",
    "me":          "rgb(225,221,125)",
    "my":          "rgb(225,221,125)",
    "FIXME_voice": "rgb(192,192,192)",
    "bush":        "rgb(192,192,192)",
    "message":     "rgb(192,192,192)",
    "odn":         "rgb(192,192,192)",
    "all":         "rgb(227,58,58)",
}


class NovelMenu(Static):
    """Панель диалога с кнопками истории и продолжения."""

    BUTTON_LABELS = {
        "btn-log": ("История", "History"),
        "btn-next": ("Продолжить", "Continue"),
    }

    def compose(self):
        with Vertical(id="novel-log-control", classes="novel-control"):
            yield Button(self.BUTTON_LABELS["btn-log"][0], id="btn-log")
        yield TextBar(id="text-bar")
        with Vertical(id="novel-next-control", classes="novel-control"):
            yield Button(self.BUTTON_LABELS["btn-next"][0], id="btn-next")

    def apply_language(self, language: str) -> None:
        for button_id, (russian, english) in self.BUTTON_LABELS.items():
            self.query_one(f"#{button_id}", Button).label = english if language == "en" else russian


class TextBar(VerticalScroll):
    """Виджет текст бара"""
    BORDER_TITLE = ""   # Имя персонажа

    def __init__(self, id=None):
        super().__init__(id=id)
        self._text = ""
        self._content = Static("", classes="dialogue-content")

    def compose(self):
        yield self._content

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value
        self._content.update(Text.from_markup(value))

    def append_nvl_paragraph(self, speaker: str, speaker_id: str | None) -> None:
        prefix = "\n" if self.text else ""
        if speaker:
            name = Text(
                f"{speaker}:",
                style=Style(bold=True, color=SPEAKER_NAME_COLORS.get(speaker_id or "")),
            )
            prefix += name.markup + " "
        self.text += prefix

    async def animate_text(self, new_text, append=False):
        """Анимация текста, символ за символом

        Если append=True  - добавляет текст к текущему,\n
        Если append=False - начинает с нуля"""

        speed = float(self.app.text_speed)

        if not append:
            self.text = ""
            self.scroll_home(animate=False)

        for index, char in enumerate(new_text):
            await self.app.wait_until_game_resumed()
            if self.app.skipping:
                self.text += new_text[index:]
                # Быстрые части <w> тоже должны отдавать управление вводу.
                await asyncio.sleep(0)
                break
            self.text += char
            await asyncio.sleep(speed)

        self.scroll_end(animate=False)


class LogMenu(Log):
    """Виджет окна истории"""
    auto_scroll = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._speaker_line_styles: dict[int, Style] = {}

    def add_dialogue_entry(
        self,
        text: str,
        speaker: str = "",
        speaker_id: str | None = None,
    ) -> None:
        if speaker:
            self.write_line(speaker)
            line_index = self.line_count - 1
            color = SPEAKER_NAME_COLORS.get(speaker_id or "")
            if color:
                self._speaker_line_styles[line_index] = Style.parse(color)

        self.write_line(f" {text}")

    def clear(self):
        self._speaker_line_styles.clear()
        return super().clear()

    def _render_line(self, y: int, scroll_x: int, width: int):
        strip = super()._render_line(y, scroll_x, width)
        style = self._speaker_line_styles.get(y)
        if style is not None:
            return strip.__class__(
                Segment.apply_style(strip._segments, post_style=style),
                strip.cell_length,
            )
        return strip
