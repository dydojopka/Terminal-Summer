#!/usr/bin/env python3
"""Проверка сценария и визуальных ресурсов перед релизной сборкой."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from script_parser import (
    DEFAULT_SCRIPT_STATE,
    DISPLAY_NAMES,
    ScriptParser,
    parse_script_assignment,
)
from sprites_builder import load_yaml_dict, parse_show_like, resolve_sprite


LABEL_RE = re.compile(r"label\s+([a-zA-Z0-9_]+):?$")
GOTO_RE = re.compile(r"goto\s+([a-zA-Z0-9_]+)$")
SCENE_RE = re.compile(r"scene\s+(bg|cg)\s+([a-zA-Z0-9_]+)")
SPEAKER_RE = re.compile(r'([a-zA-Z0-9_-]+)\s+"')
VARIABLE_RE = re.compile(r"\$([a-zA-Z0-9_.]+)")
SUPPORTED_PREFIXES = (
    "label ", "goto ", "if ", "if(", "else if ", "pause ",
    "scene ", "show ", "hide ", "play ", "stop ", "window ",
    "time ", "mode ", "menu", "load ", "with ", "volume ",
)


@dataclass(frozen=True)
class RouteFrame:
    end: int
    return_pc: int


@dataclass
class RouteResult:
    status: str
    detail: str
    variables: dict
    choices: tuple[str, ...]
    visited_labels: frozenset[tuple[Path, str]]


@dataclass(frozen=True)
class RouteDocument:
    path: Path
    lines: tuple[str, ...]
    labels: dict[str, int]


def _route_document(path: Path, cache: dict[Path, RouteDocument]) -> RouteDocument:
    resolved = path.resolve()
    cached = cache.get(resolved)
    if cached is not None:
        return cached
    parser = ScriptParser(resolved, app=None)
    document = RouteDocument(resolved, parser.lines, parser.labels)
    cache[resolved] = document
    return document


def _block_range(lines: tuple[str, ...], start: int) -> tuple[int, int]:
    if start >= len(lines) or lines[start] != "{":
        raise ValueError("ожидалась открывающая скобка блока")
    depth = 1
    cursor = start + 1
    while cursor < len(lines):
        if lines[cursor] == "{":
            depth += 1
        elif lines[cursor] == "}":
            depth -= 1
            if depth == 0:
                return start + 1, cursor
        cursor += 1
    raise ValueError("незакрытый блок")


def _evaluate_route_condition(expression: str, variables: dict) -> bool:
    expression = expression.strip()
    if expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    expression = re.sub(
        r"\$[a-zA-Z0-9_.]+",
        lambda match: f'V("{match.group(0)[1:]}")',
        expression,
    )
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"!(?!=)", " not ", expression)
    expression = re.sub(r"\btrue\b", "True", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\bfalse\b", "False", expression, flags=re.IGNORECASE)
    expression = re.sub(r"\bnull\b", "None", expression, flags=re.IGNORECASE)

    def value(name: str):
        if name not in variables:
            raise ValueError(f"неизвестная переменная ${name}")
        return variables[name]

    try:
        return bool(eval(expression, {"__builtins__": {}}, {"V": value}))
    except Exception as exc:
        raise ValueError(f"некорректное условие: {exc}") from exc


def _apply_route_assignment(line: str, variables: dict) -> None:
    key, operation, value = parse_script_assignment(line)
    if key not in variables:
        raise ValueError(f"неизвестная переменная ${key}")
    current = variables[key]
    if operation == "=":
        variables[key] = value
        return
    if isinstance(current, bool):
        current = int(current)
    if isinstance(value, bool):
        value = int(value)
    if operation == "+=":
        variables[key] = current + value
    elif operation == "-=":
        variables[key] = current - value


def _route_load_target(document: RouteDocument, line: str) -> Path:
    target = _load_target(document.path, line)
    if target is None:
        raise ValueError("некорректная команда load")
    return target.resolve()


def _menu_options(
    document: RouteDocument,
    menu_pc: int,
    variables: dict,
) -> tuple[list[tuple[str, int, int]], int]:
    lines = document.lines
    body_start, body_end = _block_range(lines, menu_pc)
    cursor = body_start
    options: list[tuple[str, int, int]] = []
    while cursor < body_end:
        line = lines[cursor]
        match = re.fullmatch(r'"(.+?)"(?:\s+if\s+(.+))?', line)
        if not match:
            cursor += 1
            continue
        text, condition = match.groups()
        start, end = _block_range(lines, cursor + 1)
        if condition is None or _evaluate_route_condition(condition, variables):
            options.append((text, start, end))
        cursor = end + 1
    return options, body_end + 1


def explore_routes(
    start_path: Path,
    initial_states: list[dict],
    *,
    stop_at: tuple[Path, str],
    max_steps: int = 20000,
    deduplicate_states: bool = False,
) -> list[RouteResult]:
    """Исчерпывающе исполняет управляющую часть DSL без UI и задержек."""
    cache: dict[Path, RouteDocument] = {}
    start_document = _route_document(start_path, cache)
    stop_path, stop_label = stop_at[0].resolve(), stop_at[1]
    stack = [
        (
            start_document,
            0,
            tuple(),
            state.copy(),
            tuple(),
            frozenset(),
            frozenset(),
            0,
        )
        for state in initial_states
    ]
    results: list[RouteResult] = []
    globally_seen: set[tuple] = set()

    while stack:
        (
            document,
            pc,
            frames,
            variables,
            choices,
            seen,
            visited_labels,
            steps,
        ) = stack.pop()

        while True:
            while frames and pc >= frames[-1].end:
                pc = frames[-1].return_pc
                frames = frames[:-1]

            if steps >= max_steps:
                results.append(RouteResult(
                    "error", "превышен лимит шагов", variables.copy(), choices,
                    visited_labels,
                ))
                break
            if pc >= len(document.lines):
                results.append(RouteResult(
                    "eof", f"конец {document.path.name} без целевой метки",
                    variables.copy(), choices, visited_labels,
                ))
                break

            line = document.lines[pc]
            label_match = LABEL_RE.fullmatch(line)
            if (
                document.path == stop_path
                and label_match
                and label_match.group(1) == stop_label
            ):
                results.append(RouteResult(
                    "stop", stop_label, variables.copy(), choices, visited_labels,
                ))
                break

            state_key = (
                document.path,
                pc,
                frames,
                tuple(sorted(variables.items())),
            )
            if state_key in seen:
                results.append(RouteResult(
                    "cycle", f"цикл в {document.path.name}:{pc + 1}",
                    variables.copy(), choices, visited_labels,
                ))
                break
            if deduplicate_states and state_key in globally_seen:
                break
            if deduplicate_states:
                globally_seen.add(state_key)
            seen = seen | {state_key}
            steps += 1
            pc += 1

            try:
                if label_match:
                    visited_labels = visited_labels | {
                        (document.path, label_match.group(1))
                    }
                    continue

                goto_match = GOTO_RE.fullmatch(line)
                if goto_match:
                    label = goto_match.group(1)
                    if label not in document.labels:
                        raise ValueError(f"неизвестная метка {label}")
                    pc = document.labels[label]
                    frames = tuple()
                    continue

                if line.startswith("if ") or line.startswith("if("):
                    branches = []
                    condition = line[2:].strip()
                    cursor = pc
                    while True:
                        start, end = _block_range(document.lines, cursor)
                        cursor = end + 1
                        branches.append((condition, start, end))
                        if (
                            cursor < len(document.lines)
                            and document.lines[cursor].startswith("else if")
                        ):
                            condition = document.lines[cursor][len("else if"):].strip()
                            cursor += 1
                            continue
                        if cursor < len(document.lines) and document.lines[cursor] == "else":
                            start, end = _block_range(document.lines, cursor + 1)
                            cursor = end + 1
                            branches.append((None, start, end))
                        break
                    pc = cursor
                    for branch_condition, start, end in branches:
                        if branch_condition is None or _evaluate_route_condition(
                            branch_condition, variables
                        ):
                            frames = frames + (RouteFrame(end, cursor),)
                            pc = start
                            break
                    continue

                if line == "menu":
                    options, return_pc = _menu_options(document, pc, variables)
                    if not options:
                        raise ValueError("меню не содержит доступных вариантов")
                    for text, start, end in options[1:]:
                        stack.append((
                            document,
                            start,
                            frames + (RouteFrame(end, return_pc),),
                            variables.copy(),
                            choices + (text,),
                            seen,
                            visited_labels,
                            steps,
                        ))
                    text, start, end = options[0]
                    frames = frames + (RouteFrame(end, return_pc),)
                    pc = start
                    choices = choices + (text,)
                    continue

                if line.startswith("$"):
                    _apply_route_assignment(line, variables)
                    continue

                if line.startswith("load"):
                    target = _route_load_target(document, line)
                    document = _route_document(target, cache)
                    pc = 0
                    frames = tuple()
                    continue
            except (OSError, TypeError, ValueError) as exc:
                results.append(RouteResult(
                    "error", f"{document.path.name}:{pc}: {exc}",
                    variables.copy(), choices, visited_labels,
                ))
                break

    return results


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


def validate_day(day: int, *, stop_at: str | None = None) -> list[str]:
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
    if stop_at is not None:
        if stop_at not in parser.labels:
            return [f"{script_path.name}: отсутствует целевая метка {stop_at}"]
        lines = lines[:parser.labels[stop_at] + 1]
        cutoff = next(
            number for number, line in source_lines
            if (match := LABEL_RE.fullmatch(line)) and match.group(1) == stop_at
        )
        source_lines = [(number, line) for number, line in source_lines if number <= cutoff]
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

        if line.startswith("$"):
            try:
                variable, _, _ = parse_script_assignment(line)
                if variable not in DEFAULT_SCRIPT_STATE:
                    errors.append(
                        f"{script_path.name}:{number}: неизвестная переменная "
                        f"${variable}"
                    )
            except ValueError as exc:
                errors.append(f"{script_path.name}:{number}: {exc}")

        if line.startswith("pause") and not re.fullmatch(
            r"pause\s+(?:hard\s+)?\d+(?:\.\d+)?", line
        ):
            errors.append(f"{script_path.name}:{number}: некорректная команда pause: {line}")

        if line.startswith("scene") and not re.fullmatch(
            r"scene\s+(?:(?:bg|cg)\s+[a-zA-Z0-9_]+|color\s+(?:black|white))"
            r"(?:\s+with\s+\w+(?:\s+(?:skip|\d+(?:\.\d+)?))?)?", line
        ):
            errors.append(f"{script_path.name}:{number}: некорректная команда scene: {line}")

        for command, arguments in (
            ("window", {"show", "hide"}),
            ("mode", {"adv", "nvl"}),
            ("time", {"day", "sunset", "night"}),
        ):
            if line.startswith(command + " ") and line.split(maxsplit=1)[1] not in arguments:
                errors.append(f"{script_path.name}:{number}: некорректная команда {command}: {line}")

        goto_match = GOTO_RE.fullmatch(line)
        if goto_match:
            gotos.append((goto_match.group(1), number))

        for variable in VARIABLE_RE.findall(line):
            if variable not in DEFAULT_SCRIPT_STATE:
                if line.startswith("$"):
                    # Для присваиваний сообщение выше точнее и не дублируется.
                    continue
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
    parser.add_argument(
        "--day",
        type=int,
        action="append",
        required=True,
        help="Номер проверяемого дня; параметр можно повторять",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        errors = []
        for day in args.day:
            errors.extend(validate_day(day))
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
