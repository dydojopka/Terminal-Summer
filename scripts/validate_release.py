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
    SCRIPT_STATE_TYPES,
    apply_script_assignment,
    parse_script_assignment,
)
from sprites_builder import load_yaml_dict, parse_show_like, resolve_sprite
from script_conditions import evaluate_script_condition, parse_script_condition


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
    return evaluate_script_condition(expression, variables, SCRIPT_STATE_TYPES)


def _apply_route_assignment(line: str, variables: dict) -> None:
    apply_script_assignment(line, variables)


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

                if line in ("menu", "menu:"):
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


def _scene_exists(category: str, name: str, assets_root: Path | None = None) -> bool:
    base = (assets_root or ROOT_DIR / "TS" / "images") / category / name
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
    return validate_script(
        ROOT_DIR / "TS" / "text" / f"day{day}.txt", stop_at=stop_at
    )


def validate_script(
    script_path: Path, *, stop_at: str | None = None, root_dir: Path | None = None
) -> list[str]:
    """Применяет существующие статические проверки к любому TXT, без обхода."""
    errors: list[str] = []
    project_root = ROOT_DIR if root_dir is None else root_dir
    resources_path = project_root / "TS" / "resources.yaml"
    assets_root = project_root / "TS" / "images"

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
        condition = None
        if line.startswith(("if ", "if(")):
            condition = line[2:].strip()
        elif line.startswith("else if "):
            condition = line[len("else if "):].strip()
        elif option := re.fullmatch(r'".+?"\s+if\s+(.+)', line):
            condition = option.group(1)
        if condition is not None:
            try:
                parse_script_condition(condition, SCRIPT_STATE_TYPES)
            except ValueError as exc:
                errors.append(f"{script_path.name}:{number}: {exc}; выражение: {condition}")
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
                else:
                    apply_script_assignment(line, DEFAULT_SCRIPT_STATE.copy())
            except ValueError as exc:
                errors.append(f"{script_path.name}:{number}: {exc}")

        if line.startswith("pause") and not re.fullmatch(
            r"pause\s+(?:hard\s+)?\d+(?:\.\d+)?", line
        ):
            errors.append(f"{script_path.name}:{number}: некорректная команда pause: {line}")

        if line.startswith("scene") and not re.fullmatch(
            r"scene\s+(?:(?:bg|cg)\s+[a-zA-Z0-9_]+|color\s+(?:black|white))"
            r"(?:\s+with\s+\w+(?:\s+\d+(?:\.\d+)?)?(?:\s+skip)?)?", line
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
            if not _scene_exists(category, name, assets_root):
                errors.append(
                    f"{script_path.name}:{number}: отсутствует сцена "
                    f"TS/images/{category}/{name}.*"
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
        f"Проверен {script_path.name}: {len(lines)} команд, {len(labels)} меток, "
        f"{scene_count} сцен, {show_count} команд show."
    )
    return errors


def validate_route_reduction(
    lines: tuple[str, ...], entry_states: list[dict], control_keys: tuple[str, ...]
) -> list[str]:
    """Доказывает применимость группировки входов и переноса LP-дельт."""
    errors = []
    condition_variables = set()
    for line in lines:
        if line.startswith(("if ", "if(", "else if ")) or re.fullmatch(
            r'".+?"\s+if\s+.+', line
        ):
            condition_variables.update(VARIABLE_RE.findall(line))
        if line.startswith("$"):
            try:
                key, operation, value = parse_script_assignment(line)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if key in control_keys:
                errors.append(f"обход day3: управляющий вход ${key} изменяется в сценарии")
            if key.startswith("lp_") and (
                operation == "=" or type(value) is not int
            ):
                errors.append(f"обход day3: перенос LP-дельт невозможен для {line}")
    for key in sorted(condition_variables):
        if key.startswith("lp_"):
            errors.append(f"обход day3: условие зависит от ${key}; перенос LP-дельт небезопасен")
        elif key not in control_keys and len({state.get(key) for state in entry_states}) > 1:
            errors.append(f"обход day3: группировка не учитывает переменный вход ${key}")
    return errors


def validate_day3_routes() -> list[str]:
    """Проверяет все развилки day3 и контракт входа в day4_main1."""
    errors: list[str] = []
    prologue_path = ROOT_DIR / "TS" / "text" / "prologue.txt"
    day3_path = ROOT_DIR / "TS" / "text" / "day3.txt"
    day4_path = ROOT_DIR / "TS" / "text" / "day4.txt"
    errors.extend(validate_day(4, stop_at="day4_main1"))
    if errors:
        return errors

    predecessor_results = explore_routes(
        prologue_path,
        [DEFAULT_SCRIPT_STATE],
        stop_at=(day3_path, "day3_main1"),
        max_steps=30000,
        deduplicate_states=True,
    )
    predecessor_failures = [
        result for result in predecessor_results if result.status != "stop"
    ]
    for result in predecessor_failures[:20]:
        errors.append(f"предыстория day3: {result.status}: {result.detail}")
    if predecessor_failures:
        return errors

    entry_states_by_key = {
        tuple(sorted(result.variables.items())): result.variables
        for result in predecessor_results
    }
    entry_states = list(entry_states_by_key.values())
    if not entry_states:
        return ["day3: не найдено ни одного достижимого входного состояния"]
    control_keys = ("d1_keys", "d2_gave_keys", "day2_un")
    day3_document = _route_document(day3_path, {})
    day4_document = _route_document(day4_path, {})
    checked_lines = day3_document.lines + day4_document.lines[
        :day4_document.labels["day4_main1"]
    ]
    errors.extend(validate_route_reduction(checked_lines, entry_states, control_keys))
    if errors:
        return errors
    representatives: dict[tuple, dict] = {}
    for state in entry_states:
        key = tuple(state[name] for name in control_keys)
        representatives.setdefault(key, state)

    route_results = explore_routes(
        day3_path,
        list(representatives.values()),
        stop_at=(day4_path, "day4_main1"),
        max_steps=30000,
    )
    route_failures = [result for result in route_results if result.status != "stop"]
    for result in route_failures[:20]:
        errors.append(f"маршрут day3: {result.status}: {result.detail}")
    if route_failures:
        return errors

    choice_traces = {result.choices for result in route_results}
    if len(choice_traces) != 52:
        errors.append(
            f"day3: ожидалось 52 маршрута выбора, получено {len(choice_traces)}"
        )
    routes_by_control: dict[tuple, list[RouteResult]] = {}
    for result in route_results:
        control = tuple(result.variables[name] for name in control_keys)
        routes_by_control.setdefault(control, []).append(result)
    for control, results in routes_by_control.items():
        traces = {result.choices for result in results}
        if len(traces) != 52:
            errors.append(
                f"day3: вход {control!r} даёт {len(traces)} маршрутов вместо 52"
            )

    day3_labels = set(_route_document(day3_path, {}).labels)
    visited_day3_labels = {
        label
        for result in route_results
        for path, label in result.visited_labels
        if path == day3_path.resolve()
    }
    unreachable = sorted(day3_labels - visited_day3_labels)
    if unreachable:
        errors.append(f"day3: недостижимые метки: {', '.join(unreachable)}")

    evening_flags = (
        "day3_sl_evening",
        "day3_un_evening",
        "day3_us_evening",
        "day3_dv_evening",
        "day3_got_fail",
    )
    morning_flags = (
        "goto_day4_std_morning",
        "goto_day4_fail_morning",
        "goto_day4_us_morning",
    )
    for result in route_results:
        state = result.variables
        active_evenings = [name for name in evening_flags if state[name]]
        active_mornings = [name for name in morning_flags if state[name]]
        if len(active_evenings) != 1:
            errors.append(
                f"day3: маршрут {result.choices!r} выставил вечерние флаги "
                f"{active_evenings!r}"
            )
            continue
        if len(active_mornings) != 1:
            errors.append(
                f"day3: маршрут {result.choices!r} выставил morning-флаги "
                f"{active_mornings!r}"
            )
            continue

        evening = active_evenings[0]
        expected_morning = (
            "day4_us_morning"
            if evening == "day3_us_evening"
            else "day4_fail_morning"
            if evening == "day3_got_fail"
            else "day4_std_morning"
        )
        if (day4_path.resolve(), expected_morning) not in result.visited_labels:
            errors.append(
                f"day3: маршрут {result.choices!r} не вошёл в {expected_morning}"
            )

    # Полные состояния отличаются persistent/card-флагами, которые day3 не
    # читает и не меняет. LP влияют на результат, но не на выбор ветки, поэтому
    # управляющий граф достаточно исполнить для шести проекций. Затем каждую
    # реально достижимую LP-комбинацию прогоняем через рассчитанные дельты всех
    # 52 маршрутов.
    active_day3_variables = set()
    for raw_line in day3_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#"):
            active_day3_variables.update(VARIABLE_RE.findall(stripped))
    relevant_entry_states = {
        tuple((name, state[name]) for name in sorted(active_day3_variables))
        for state in entry_states
    }
    representative_by_control = {
        tuple(state[name] for name in control_keys): state
        for state in representatives.values()
    }
    checked_state_routes = 0
    for projection in relevant_entry_states:
        values = dict(projection)
        for lp_name in ("lp_sl", "lp_un", "lp_dv", "lp_us"):
            if not isinstance(values[lp_name], int):
                errors.append(
                    f"day3: входное значение {lp_name} не является int: "
                    f"{values[lp_name]!r}"
                )
        control = tuple(values[name] for name in control_keys)
        representative = representative_by_control[control]
        for result in routes_by_control.get(control, []):
            for lp_name in ("lp_sl", "lp_un", "lp_dv", "lp_us"):
                delta = result.variables[lp_name] - representative[lp_name]
                final_value = values[lp_name] + delta
                if not isinstance(final_value, int):
                    errors.append(
                        f"day3: маршрут {result.choices!r} дал нечисловой "
                        f"{lp_name}: {final_value!r}"
                    )
            checked_state_routes += 1

    if any(name.startswith("persistent.") for name in active_day3_variables):
        errors.append("day3: маршрут не должен менять persistent-переменные")

    print(
        "Обход day3: "
        f"{len(entry_states)} полных входных состояний, "
        f"{len(relevant_entry_states)} значимых проекций, "
        f"{len(representatives)} комбинаций управления, "
        f"{len(choice_traces)} маршрута; "
        f"композиционно проверено {checked_state_routes} значимых и "
        f"{len(entry_states) * len(choice_traces)} полных пар "
        "состояние/маршрут."
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
        if 3 in args.day:
            errors.extend(validate_day3_routes())
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
