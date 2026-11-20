#!/usr/bin/env python3
"""Build and audit English chapter catalogs from a local Everlasting Summer install."""

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

from renpy_translation_source import kind, nodes, read_rpyc
from english_source_matches import REVIEWED_SAYS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from file_io import write_json_atomic
from script_locale import read_chapter_locale, read_script_source, script_content_hash, text_sites
from script_locale import SPEAKER_KEYS
from script_parser import DISPLAY_NAMES
from script_resources import RELEASE_SCRIPTS
from script_structure import read_block_range
from camp_map import map_choice_zones
from endings_catalog import load_endings_catalog


REN_TAG = re.compile(r"(?<!\{)\{(/?\s*i|/?b|w)\}")
DSL_TAG = re.compile(r"</?[ib]>|<w>")
# Transcribed from Steam archive.rpa: images/maps/map_en.jpg. Map choices in
# Terminal Summer replace the original clickable image, not Ren'Py menus.
MAP_EN = {
    "boat_station": "BOAT-HOUSE", "camp_entrance": "BUS STOP", "clubs": "CLUB HOUSE",
    "dining_hall": "DINNING-HALL", "estrade": "SCENE", "forest": "FOREST",
    "square": "SQUARE", "library": "LIBRARY", "medic_house": "INFIRMARY",
    "music_club": "MUSIC CLUB", "sport_area": "FOOTBALL", "beach": "BEACH",
}


def original_text(text):
    return REN_TAG.sub(lambda m: f"<{m[1].replace(' ', '')}>", text).replace("%%", "%")


def visible(text):
    return " ".join(DSL_TAG.sub("", text).split())


def words(text):
    """Only ignore typography; require exactly the same words and numbers."""
    return tuple(re.findall(r"\w+", visible(text).replace("ё", "е").replace("Ё", "Е")))


def renderable(text, *, choice=False):
    # Never guess at interpolation, unfamiliar Ren'Py tags, or unsupported timing.
    remainder = DSL_TAG.sub("", text)
    if re.search(r"[{}]|(?<!\[)\[[a-zA-Z_][^\]\n]*\]|%\(", remainder):
        return False
    stack = []
    for match in DSL_TAG.finditer(text):
        if choice:
            return False
        tag = match[0][1:-1]
        if tag in ("i", "b"):
            stack.append(tag)
        elif tag == "w":
            if stack:  # Runtime styles cannot span a pause.
                return False
        elif not stack or stack.pop() != tag[1:]:
            return False
    return bool(text.strip()) and not stack


def statements(path, slot):
    return list(nodes(read_rpyc(path, slot=slot)))


def say_blocks(ast, language):
    blocks = {}
    for node in ast:
        if kind(node) != "Translate" or node.language != language:
            continue
        say = [child for child in node.block if kind(child) == "Say"]
        if len(say) != 1:
            continue
        if node.identifier in blocks:
            raise ValueError(f"Duplicate Ren'Py translate ID: {node.identifier}")
        blocks[node.identifier] = say[0]
    return blocks


def choice_strings(ast):
    result = defaultdict(set)
    for node in ast:
        if kind(node) == "TranslateString" and node.language == "english":
            result[node.old].add(node.new)
    return result


def interface_names(path):
    for node in statements(path, 1):
        if kind(node) != "Python":
            continue
        for statement in ast.parse(node.code.source.strip()).body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "translation_en"
                for target in statement.targets
            ):
                table = ast.literal_eval(statement.value)
                keys = {SPEAKER_KEYS.get(key, key) for key in DISPLAY_NAMES}
                return {key: table[key] for key in sorted(keys & table.keys())}
    raise ValueError("Missing official translation_en dictionary")


def match_chapter(path, ru, en, choice_catalog):
    source = read_script_source(path)
    numbers, lines = zip(*source)
    sites = list(text_sites(lines))
    original = say_blocks(ru, None)
    english = say_blocks(en, "english")
    matches = defaultdict(list)
    typographic_matches = defaultdict(list)
    original_context = []
    by_id = {}
    for order, (origin, say) in enumerate(original.items()):
        translated = english.get(origin)
        text = (original_text(translated.what)
                if translated is not None and (translated.who or "") == (say.who or "") else None)
        # These two official lines use a second opening italic tag instead of a closing tag.
        if text is not None and origin in {"day3_library_sl_4fa4d55e", "day6_sl_b37413a9"}:
            if text.count("<i>") == 2 and "</i>" not in text:
                last = text.rfind("<i>")
                text = text[:last] + "</i>" + text[last + 3:]
        russian = original_text(say.what)
        key = say.who or "", visible(russian)
        candidate = (order, origin, text)
        by_id[origin] = candidate
        matches[key].append(candidate)
        if tokens := words(russian):
            typographic_matches[key[0], tokens].append(candidate)
        original_context.append((key[0], words(russian) or (key[1],)))
    original_choices = {item[0] for node in ru if kind(node) == "Menu"
                        for item in node.items if isinstance(item[0], str)}
    candidates_by_pc = {
        pc: matches[speaker, visible(text)]
        for pc, medium, _, speaker, text in sites if medium == "dialogue"
    }
    dsl_context = defaultdict(list)
    context_index = {}
    global_context = []
    global_index = {}
    for pc, medium, label, speaker, text in sites:
        if medium == "dialogue":
            context_index[pc] = len(dsl_context[label])
            global_index[pc] = len(global_context)
            key = speaker, words(text) or (visible(text),)
            dsl_context[label].append(key)
            global_context.append(key)
    # Bound a repeated line by strictly ordered, exact neighbours in the same DSL scene.
    previous = {}
    lower, upper = {}, {}
    for pc, medium, label, _, _ in sites:
        if medium != "dialogue":
            continue
        lower[pc] = previous.get(label)
        if len(candidates_by_pc[pc]) == 1:
            previous[label] = candidates_by_pc[pc][0][0]
    previous.clear()
    for pc, medium, label, _, _ in reversed(sites):
        if medium != "dialogue":
            continue
        upper[pc] = previous.get(label)
        if len(candidates_by_pc[pc]) == 1:
            previous[label] = candidates_by_pc[pc][0][0]

    entries = {}
    unresolved = []
    for pc, medium, label, speaker, source_text in sites:
        text = None
        ids = []
        reason = "no exact Russian source"
        if medium == "choice":
            if source_text in original_choices:
                options = choice_catalog[source_text]
                if len(options) == 1:
                    text, = options
                    text = original_text(text)
                    ids = ["menu:" + source_text]
                else:
                    reason = "missing or ambiguous official menu string"
            else:
                start, end = read_block_range(lines, pc + 1)
                zones = map_choice_zones(path.name, (lines[start:end],))
                if zones:
                    text = MAP_EN.get(zones[0])
                    ids = ["images/maps/map_en.jpg:" + zones[0]]
                    reason = "map zone not labelled on the official English map"
                    if zones[0] == "me_mt_house" and source_text == "Домик Ольги Дмитриевны":
                        # Unlabelled on the map; the exact noun phrase is in this day's Say.
                        origin = "day4_fail_9fa06fb8"
                        phrase = "Olga Dmitrievna's cabin"
                        if origin in by_id and phrase in (by_id[origin][2] or ""):
                            text, ids = phrase, [origin]
        else:
            candidates = candidates_by_pc[pc]
            lo, hi = lower[pc], upper[pc]
            if not candidates and (tokens := words(source_text)):
                same_words = typographic_matches[speaker, tokens]
                if len(same_words) == 1:
                    candidates = same_words
                elif lo is not None and hi is not None and lo < hi:
                    candidates = [item for item in same_words if lo < item[0] < hi]
            if not candidates:
                fingerprint = hashlib.sha256(json.dumps(
                    [label, speaker, source_text], ensure_ascii=False,
                ).encode()).hexdigest()[:20]
                origin = REVIEWED_SAYS.get(fingerprint)
                if origin in by_id and (original[origin].who or "") == speaker:
                    index = global_index[pc]
                    order = by_id[origin][0]
                    # Recheck both surrounding pairs before reusing the reviewed match.
                    if all(
                        0 <= index + step < len(global_context) and 0 <= order + step < len(original_context)
                        and global_context[index + step] == original_context[order + step]
                        for step in (-2, -1, 1, 2)
                    ):
                        candidates = [by_id[origin]]
            if candidates:
                if len(candidates) > 1 and label:
                    local = [item for item in candidates if re.fullmatch(
                        re.escape(label) + r"_[0-9a-f]{8}(?:_[0-9]+)?", item[1]
                    )]
                    candidates = local or candidates
                if len(candidates) > 1:
                    context = dsl_context[label]
                    index = context_index[pc]
                    # Require two identical neighbouring Say keys before narrowing by context.
                    windows = []
                    for before, after in ((1, 1), (2, 0), (0, 2)):
                        if index < before or index + after >= len(context):
                            continue
                        neighbours = context[index - before:index + after + 1]
                        exact = [item for item in candidates if item[0] >= before
                                 and original_context[item[0] - before:item[0] + after + 1] == neighbours]
                        if len(exact) == 1:
                            windows.append(exact[0])
                    if windows and all(item == windows[0] for item in windows):
                        candidates = windows[:1]
                if len(candidates) > 1 and lo is not None and hi is not None and lo < hi:
                    within = [candidate for candidate in candidates if lo < candidate[0] < hi]
                    if len(within) == 1:
                        candidates = within
                variants = {candidate[2] for candidate in candidates}
                if len(variants) == 1 and None not in variants:
                    text, = variants
                    ids = [("endings.rpyc:" if candidate[1].startswith("postscriptum_") else "")
                           + candidate[1] for candidate in candidates]
                else:
                    reason = "no official Say with the same speaker" if len(variants) == 1 else "ambiguous official Say"
        if text is not None and renderable(text, choice=medium == "choice"):
            entries[str(pc)] = [text, " | ".join(ids)]
            continue
        if text is not None:
            reason = "unsupported Ren'Py text markup"
        unresolved.append({"line": numbers[pc], "label": label, "kind": medium,
                           "speaker": speaker, "source": source_text, "reason": reason})
    return {"version": 1, "content_hash": script_content_hash(lines), "lines": entries}, unresolved


def validate(text_path):
    interface = json.loads((text_path / "en" / "interface.json").read_text(encoding="utf-8"))
    if not isinstance(interface, dict) or not all(isinstance(value, str) for value in interface.values()):
        raise ValueError("Invalid English speaker catalog")
    menu = json.loads((text_path / "en" / "main-menu.json").read_text(encoding="utf-8"))
    expected = {"information", "main-start-description", "main-load-description", "main-gallery-description"}
    if not isinstance(menu, dict) or menu.keys() != expected or not all(
        isinstance(value, str) and value.strip() for value in menu.values()
    ):
        raise ValueError("Invalid English menu announcements")
    for filename in ("settings-menu.json", "endings-menu.json", "gallery-menu.json", "footer.json",
                     "save-menu.json", "runtime-ui.json"):
        content = json.loads((text_path / "en" / filename).read_text(encoding="utf-8"))
        if not isinstance(content, dict) or not content or not all(
            isinstance(value, str) and value.strip() for value in content.values()
        ):
            raise ValueError(f"Invalid English UI catalog: {filename}")
        if filename == "endings-menu.json":
            expected = {f"{field}.{ending.id}" for ending in load_endings_catalog()
                        for field in ("route", "title")}
            if expected - content.keys():
                raise ValueError("Incomplete English ending names")
    for name in RELEASE_SCRIPTS:
        path = text_path / name
        lines = tuple(line for _, line in read_script_source(path))
        catalog = read_chapter_locale(text_path / "en" / path.with_suffix(".json").name,
                                      script_content_hash(lines), len(lines))
        sites = {}
        for pc, medium, _, speaker, _ in text_sites(lines):
            sites[pc] = medium
            if medium == "dialogue" and speaker not in ("", "th") and SPEAKER_KEYS.get(speaker, speaker) not in interface:
                raise ValueError(f"{name}: missing English speaker name {speaker} at pc {pc}")
        if missing := sites.keys() - catalog.keys():
            raise ValueError(f"{name}: {len(missing)} untranslated positions; see import-report.json")
        for pc, text in catalog.items():
            if pc not in sites or not renderable(text, choice=sites[pc] == "choice"):
                raise ValueError(f"{name}: invalid English translation at pc {pc}")
    print("English catalog structure and chapter hashes verified.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steam-game", type=Path, help="Everlasting Summer install directory")
    parser.add_argument("--text-dir", type=Path, default=ROOT / "TS" / "text")
    parser.add_argument("--check", action="store_true", help="verify catalogs without changing them")
    args = parser.parse_args()
    if not args.steam_game:
        if not args.check:
            parser.error("--steam-game is required to import")
        validate(args.text_dir)
        return

    game = args.steam_game / "game"
    english = game / "tl" / "english"
    official_choices = choice_strings(statements(english / "scenario" / "menu.rpyc", 1))
    report = {}
    out = args.text_dir / "en"
    names = interface_names(english / "translation.rpyc")
    if args.check:
        if json.loads((out / "interface.json").read_text(encoding="utf-8")) != names:
            raise ValueError("interface.json: not identical to Steam speaker names")
    else:
        write_json_atomic(out / "interface.json", names)
    for name in RELEASE_SCRIPTS:
        path = args.text_dir / name
        basename = path.with_suffix(".rpyc").name
        original = statements(game / "scenario" / basename, 2)
        translation = statements(english / "scenario" / basename, 1)
        if name == "epilogue.txt":
            # Terminal Summer moved this block from Ren'Py endings into epilogue.
            for ast_nodes, root, slot in ((original, game, 2), (translation, english, 1)):
                ast_nodes.extend(
                    node for node in statements(root / "scenario" / "endings.rpyc", slot)
                    if kind(node) == "Translate" and node.identifier.startswith("postscriptum_")
                )
        catalog, remaining = match_chapter(path, original, translation, official_choices)
        target = out / path.with_suffix(".json").name
        if args.check:
            if json.loads(target.read_text(encoding="utf-8")) != catalog:
                raise ValueError(f"{target}: not identical to exact Steam import")
        else:
            write_json_atomic(target, catalog)
        report[name] = {"matched": len(catalog["lines"]), "unresolved": remaining}
        print(f"{name}: {len(catalog['lines'])} matched, {len(remaining)} unresolved")
    report_path = out / "import-report.json"
    if args.check:
        if json.loads(report_path.read_text(encoding="utf-8")) != report:
            raise ValueError(f"{report_path}: stale report")
    else:
        write_json_atomic(report_path, report)
    validate(args.text_dir)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
