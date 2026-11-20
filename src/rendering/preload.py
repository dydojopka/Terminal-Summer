"""Жизненный цикл прогрева сценария без привязки к виджетам."""

import asyncio
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path

from rendering.jobs import SceneRenderer
from rendering.scene import SceneRenderSnapshot


class ScriptPreloader:
    def __init__(self, renderer: SceneRenderer) -> None:
        self._renderer = renderer
        self.task: asyncio.Task[None] | None = None
        self._filename: Path | None = None
        self._generation = 0

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def is_current(self, generation: int) -> bool:
        return generation == self._generation

    def _cancel(self) -> None:
        self._generation += 1
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self.task = None

    def start(
        self, filename: str | Path, prepare: Callable[[int], Coroutine[None, None, None]],
    ) -> asyncio.Task[None]:
        path = Path(filename).resolve()
        self._cancel()
        if path != self._filename:
            # При смене файла прежние кадры больше не нужны.
            self._renderer.clear()
            self._filename = path
        self.task = asyncio.create_task(prepare(self._generation))
        return self.task

    def clear(self) -> None:
        self._cancel()
        self._filename = None
        self._renderer.clear()

    async def warm_resources(
        self,
        generation: int,
        scenes: Sequence[tuple[str, str]],
        show_lines: Sequence[str],
        *,
        ts_path: Path,
        make_snapshot: Callable[[str, str], SceneRenderSnapshot],
        build_sprite: Callable[[str, int], object],
        report: Callable[[str, int, int], None],
    ) -> None:
        loop = asyncio.get_running_loop()
        total = len(scenes) + len(show_lines)
        for number, (category, name) in enumerate(scenes, start=1):
            if not self.is_current(generation):
                return
            report("scenes", number, total)
            # Снимаем состояние в основном потоке. Старый worker не может
            # захватить настройки или эпоху уже после отмены.
            snapshot = make_snapshot(category, name)
            if self._renderer.cache.frame(snapshot.key) is None:
                await loop.run_in_executor(None, self._renderer.render, snapshot, ts_path)
            await asyncio.sleep(0)
        for number, line in enumerate(show_lines, start=len(scenes) + 1):
            if not self.is_current(generation):
                return
            report("sprites", number, total)
            await loop.run_in_executor(None, build_sprite, line, generation)
            await asyncio.sleep(0)
