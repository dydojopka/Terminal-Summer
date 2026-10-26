"""Страницы титров и их положение на сценарной шкале времени."""

from dataclasses import dataclass
import math


CREDIT_PAGES = (
    "Терминальная адаптация\n[bold]dydojopka[/bold]",
    "Оригинальная игра\n[bold]«Бесконечное лето» — Soviet Games[/bold]\n"
    "Спасибо авторам сценария, графики и музыки.",
    "Создано с помощью\nPython · Textual · Pillow · pil2ansi · pygame-ce",
    "Спасибо за прохождение!\ngithub.com/dydojopka/Terminal-Summer",
)


@dataclass
class CreditsTimeline:
    duration: float
    elapsed: float = 0.0

    def __post_init__(self):
        if not math.isfinite(self.duration) or self.duration <= 0:
            raise ValueError("Титры должны содержать положительную длительность пауз")

    @property
    def page(self) -> int:
        return min(len(CREDIT_PAGES) - 1, int((self.elapsed + 1e-6) * len(CREDIT_PAGES) / self.duration))

    def next_delay(self, remaining: float) -> float:
        """Длинная пауза также должна показать промежуточные страницы."""
        if self.page == len(CREDIT_PAGES) - 1:
            return remaining
        boundary = self.duration * (self.page + 1) / len(CREDIT_PAGES)
        return min(remaining, boundary - self.elapsed)

    def advance(self, seconds: float) -> None:
        self.elapsed = min(self.duration, self.elapsed + seconds)
