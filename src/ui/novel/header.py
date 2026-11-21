"""Верхняя панель состояния сценария."""

from textual import events
from textual.widgets import Header


class ScriptStateHeader(Header):
    """Header, переносящий длинное состояние сценария на несколько строк."""

    DEFAULT_CSS = """
    ScriptStateHeader {
        height: auto;
        max-height: 8;
    }

    ScriptStateHeader HeaderTitle {
        height: auto;
        text-wrap: wrap;
        text-overflow: fold;
        padding: 0 1;
    }
    """

    def format_title(self):
        title = super().format_title()
        self._sync_title_alignment(title)
        return title

    def on_resize(self) -> None:
        self._sync_title_alignment(super().format_title())

    def _sync_title_alignment(self, title) -> None:
        clock_width = self.query_one("HeaderClockSpace").region.width
        title_gutter = self.query_one("HeaderTitle").styles.gutter.width
        # Считаем по внешней ширине, чтобы смена padding не вызывала колебаний.
        centered_width = self.region.width - 2 * clock_width - title_gutter
        fits_centered = title.get_optimal_width({}, self.region.width) <= centered_width
        self.styles.padding = (0, 0, 0, clock_width if fits_centered else 0)

    def on_click(self, event: events.Click) -> None:
        # Не вызывать унаследованный Header._on_click(), меняющий класс -tall.
        event.prevent_default()
