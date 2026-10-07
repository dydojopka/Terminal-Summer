#!/usr/bin/env python3
"""Read-only исходный инвентарь 1.0.0; не доказательство проходимости.

Запись выполняется только в явно указанный --output. Эталон не копируется:
для RPY сохраняются hashes и нормализованные LP-операции. Пользовательские
settings/saves/persistent не читаются и не изменяются.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import importlib.metadata
import io
import json
import platform
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.validate_release import (
    DEFAULT_SCRIPT_STATE,
    DISPLAY_NAMES,
    GOTO_RE,
    LABEL_RE,
    SCENE_RE,
    VARIABLE_RE,
    _load_target,
    parse_script_assignment,
    validate_script,
)

RELEASE_SCRIPTS = (
    "prologue.txt",
    *(f"day{day}.txt" for day in range(1, 8)),
    "epilogue.txt", "epilogue_mi.txt", "epilogue_uv.txt", "endings.txt",
)
OPTION_RE = re.compile(r'"(.+?)"(?:\s+if\s+(.+))?')
DIALOGUE_RE = re.compile(r'(?:([a-zA-Z0-9_-]+)\s+)?".*"')
LP_RE = re.compile(r'\$\s*(lp_\w+)\s*([+\-]?=)\s*(.+)')


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_fingerprint(root: Path, paths: list[Path]) -> dict:
    """Hash канонического списка относительных путей и SHA256 содержимого."""
    files = [
        {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)}
        for path in sorted(paths)
    ]
    encoded = json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": files}


def condition_errors(expression: str) -> list[str]:
    """Синтаксический аудит без eval и без подстановки значений состояния."""
    names = set()
    bare_names = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", VARIABLE_RE.sub("0", expression))
    errors = [
        f"имя без $ или неизвестный литерал: {name}"
        for name in bare_names if name.lower() not in ("true", "false", "null")
    ]

    def substitute(match: re.Match) -> str:
        name = f"state_{len(names)}"
        names.add(name)
        return name

    translated = VARIABLE_RE.sub(substitute, expression)
    translated = translated.replace("&&", " and ").replace("||", " or ")
    translated = re.sub(r"!(?!=)", " not ", translated)
    for literal, python_literal in (("true", "True"), ("false", "False"), ("null", "None")):
        translated = re.sub(rf"\b{literal}\b", python_literal, translated, flags=re.I)
    try:
        tree = ast.parse(translated.strip(), mode="eval")
    except SyntaxError as exc:
        return errors + [f"синтаксис условия: {exc.msg}"]
    allowed = (
        ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
        ast.USub, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
        ast.GtE, ast.Name, ast.Load, ast.Constant,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            errors.append(f"неподдерживаемая конструкция условия: {type(node).__name__}")
        elif isinstance(node, ast.Name) and node.id not in names:
            errors.append(f"имя без $ или неизвестный литерал: {node.id}")
        elif isinstance(node, ast.Constant) and node.value is not None and type(node.value) not in (bool, int):
            errors.append(f"неподдерживаемый литерал: {node.value!r}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and not (
            isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
        ):
            errors.append("минус допустим только в целом литерале")
    return sorted(set(errors))


def lp_operations(path: Path, *, reference: bool = False) -> list[dict]:
    operations = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = LP_RE.fullmatch(raw.strip())
        if not match:
            continue
        key, operator, value = match.groups()
        if reference and operator == "=":
            expanded = re.fullmatch(rf"{key}\s*([+\-])\s*(\d+)", value)
            if expanded:
                sign, value = expanded.groups()
                operator = sign + "="
        operations.append({"line": number, "key": key, "operator": operator, "value": value})
    return operations


def inventory_script(path: Path) -> dict:
    records = [
        (number, line)
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if (line := raw.strip()) and not line.startswith("#")
    ]
    normalized = "\n".join(line for _, line in records)
    inventory = {
        "path": f"TS/text/{path.name}", "sha256": file_hash(path),
        "runtime_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "command_count": len(records), "commands": {}, "labels": [], "gotos": [],
        "loads": [], "menus": [], "conditions": [], "assignments": [],
        "variables": {}, "speakers": {}, "resources": [], "diagnostics": [],
        "lp_operations": lp_operations(path),
    }
    commands = Counter()
    # Диапазоны нужны для инвентаря пунктов каждого меню, не для исполнения.
    blocks = {}
    openings = []
    for index, (_, line) in enumerate(records):
        if line == "{":
            openings.append(index)
        elif line == "}" and openings:
            blocks[openings.pop()] = index
    label = None
    for index, (number, line) in enumerate(records):
        location = {"line": number, "label": label}
        diagnostic = lambda detail: inventory["diagnostics"].append({**location, "detail": detail})
        label_match = LABEL_RE.fullmatch(line)
        goto_match = GOTO_RE.fullmatch(line)
        condition = None
        kind = line.split()[0]
        if label_match:
            label = label_match.group(1)
            location["label"] = label
            inventory["labels"].append({**location, "name": label})
            kind = "label"
        elif goto_match:
            inventory["gotos"].append({**location, "target": goto_match.group(1)})
        elif line.startswith("load "):
            target = _load_target(path, line)
            inventory["loads"].append({**location, "target": target.name if target else None})
        elif line in ("menu", "menu:"):
            menu = {**location, "syntax": line, "options": []}
            end = blocks.get(index + 1)
            if end is None:
                diagnostic("у меню нет корректного блока")
            else:
                menu["block_end_line"] = records[end][0]
                cursor = index + 2
                while cursor < end:
                    option = OPTION_RE.fullmatch(records[cursor][1])
                    option_end = blocks.get(cursor + 1)
                    if option is None or option_end is None:
                        diagnostic(f"неразобранный пункт меню на строке {records[cursor][0]}")
                        break
                    menu["options"].append({
                        "line": records[cursor][0], "text": option.group(1),
                        "condition": option.group(2), "block_end_line": records[option_end][0],
                    })
                    cursor = option_end + 1
            inventory["menus"].append(menu)
            kind = "menu"
        elif line.startswith(("if ", "if(", "else if ")):
            condition = line[len("else if"):] if line.startswith("else if ") else line[2:]
            kind = "else if" if line.startswith("else if ") else "if"
        elif line.startswith("$"):
            kind = "assignment"
            try:
                key, operator, value = parse_script_assignment(line)
                inventory["assignments"].append({
                    **location, "key": key, "operator": operator,
                    "value": value, "literal_type": type(value).__name__,
                })
            except ValueError as exc:
                diagnostic(str(exc))
        elif option := OPTION_RE.fullmatch(line):
            if index + 1 < len(records) and records[index + 1][1] == "{":
                kind = "option"
                condition = option.group(2)
            else:
                kind = "dialogue"
                inventory["speakers"].setdefault("narrator", []).append(location)
        elif dialogue := DIALOGUE_RE.fullmatch(line):
            kind = "dialogue"
            speaker = dialogue.group(1) or "narrator"
            inventory["speakers"].setdefault(speaker, []).append(location)
            if speaker not in DISPLAY_NAMES and speaker not in ("th", "narrator"):
                diagnostic(f"неизвестный говорящий: {speaker}")
        elif line not in ("{", "}", "else", "clear") and kind not in (
            "pause", "scene", "show", "hide", "play", "stop", "window",
            "time", "mode", "with", "volume",
        ):
            diagnostic(f"команда без явного runtime-контракта: {line}")
        commands[kind] += 1
        if condition is not None:
            condition = condition.strip()
            inventory["conditions"].append({**location, "expression": condition})
            for error in condition_errors(condition):
                diagnostic(f"{error}; выражение: {condition}")
        # Не ищем переменные в репликах: '$' в тексте не является DSL-чтением.
        variables = VARIABLE_RE.findall(line if kind == "assignment" else condition or "")
        for variable in variables:
            inventory["variables"].setdefault(variable, []).append(location)
        scene = SCENE_RE.match(line)
        if scene:
            inventory["resources"].append({**location, "kind": "scene", "category": scene[1], "name": scene[2]})
        elif line.startswith(("show ", "hide ")):
            inventory["resources"].append({**location, "kind": kind, "command": line})
    inventory["commands"] = dict(sorted(commands.items()))
    return inventory


def build_audit(root: Path = ROOT_DIR) -> dict:
    # Полный состав пока является предложением плана, не решением Q01.
    scripts = []
    missing = []
    for filename in RELEASE_SCRIPTS:
        path = root / "TS" / "text" / filename
        if path.is_file():
            scripts.append(inventory_script(path))
        else:
            missing.append(filename)
    variables = defaultdict(lambda: {"readers": [], "assignments": [], "literal_types": set()})
    for script in scripts:
        for key, locations in script["variables"].items():
            assignment_lines = {item["line"] for item in script["assignments"]}
            variables[key]["readers"].extend(
                {"path": script["path"], **location}
                for location in locations if location["line"] not in assignment_lines
            )
        for assignment in script["assignments"]:
            record = variables[assignment["key"]]
            record["assignments"].append({"path": script["path"], **assignment})
            record["literal_types"].add(assignment["literal_type"])
    schema = {}
    for key, record in sorted(variables.items()):
        registered = key in DEFAULT_SCRIPT_STATE
        schema[key] = {
            **record, "literal_types": sorted(record["literal_types"]),
            "registered": registered,
            "default": DEFAULT_SCRIPT_STATE.get(key),
            "default_type": type(DEFAULT_SCRIPT_STATE[key]).__name__ if registered else None,
            "lifetime": "persistent" if key.startswith("persistent.") else "playthrough",
            "first_assignment_in_file_order": next(iter(record["assignments"]), None),
        }
    reference_dir = root / "ES"
    reference = tree_fingerprint(root, list(reference_dir.glob("*.rpy")))
    reference["available"] = reference_dir.is_dir()
    comparison = []
    for script in scripts:
        path = reference_dir / (Path(script["path"]).stem + ".rpy")
        if not path.is_file():
            comparison.append({"script": script["path"], "status": "NO_REFERENCE"})
            continue
        original = lp_operations(path, reference=True)
        normalized = lambda ops: [(item["key"], item["operator"], item["value"]) for item in ops]
        comparison.append({
            "script": script["path"], "status": "MATCH" if normalized(original) == normalized(script["lp_operations"]) else "DIFF",
            "txt_count": len(script["lp_operations"]), "rpy_count": len(original),
            "reference_operations": original,
        })
    resources_path = root / "TS" / "resources.yaml"
    asset_paths = [p for p in (root / "TS" / "images").rglob("*") if p.is_file()]
    if resources_path.is_file():
        asset_paths.append(resources_path)
    assets = tree_fingerprint(root, asset_paths)
    archive_path = root / "TS.zip"
    assets["archive_sha256"] = file_hash(archive_path) if archive_path.is_file() else None
    assets["archive_note"] = "Hash установленного дерева не является hash исходного архива; без TS.zip архив не верифицирован."
    assets["configured_url"] = "https://storage.yandexcloud.net/terminal-summer-assets/TS.zip"
    packages = {}
    for name in ("textual", "Pillow", "pil2ansi", "PyInstaller", "PyYAML", "requests"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    static_errors = {}
    with contextlib.redirect_stdout(io.StringIO()):
        for script in scripts:
            static_errors[script["path"]] = validate_script(root / script["path"], root_dir=root)
    unknown = sorted(key for key, record in schema.items() if not record["registered"])
    diagnostics = sum(len(script["diagnostics"]) for script in scripts)
    return {
        "format_version": 1, "scope_status": "PROPOSED_NEEDS_DECISION",
        "revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(), "packages": packages},
        "scripts": scripts, "missing_scripts": missing, "state_schema_inventory": schema,
        "tooling": tree_fingerprint(root, [
            path for name in (
                "src/main.py", "src/script_parser.py", "src/script_conditions.py", "src/sprites_builder.py",
                "src/gameUI.tcss", "scripts/assets_manager.py", "scripts/validate_release.py",
                "scripts/audit_release.py", "scripts/build_and_run.sh", "scripts/build_and_run.bat",
                "requirements.txt", "tests/test_release.py", "tests/test_release_audit.py",
                "tests/test_script_contract.py", "tests/test_known_release_defects.py", "tests/smoke_onefile.py",
            ) if (path := root / name).is_file()
        ]),
        "reference": reference, "installed_assets": assets, "lp_comparison": comparison,
        "existing_static_checks": static_errors,
        "summary": {
            "files": len(scripts), "commands": sum(s["command_count"] for s in scripts),
            "labels": sum(len(s["labels"]) for s in scripts),
            "menus": sum(len(s["menus"]) for s in scripts),
            "conditions": sum(len(s["conditions"]) for s in scripts),
            "variables": len(schema), "unknown_variables": unknown,
            "lp_operations": sum(len(s["lp_operations"]) for s in scripts),
            "static_errors": sum(len(errors) for errors in static_errors.values()),
            "inventory_diagnostics": diagnostics,
        },
        "status": "FAIL" if missing or unknown or diagnostics or any(static_errors.values()) else "AUDITED_NOT_ROUTE_PROOF",
        "limitations": [
            "Никаких свидетелей концовок или доказательств покрытия веток.",
            "Типы литералов/существующие defaults — инвентарь, не утверждённая полная схема.",
            "Порядок первых присваиваний — файловый, не порядок достижимого исполнения.",
            "Существующая статика не доказывает корректную структуру всех команд/блоков.",
            "MATCH LP означает совпадение операций в файловом порядке, не условий их выполнения/порогов.",
            "Ресурсный аудит проверяет наличие файлов, не их декодирование/отрисовку.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Новый JSON-отчёт (существующий файл не перезаписывается)")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Отчёт уже существует: {args.output}")
    report = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"{report['status']}: {args.output}")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
