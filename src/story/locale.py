"""Translations decorate the canonical DSL; they never become source lines."""

import hashlib
import json
import re
from pathlib import Path

from story.structure import OPTION_RE, read_block_range

DIALOGUE_RE = re.compile(r'(?:([a-zA-Z0-9_-]+)\s+)?"(.*)"')
DSL_ESCAPE = re.compile(r'\\([n"\\])')
SPEAKER_KEYS = {
    "slp": "pika", "slg": "Girl", "sa": "Sasha", "unp": "pika", "dvp": "pika",
    "dvg": "Girl", "elp": "pi", "ro": "Router", "usp": "pika", "usg": "Girl",
    "mtp": "Camp_leader", "mt_voice": "Voice", "csp": "Nurse", "mip": "pika",
    "ma": "Masha", "uvp": "Strange_girl", "my": "Myself",
    "FIXME_voice": "Voice", "bush": "Voice", "message": "Message",
}


def read_script_source(path: Path):
    with path.open(encoding="utf-8") as source:
        return tuple(
            (number, line.strip()) for number, line in enumerate(source, 1)
            if line.strip() and not line.strip().startswith("#")
        )


def script_content_hash(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def decode_dsl_dialogue(text: str) -> str:
    return DSL_ESCAPE.sub(
        lambda m: {"n": "\n", '"': '"', "\\": "\\"}[m[1]], text.replace("%%", "%")
    )


def text_sites(lines):
    """Yield (pc, kind, label, speaker, text), following the DSL's own menu grammar."""
    choices = {}
    for pc, line in enumerate(lines):
        if line not in ("menu", "menu:"):
            continue
        cursor, close = read_block_range(lines, pc + 1)
        while cursor < close:
            match = OPTION_RE.fullmatch(lines[cursor])
            if match is None:
                raise ValueError(f"Invalid menu option at pc {cursor}")
            choices[cursor] = match[1]
            _, option_end = read_block_range(lines, cursor + 1)
            cursor = option_end + 1
    label = ""
    for pc, line in enumerate(lines):
        if line.startswith("label "):
            label = line.split()[1].removesuffix(":")
        elif pc in choices:
            yield pc, "choice", label, "", choices[pc]
        elif (match := DIALOGUE_RE.fullmatch(line)) is not None:
            yield pc, "dialogue", label, match[1] or "", decode_dsl_dialogue(match[2])


def read_chapter_locale(path: Path, content_hash: str, line_count: int) -> dict[int, str]:
    with path.open(encoding="utf-8") as source:
        data = json.load(source)
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1 or data.get("content_hash") != content_hash
            or not isinstance(data.get("lines"), dict)):
        raise ValueError("Invalid or stale chapter translation")
    result = {}
    for key, entry in data["lines"].items():
        if (not re.fullmatch(r"0|[1-9][0-9]*", key) or not 0 <= (pc := int(key)) < line_count
                or not isinstance(entry, list) or len(entry) != 2
                or not all(isinstance(value, str) and value for value in entry)
                or any(ord(char) < 32 and char not in "\n\t" for char in entry[0])):
            raise ValueError(f"Invalid translation entry at pc {key}")
        result[pc] = entry[0]
    return result


def load_chapter_locale(chapter: Path, language: str, content_hash: str, count: int,
                        bundled_text: Path | None) -> dict[int, str]:
    if language != "en":
        return {}
    # Prefer local packs; a stale local pack must not prevent matching bundled data.
    for root in (chapter.parent, bundled_text):
        if root is None:
            continue
        try:
            return read_chapter_locale(root / language / chapter.with_suffix(".json").name,
                                       content_hash, count)
        except (OSError, ValueError):
            continue
    return {}


def load_interface_locale(language: str, *roots: Path, filename: str = "interface.json") -> dict[str, str]:
    if language != "en":
        return {}
    for root in roots:
        try:
            with (root / language / filename).open(encoding="utf-8") as source:
                data = json.load(source)
            if isinstance(data, dict) and all(isinstance(value, str) for value in data.values()):
                return data
        except (OSError, ValueError):
            continue
    return {}
