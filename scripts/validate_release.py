#!/usr/bin/env python3
"""Проверка сценария и визуальных ресурсов перед релизной сборкой."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from script_parser import DEFAULT_SCRIPT_STATE, DISPLAY_NAMES, ScriptParser
from sprites_builder import load_yaml_dict, parse_show_like, resolve_sprite


LABEL_RE = re.compile(r"label\s+([a-zA-Z0-9_]+):?$")
GOTO_RE = re.compile(r"goto\s+([a-zA-Z0-9_]+)$")
SCENE_RE = re.compile(r"scene\s+(bg|cg)\s+([a-zA-Z0-9_]+)")
SPEAKER_RE = re.compile(r'([a-zA-Z0-9_-]+)\s+"')
VARIABLE_RE = re.compile(r"\$([a-zA-Z0-9_.]+)")
SUPPORTED_PREFIXES = (
    "label ", "goto ", "if ", "if(", "else if ", "pause ",
    "scene ", "show ", "hide ", "play ", "stop ", "window ",
    "time ", "mode ", "menu", "load ", "with ",
)


def _scene_exists(category: str, name: str) -> bool:
    base = ROOT_DIR / "TS" / "game" / category / name
    return any(base.with_suffix(f".{extension}").exists() for extension in ("jpg", "jpeg", "png", "webp"))


def _load_target(script_path: Path, line: str) -> Path | None:
    match = re.fullmatch(r"load\s+(.+)", line)
    if not match:
        return None
    target = Path(match.group(1).strip().strip('"').strip("'"))
    if target.suffix.lower() != ".txt":
        target = target.with_suffix(".txt")
    return target if target.is_absolute() else script_path.parent / target


def validate_day(day: int) -> list[str]:
    errors: list[str] = []
    script_path = ROOT_DIR / "TS" / "text" / f"day{day}.txt"
    resources_path = ROOT_DIR / "TS" / "resources.yaml"
    assets_root = ROOT_DIR / "TS" / "game"

    if not script_path.is_file():
        return [f"Сценарий не найден: {script_path}"]
    if not resources_path.is_file():
        return [f"Описание спрайтов не найдено: {resources_path}"]

    parser = ScriptParser(script_path, app=None)
    lines = parser.lines
    source_lines = [
        (number, stripped)
        for number, raw_line in enumerate(
            script_path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if (stripped := raw_line.strip()) and not stripped.startswith("#")
    ]
    resources = load_yaml_dict(resources_path)

    labels: dict[str, int] = {}
    gotos: list[tuple[str, int]] = []
    scene_count = 0
    show_count = 0

    for number, line in source_lines:
        if not (
            line in {"{", "}", "else", "clear"}
            or line.startswith("$")
            or '"' in line
            or line.startswith(SUPPORTED_PREFIXES)
        ):
            errors.append(
                f"{script_path.name}:{number}: неизвестная команда: {line}"
            )

        label_match = LABEL_RE.fullmatch(line)
        if label_match:
            label = label_match.group(1)
            if label in labels:
                errors.append(f"{script_path.name}:{number}: повторная метка {label}")
            labels[label] = number

        goto_match = GOTO_RE.fullmatch(line)
        if goto_match:
            gotos.append((goto_match.group(1), number))

        for variable in VARIABLE_RE.findall(line):
            if variable not in DEFAULT_SCRIPT_STATE:
                errors.append(
                    f"{script_path.name}:{number}: неизвестная переменная ${variable}"
                )

        scene_match = SCENE_RE.match(line)
        if scene_match:
            scene_count += 1
            category, name = scene_match.groups()
            if not _scene_exists(category, name):
                errors.append(
                    f"{script_path.name}:{number}: отсутствует сцена "
                    f"TS/game/{category}/{name}.*"
                )

        if line.startswith("show "):
            show_count += 1
            try:
                request = parse_show_like(line)
                resolved = resolve_sprite(resources, request, assets_root)
                for pick in resolved.picks:
                    if not pick.absolute_path.is_file():
                        errors.append(
                            f"{script_path.name}:{number}: отсутствует слой спрайта "
                            f"{pick.absolute_path}"
                        )
            except Exception as exc:
                errors.append(
                    f"{script_path.name}:{number}: спрайт не собирается: {exc}"
                )

        speaker_match = SPEAKER_RE.match(line)
        if (
            speaker_match
            and speaker_match.group(1) != "th"
            and speaker_match.group(1) not in DISPLAY_NAMES
        ):
            errors.append(
                f"{script_path.name}:{number}: неизвестный говорящий "
                f"{speaker_match.group(1)}"
            )

        if line.startswith("load"):
            target = _load_target(script_path, line)
            if target is None:
                errors.append(f"{script_path.name}:{number}: некорректная команда load")
            elif not target.is_file():
                errors.append(f"{script_path.name}:{number}: файл перехода не найден: {target}")

    for label, number in gotos:
        if label not in labels:
            errors.append(f"{script_path.name}:{number}: переход на неизвестную метку {label}")

    depth = 0
    for number, line in source_lines:
        if line == "{":
            depth += 1
        elif line == "}":
            depth -= 1
            if depth < 0:
                errors.append(f"{script_path.name}:{number}: лишняя закрывающая скобка")
                depth = 0
    if depth:
        errors.append(f"{script_path.name}: незакрытых блоков: {depth}")

    print(
        f"Проверен день {day}: {len(lines)} команд, {len(labels)} меток, "
        f"{scene_count} сцен, {show_count} команд show."
    )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=int, required=True, help="Номер проверяемого дня")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        errors = validate_day(args.day)
    except Exception as exc:
        print(f"Ошибка валидатора: {exc}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        print(f"Проверка завершилась с ошибками: {len(errors)}", file=sys.stderr)
        return 1

    print("Сценарий и ресурсы готовы к сборке.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
