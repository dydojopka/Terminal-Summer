"""Разбор show-команд и сборка слоёв из resources.yaml для игры и инструментов."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


KEYWORDS = {
    "size", "at", "with", "behind", "xalign", "yalign", "zorder", "alpha",
    "spritecolor",
}

SPRITE_COLOR_FACTORS = {
    "sunset": (0.94, 0.82, 1.0),
    "night": (0.63, 0.78, 0.82),
}

SPRITE_POSITIONS = {
    "fleft": 0.18, "left": 0.30, "cleft": 0.40, "center": 0.50,
    "cright": 0.60, "right": 0.70, "fright": 0.82,
}
SPRITE_SIZES = {"normal": 1.0, "small": 0.86, "large": 1.12, "big": 1.12}


def normalize_sprite_position(position: str) -> str:
    # Именованные Ren'Py transforms адаптированы к статичным позициям терминала.
    position = {"us_d1": "left", "uv_pos": "center"}.get(position, position)
    if position not in SPRITE_POSITIONS:
        raise ValueError(f"Unknown sprite position: {position}")
    return position


@dataclass
class ShowRequest:
    raw: str
    character: str
    expression_tokens: list[str]
    size: str | None = None
    at: str | None = None
    transition: str | None = None
    extras: dict[str, str] = field(default_factory=dict)


@dataclass
class LayerPick:
    layer_name: str
    part_name: str
    relative_path: str
    absolute_path: Path


@dataclass
class ResolvedSprite:
    character: str
    pose: str
    line_label: str
    picks: list[LayerPick]
    metadata: ShowRequest


def load_yaml_dict(path: Path) -> dict:
    """Load YAML via PyYAML, fallback to yq if PyYAML is unavailable."""
    try:
        import yaml
    except ImportError:
        yaml = None

    if yaml is not None:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected YAML root type in {path}: {type(data).__name__}")
        return data

    if not shutil.which("yq"):
        raise RuntimeError(
            "PyYAML is not installed and 'yq' command was not found. "
            "Install PyYAML or yq to read resources.yaml."
        )

    proc = subprocess.run(
        ["yq", "-o=json", ".", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"Failed to parse YAML with yq: {err}")

    return json.loads(proc.stdout)


def parse_show_like(line: str) -> ShowRequest:
    line = line.strip()
    if not line:
        raise ValueError("Empty line")

    tokens = line.split()
    if tokens[0] == "show":
        tokens = tokens[1:]

    if not tokens:
        raise ValueError(f"Invalid command: {line}")

    character = tokens[0]
    if not re.fullmatch(r"[a-zA-Z0-9_]+", character):
        raise ValueError(f"Invalid sprite character: {character}")
    rest = tokens[1:]

    i = 0
    expression_tokens: list[str] = []
    while i < len(rest) and rest[i] not in KEYWORDS:
        expression_tokens.append(rest[i])
        i += 1

    req = ShowRequest(raw=line, character=character, expression_tokens=expression_tokens)

    while i < len(rest):
        key = rest[i]
        if key == "with":
            transition = " ".join(rest[i + 1:])
            if not re.fullmatch(r"\w+(?:\s+\d+(?:\.\d+)?)?(?:\s+(?:skip|await))?", transition):
                raise ValueError(f"Invalid sprite transition: {line}")
            req.transition = rest[i + 1]
            break
        if key not in {"size", "at", "behind", "spritecolor"} or i + 1 >= len(rest):
            raise ValueError(f"Invalid sprite modifier: {line}")
        value = rest[i + 1]

        if key == "size":
            if value not in SPRITE_SIZES:
                raise ValueError(f"Unknown sprite size: {value}")
            req.size = value
        elif key == "at":
            req.at = normalize_sprite_position(value)
        else:
            if key == "behind" and not re.fullmatch(r"[a-zA-Z0-9_]+", value):
                raise ValueError(f"Invalid behind character: {value}")
            if key == "spritecolor" and value not in SPRITE_COLOR_FACTORS:
                raise ValueError(f"Unknown sprite color: {value}")
            req.extras[key] = value
        i += 2

    return req


def _build_tokens_from_shortname(
    shortnames: dict,
    expression_tokens: list[str],
) -> tuple[list[str], str]:
    expression_text = " ".join(expression_tokens).strip()
    if expression_text and expression_text in shortnames:
        resolved = str(shortnames[expression_text]).split()
        return resolved, expression_text

    return list(expression_tokens), expression_text or "default"


def _pick_token_for_parts(
    available_tokens: list[str],
    parts: dict,
    default: str | None,
) -> tuple[str, str]:
    for idx, token in enumerate(list(available_tokens)):
        if token in parts:
            available_tokens.pop(idx)
            return token, str(parts[token])

    if default and default in parts:
        return default, str(parts[default])

    if parts:
        first_key = next(iter(parts))
        return str(first_key), str(parts[first_key])

    raise ValueError("Layer has no selectable parts")


def resolve_sprite(
    resources: dict,
    req: ShowRequest,
    assets_root: Path,
) -> ResolvedSprite:
    characters = resources.get("characters", {})
    if req.character not in characters:
        raise KeyError(f"Character '{req.character}' not found in resources.yaml")

    char_cfg = characters[req.character]
    shortnames = char_cfg.get("shortnames", {})
    poses = char_cfg.get("poses", {})
    if not poses:
        raise ValueError(f"Character '{req.character}' has no poses in resources.yaml")

    resolved_tokens, line_label = _build_tokens_from_shortname(shortnames, req.expression_tokens)

    if resolved_tokens and resolved_tokens[0] in poses:
        pose = resolved_tokens[0]
        layer_tokens = resolved_tokens[1:]
    else:
        pose = "mid" if "mid" in poses else next(iter(poses))
        layer_tokens = resolved_tokens

    pose_cfg = poses.get(pose)
    if not isinstance(pose_cfg, dict):
        raise ValueError(f"Pose '{pose}' for '{req.character}' is not a dict")

    available_tokens = list(layer_tokens)
    picks: list[LayerPick] = []

    for layer_name, layer_cfg in pose_cfg.items():
        # Layer with named parts
        if isinstance(layer_cfg, dict) and "parts" in layer_cfg:
            parts = layer_cfg.get("parts", {})
            default = layer_cfg.get("default")
            part_name, rel_path = _pick_token_for_parts(available_tokens, parts, default)
            abs_path = assets_root / rel_path
            picks.append(
                LayerPick(
                    layer_name=layer_name,
                    part_name=part_name,
                    relative_path=rel_path,
                    absolute_path=abs_path,
                )
            )
            continue

        # Flat direct layer path (rare)
        if isinstance(layer_cfg, str):
            rel_path = layer_cfg
            picks.append(
                LayerPick(
                    layer_name=layer_name,
                    part_name=layer_name,
                    relative_path=rel_path,
                    absolute_path=assets_root / rel_path,
                )
            )
            continue

        # Pose variants like: main_good: { body: ach/main_good.png }
        if isinstance(layer_cfg, dict):
            for sub_name, sub_path in layer_cfg.items():
                if isinstance(sub_path, str):
                    picks.append(
                        LayerPick(
                            layer_name=f"{layer_name}.{sub_name}",
                            part_name=sub_name,
                            relative_path=sub_path,
                            absolute_path=assets_root / sub_path,
                        )
                    )

    if not picks:
        raise ValueError(f"No drawable layers found for '{req.character}' pose '{pose}'")

    return ResolvedSprite(
        character=req.character,
        pose=pose,
        line_label=line_label,
        picks=picks,
        metadata=req,
    )


def compose_layers(
    picks: list[LayerPick], sprite_color: str | None = None
) -> Image.Image:
    loaded: list[tuple[LayerPick, Image.Image]] = []
    max_w = 0
    max_h = 0

    for pick in picks:
        if not pick.absolute_path.exists():
            raise FileNotFoundError(f"Layer image not found: {pick.absolute_path}")
        img = Image.open(pick.absolute_path).convert("RGBA")
        loaded.append((pick, img))
        max_w = max(max_w, img.width)
        max_h = max(max_h, img.height)

    if max_w <= 0 or max_h <= 0:
        raise ValueError("Invalid composed image size")

    canvas = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
    for _, img in loaded:
        canvas.alpha_composite(img, dest=(0, 0))
        img.close()

    factors = SPRITE_COLOR_FACTORS.get((sprite_color or "").lower())
    if factors:
        red, green, blue, alpha = canvas.split()
        channels = []
        for channel, factor in zip((red, green, blue), factors):
            lut = [min(255, round(value * factor)) for value in range(256)]
            channels.append(channel.point(lut))
            channel.close()
        tinted = Image.merge("RGBA", (*channels, alpha))
        for channel in channels:
            channel.close()
        alpha.close()
        canvas.close()
        canvas = tinted

    return canvas
