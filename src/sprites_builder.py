#!/usr/bin/env python3
"""Sprite builder for layered assets from resources.yaml.

Usage examples:
  python sprites_builder.py \
      --line "sl normal_pioneer_far size normal at center with dissolve"

  python sprites_builder.py \
      --line "show sl normal_pioneer_far size normal at center with dissolve" \
      --line "show dv smile_pioneer size normal at right" \
      --out-dir TS/game/sprites/generated

If no --line / --from-file is passed, commands are taken from MANUAL_COMMANDS.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


# Put quick manual tests here.
MANUAL_COMMANDS = [
    "sl normal_pioneer_far size normal at center with dissolve",
]

KEYWORDS = {"size", "at", "with", "behind", "xalign", "yalign", "zorder", "alpha"}


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
    """Load YAML using yq (no PyYAML dependency)."""
    if not shutil.which("yq"):
        raise RuntimeError("Command 'yq' is not installed. Install it to read resources.yaml.")

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
    rest = tokens[1:]

    i = 0
    expression_tokens: list[str] = []
    while i < len(rest) and rest[i] not in KEYWORDS:
        expression_tokens.append(rest[i])
        i += 1

    req = ShowRequest(raw=line, character=character, expression_tokens=expression_tokens)

    while i < len(rest):
        key = rest[i]
        if i + 1 < len(rest):
            value = rest[i + 1]
        else:
            value = ""

        if key == "size":
            req.size = value
        elif key == "at":
            req.at = value
        elif key == "with":
            req.transition = value
        else:
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

    if len(expression_tokens) == 1 and expression_tokens[0] in shortnames:
        resolved = str(shortnames[expression_tokens[0]]).split()
        return resolved, expression_tokens[0]

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


def compose_layers(picks: list[LayerPick]) -> Image.Image:
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

    return canvas


def sanitize_filename(text: str) -> str:
    text = text.strip().replace("show ", "")
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)
    text = text.strip("._")
    return text[:100] or "sprite"


def maybe_preview_in_kitty(path: Path) -> bool:
    if "KITTY_WINDOW_ID" not in os.environ:
        return False

    kitten = shutil.which("kitten")
    if kitten:
        subprocess.run([kitten, "icat", str(path)], check=False)
        return True

    kitty = shutil.which("kitty")
    if kitty:
        subprocess.run([kitty, "+kitten", "icat", str(path)], check=False)
        return True

    return False


def load_lines(args: argparse.Namespace) -> list[str]:
    lines: list[str] = []

    if args.from_file:
        file_path = Path(args.from_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")
        for raw in file_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            lines.append(raw)

    if args.line:
        for item in args.line:
            item = item.strip()
            if item:
                lines.append(item)

    if not lines:
        lines = [line for line in MANUAL_COMMANDS if line.strip()]

    return lines


def build_one(
    resources: dict,
    line: str,
    assets_root: Path,
    out_dir: Path,
    index: int,
    preview: bool,
) -> Path:
    req = parse_show_like(line)
    resolved = resolve_sprite(resources, req, assets_root)
    image = compose_layers(resolved.picks)

    name = sanitize_filename(line)
    out_path = out_dir / f"{index:03d}_{name}.png"
    image.save(out_path, format="PNG")

    print(f"[OK] {line}")
    print(
        f"     character={resolved.character} pose={resolved.pose} "
        f"size={req.size or '-'} at={req.at or '-'} with={req.transition or '-'}"
    )
    print("     layers:")
    for pick in resolved.picks:
        print(f"       {pick.layer_name}: {pick.part_name} -> {pick.relative_path}")
    print(f"     saved: {out_path}")

    if preview:
        shown = maybe_preview_in_kitty(out_path)
        if shown:
            print("     preview: shown via kitty icat")
        else:
            print("     preview: skipped (not kitty or icat unavailable)")

    return out_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build layered sprite PNGs from resources.yaml show-like lines."
    )
    parser.add_argument(
        "--resources",
        default="resources.yaml",
        help="Path to resources.yaml (default: resources.yaml)",
    )
    parser.add_argument(
        "--assets-root",
        default="TS",
        help="Root folder for relative asset paths from resources.yaml (default: TS)",
    )
    parser.add_argument(
        "--out-dir",
        default="../TS/game/sprites/generated",
        help="Output folder for generated PNG sprites",
    )
    parser.add_argument(
        "--line",
        action="append",
        help="Show-like line. Can be used multiple times.",
    )
    parser.add_argument(
        "--from-file",
        help="Text file with one show-like line per row (comments with # are ignored).",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Disable kitty preview even if running in kitty.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    resources_path = Path(args.resources)
    assets_root = Path(args.assets_root)
    out_dir = Path(args.out_dir)

    if not resources_path.exists():
        print(f"[ERROR] resources file not found: {resources_path}", file=sys.stderr)
        return 2
    if not assets_root.exists():
        print(f"[ERROR] assets root not found: {assets_root}", file=sys.stderr)
        return 2

    try:
        resources = load_yaml_dict(resources_path)
        lines = load_lines(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    if not lines:
        print("[ERROR] no input lines")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    preview = not args.no_preview

    failed = 0
    for idx, line in enumerate(lines, start=1):
        try:
            build_one(resources, line, assets_root, out_dir, idx, preview)
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {line}", file=sys.stderr)
            print(f"       {exc}", file=sys.stderr)

    if failed:
        print(f"\nDone with errors: {failed}/{len(lines)} failed", file=sys.stderr)
        return 1

    print(f"\nDone: {len(lines)} sprite(s) generated in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
