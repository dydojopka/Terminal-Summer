"""Очередь рендера и фоновые задачи подготовки следующих кадров."""

import asyncio
from pathlib import Path

from rich.text import Text

from rendering.cache import RenderCache
from rendering.scene import SceneRenderSnapshot, render_scene


class SceneRenderer:
    def __init__(self) -> None:
        self.cache = RenderCache()
        self._tasks: dict[tuple, asyncio.Task[Text]] = {}
        self._prefetch_tasks: set[asyncio.Task[Text]] = set()
        self._semaphore = asyncio.Semaphore(2)

    def render(self, snapshot: SceneRenderSnapshot, ts_path: Path) -> Text:
        cached = self.cache.frame(snapshot.key)
        if cached is not None:
            return cached
        art, cacheable = render_scene(snapshot, ts_path, self.cache.load_rgba)
        if cacheable:
            self.cache.store_frame(snapshot.key, art, snapshot.cache_epoch)
        return art

    async def _run(self, snapshot: SceneRenderSnapshot, ts_path: Path) -> Text:
        async with self._semaphore:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.render, snapshot, ts_path)

    async def get(self, snapshot: SceneRenderSnapshot, ts_path: Path) -> Text:
        key = snapshot.key
        cached = self.cache.frame(key)
        if cached is not None:
            return cached
        task = self._tasks.get(key)
        if task is None:
            task = asyncio.create_task(self._run(snapshot, ts_path))
            self._tasks[key] = task
        try:
            return await task
        finally:
            if self._tasks.get(key) is task:
                self._tasks.pop(key, None)

    def prefetch(self, snapshot: SceneRenderSnapshot | None, ts_path: Path) -> None:
        if snapshot is None or self.cache.frame(snapshot.key) is not None:
            return
        task = asyncio.create_task(self.get(snapshot, ts_path))
        self._prefetch_tasks.add(task)
        task.add_done_callback(self._finish_prefetch)

    def _finish_prefetch(self, task: asyncio.Task[Text]) -> None:
        self._prefetch_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            # Prefetch — оптимизация; ошибка не должна останавливать сценарий.
            pass

    def clear(self) -> None:
        self.cache.clear()
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        for task in self._prefetch_tasks:
            task.cancel()
        self._prefetch_tasks.clear()
