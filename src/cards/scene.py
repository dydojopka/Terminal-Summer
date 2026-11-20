"""Декорации автономного стенда и портрет соперницы, без сюжетного контроллера."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image
from rich.text import Text

from art_renderer import render_art
from story.resources import find_scene_path
from sprites_builder import SPRITE_POSITIONS, compose_layers, load_yaml_dict, parse_show_like, resolve_sprite


@dataclass(frozen=True)
class CardScene:
    category: str = "bg"
    name: str = "int_dining_hall_sunset"
    character: str = ""
    expression: str = "normal_pioneer"


@lru_cache(maxsize=2)
def _resources(ts_path):
    return load_yaml_dict(ts_path / "resources.yaml")


@lru_cache(maxsize=12)
def render_portrait(ts_path: Path, rival: str, style: str, width: int) -> Text:
    request = parse_show_like(f"show {rival} normal_pioneer size normal at center")
    resolved = resolve_sprite(_resources(ts_path), request, ts_path / "images")
    with compose_layers(resolved.picks, sprite_color="sunset") as sprite:
        left, top, right, bottom = sprite.getbbox()
        side = min(right - left, (bottom - top) // 2)
        center = (left + right) // 2
        with sprite.crop((center - side // 2, top, center + side // 2, top + side)) as face:
            return render_art(face, width=width, style=style, alpha=True)


@lru_cache(maxsize=32)
def render_card_scene(ts_path: Path, scene: CardScene, style: str, width: int) -> Text:
    path = find_scene_path(ts_path / "images", scene.category, scene.name)
    if path is None:
        raise FileNotFoundError(f"TS/images/{scene.category}/{scene.name}")
    with Image.open(path) as background, background.convert("RGBA") as canvas:
        if scene.character:
            request = parse_show_like(f"show {scene.character} {scene.expression} at center")
            resolved = resolve_sprite(_resources(ts_path), request, ts_path / "images")
            with compose_layers(resolved.picks, sprite_color="sunset") as sprite:
                height = min(sprite.height, round(canvas.height * 0.98))
                width_px = round(sprite.width * height / sprite.height)
                with sprite.resize((width_px, height), Image.Resampling.NEAREST) as fitted:
                    x = round(canvas.width * SPRITE_POSITIONS["center"] - width_px / 2)
                    canvas.alpha_composite(fitted, (max(0, x), canvas.height - height))
        return render_art(canvas, width=width, style=style, alpha=False)
