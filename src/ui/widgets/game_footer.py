"""Панель горячих клавиш без удержания старых кнопок."""

from textual.widgets import Footer


class GameFooter(Footer):
    async def recompose(self) -> None:
        await super().recompose()
        # Textual 8.0.1 удаляет подписки закрытых FooterKey только при
        # обновлении compact. Запускаем эту очистку, не меняя его значение.
        self.mutate_reactive(Footer.compact)
