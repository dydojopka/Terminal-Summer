#!/usr/bin/env python3
"""Ручная сборка PNG-спрайтов из resources.yaml.

Пример из корня проекта:
  python scripts/build_sprites.py --line "show sl normal_pioneer_far at center" --no-preview
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rendering.sprites import compose_layers, load_yaml_dict, parse_show_like, resolve_sprite


MANUAL_COMMANDS = [
    "sl normal_pioneer_far size normal at center with dissolve",
]


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
    image = compose_layers(resolved.picks, req.extras.get("spritecolor"))

    name = sanitize_filename(line)
    out_path = out_dir / f"{index:03d}_{name}.png"
    try:
        image.save(out_path, format="PNG")
    finally:
        image.close()

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
        default="TS/resources.yaml",
        help="Путь к файлу ресурсов (по умолчанию: TS/resources.yaml)",
    )
    parser.add_argument(
        "--assets-root",
        default="TS/images",
        help="Папка изображений для путей из resources.yaml (по умолчанию: TS/images)",
    )
    parser.add_argument(
        "--out-dir",
        default="TS/images/sprites/generated",
        help="Папка для сгенерированных PNG-спрайтов",
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
