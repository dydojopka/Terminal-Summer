"""Общие ресурсы явного релизного набора TXT, без запуска игры."""

from pathlib import Path
import re

from sprites_builder import load_yaml_dict, parse_show_like, resolve_sprite

RELEASE_SCRIPTS = (
    "prologue.txt", *(f"day{day}.txt" for day in range(1, 8)),
    "epilogue.txt", "epilogue_mi.txt", "epilogue_uv.txt", "endings.txt",
)
SCENE_RE = re.compile(r"scene\s+(bg|cg)\s+([a-zA-Z0-9_]+)")


def resource_manifest(lines) -> dict:
    scenes, shows = set(), set()
    for raw in lines:
        line = raw.strip()
        match = SCENE_RE.match(line)
        if match:
            scenes.add(match.groups())
        elif line.startswith("show "):
            shows.add(line)
    return {"scenes": tuple(sorted(scenes)), "show_lines": tuple(sorted(shows))}


def find_scene_path(images: Path, category: str, name: str) -> Path | None:
    for extension in ("jpg", "jpeg", "png", "webp"):
        path = images / category / f"{name}.{extension}"
        if path.exists() or path.is_symlink():
            return path
    return None


def visual_asset_problems(ts_dir: Path, *, verify_images=False) -> tuple[list[str], list[str]]:
    """Возвращает отдельно недостающие и неисправные/небезопасные ресурсы.

    Проверка полноты самих TXT принадлежит релизному валидатору: архив ассетов
    не является источником сценария и не должен скачиваться ради ошибки DSL.
    """
    missing, invalid = [], []
    yaml_path = ts_dir / "resources.yaml"
    if not yaml_path.exists():
        return [str(yaml_path)], []
    try:
        resources = load_yaml_dict(yaml_path)
    except Exception as exc:
        return [], [f"Описание ресурсов {yaml_path}: {exc}"]
    paths = set()
    for filename in RELEASE_SCRIPTS:
        script = ts_dir / "text" / filename
        if not script.is_file():
            continue
        manifest = resource_manifest(script.read_text(encoding="utf-8").splitlines())
        for category, name in manifest["scenes"]:
            path = find_scene_path(ts_dir / "images", category, name)
            if path is None:
                missing.append(str(ts_dir / "images" / category / f"{name}.*"))
            else:
                paths.add(path)
        for line in manifest["show_lines"]:
            try:
                resolved = resolve_sprite(resources, parse_show_like(line), ts_dir / "images")
                paths.update(pick.absolute_path for pick in resolved.picks)
            except (KeyError, TypeError, ValueError) as exc:
                invalid.append(f"{filename}: {line}: {exc}")
    root = (ts_dir / "images").resolve()
    for path in sorted(paths):
        if not path.resolve().is_relative_to(root):
            invalid.append(f"Путь изображения выходит за пределы TS/images: {path}")
        elif not path.exists() and not path.is_symlink():
            missing.append(str(path))
        elif not path.is_file() or path.stat().st_size == 0:
            invalid.append(f"Повреждённое изображение: {path}")
        elif verify_images:
            try:
                from PIL import Image
                with Image.open(path) as image:
                    image.load()
            except (OSError, ValueError) as exc:
                invalid.append(f"Изображение не декодируется: {path}: {exc}")
    return sorted(set(missing)), sorted(set(invalid))
