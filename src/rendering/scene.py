"""Построение терминального кадра из снимка сцены, без Textual."""

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path

from PIL import Image
from rich.text import Text

from rendering.art import render_art
from rendering.sprites import SPRITE_POSITIONS, SPRITE_SIZES, normalize_sprite_position


@dataclass(frozen=True)
class RenderSprite:
    character: str
    show_line: str
    image_path: str
    at: str
    size: str
    behind: str | None
    order: int


@dataclass(frozen=True)
class SceneRenderSnapshot:
    category: str
    name: str
    sprites: tuple[RenderSprite, ...]
    width: int
    style: str
    cache_epoch: int
    diagnostics: tuple[str, str, str | None] = ("Неизвестный цвет сцены", "Файл не найден", None)

    @property
    def key(self) -> tuple:
        sprite_key = tuple(
            (
                sprite.character,
                sprite.show_line,
                sprite.image_path,
                sprite.at,
                sprite.size,
                sprite.behind,
                sprite.order,
            )
            for sprite in self.sprites
        )
        return (
            self.category, self.name, sprite_key, str(self.width), self.style,
            self.cache_epoch, 3, self.diagnostics,
        )


def _find_background(ts_path: Path, category: str, name: str) -> str | None:
    for extension in ("jpg", "jpeg", "png", "webp"):
        candidate = ts_path / "images" / category / f"{name}.{extension}"
        # Битая ссылка не мешает попробовать следующее расширение.
        if candidate.exists():
            return str(candidate)
    return None


def _composite_sprite(composed: Image.Image, sprite_img: Image.Image, sprite: RenderSprite) -> None:
    """Накладывает спрайт и освобождает переданную копию изображения."""
    try:
        scale = SPRITE_SIZES[sprite.size or "normal"]
        if abs(scale - 1.0) > 1e-3:
            resized = sprite_img.resize(
                (
                    max(1, int(sprite_img.width * scale)),
                    max(1, int(sprite_img.height * scale)),
                ),
                resample=Image.NEAREST,
            )
            sprite_img.close()
            sprite_img = resized
        max_sprite_height = max(1, int(composed.height * 0.98))
        is_full_canvas_overlay = sprite_img.size == composed.size
        if sprite_img.height > max_sprite_height and not is_full_canvas_overlay:
            resized = sprite_img.resize(
                (
                    max(1, int(sprite_img.width * (max_sprite_height / sprite_img.height))),
                    max_sprite_height,
                ),
                resample=Image.NEAREST,
            )
            sprite_img.close()
            sprite_img = resized
        position = SPRITE_POSITIONS[normalize_sprite_position(sprite.at or "center")]
        x = int(composed.width * position - sprite_img.width / 2)
        x = max(0, min(x, composed.width - sprite_img.width))
        y = max(0, composed.height - sprite_img.height)
        composed.alpha_composite(sprite_img, dest=(x, y))
    finally:
        sprite_img.close()


def render_scene(
    snapshot: SceneRenderSnapshot,
    ts_path: Path,
    load_rgba: Callable[[str, int], Image.Image],
) -> tuple[Text, bool]:
    """Возвращает арт и признак кешируемости; загрузчик отдаёт отдельные RGBA-копии."""
    if not snapshot.name or not snapshot.category:
        return Text(""), False

    composed = None
    try:
        if snapshot.category == "color":
            colors = {
                "black": (0, 0, 0, 255),
                "white": (255, 255, 255, 255),
            }
            rgba = colors.get(snapshot.name.lower())
            if rgba is None:
                label = snapshot.diagnostics[0]
                return Text(f"[{label}: {snapshot.name}]"), False
            composed = Image.new("RGBA", (1920, 1080), rgba)
        else:
            scene_path = _find_background(ts_path, snapshot.category, snapshot.name)
            if scene_path is None:
                label = snapshot.diagnostics[1]
                return Text(f"[{label}: TS/images/{snapshot.category}/{snapshot.name}.*]"), False
            composed = load_rgba(scene_path, snapshot.cache_epoch)
        for sprite in snapshot.sprites:
            if not sprite.image_path or not os.path.exists(sprite.image_path):
                continue
            sprite_img = load_rgba(sprite.image_path, snapshot.cache_epoch)
            _composite_sprite(composed, sprite_img, sprite)
        art = render_art(
            composed,
            width=snapshot.width,
            style=snapshot.style,
            alpha=not snapshot.sprites,
        )
        return art, True
    except Exception as exc:
        return Text(snapshot.diagnostics[2] or f"[Ошибка сборки сцены со спрайтами: {exc}]"), False
    finally:
        if composed is not None:
            composed.close()
