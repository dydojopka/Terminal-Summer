"""Детерминированные свидетели концовок на настоящем runtime, без UI/диска/SDL.

Это проверка выбранных полных прохождений, не полный перебор всех веток.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import script_parser as sp
from audio_catalog import load_audio_catalog
from endings_catalog import current_ending, load_endings_catalog
from script_audio import parse_audio_command


class RouteApp:
    def __init__(self):
        self.sub_title = ""
        self.current_text_mode = "adv"
        self.window_visible = True
        self.ending = None
        self.new_unlocks = set()
        self.audio = SimpleNamespace(execute=lambda line: parse_audio_command(line, self.audio.catalog),
                                     catalog=load_audio_catalog())
        self.text_bar = SimpleNamespace(text="", refresh=lambda: None)

    def query_one(self, *args, **kwargs):
        return self.text_bar

    def update_script_header(self):
        pass

    def stop_skipping(self):
        pass

    def save_persistent_state(self):
        pass

    def record_ending_unlock(self, flag):
        self.new_unlocks.add(flag)

    def start_script_preload(self, parser):
        return None

    def set_text_mode(self, mode):
        self.current_text_mode = mode

    def clear_active_sprites(self):
        pass

    def mark_scene_dirty(self):
        pass

    def show_sprite_from_script_line(self, line):
        pass

    def hide_sprite_by_id(self, identity):
        pass

    def start_credits(self, parser, duration):
        if duration <= 0:
            raise ValueError("Титры без длительности")
        self.ending = current_ending(sp.get_script_state())

    def finish_game(self, parser):
        if self.ending is None or not sp.SCRIPT_STATE[self.ending.flag]:
            raise ValueError("Финал не открыл свою концовку")


class RouteParser(sp.ScriptParser):
    def __init__(self, filename, app, choose):
        super().__init__(filename, app)
        self.choose = choose
        self.steps = 0
        self.choice_indices = []
        self.menu_digest = hashlib.sha256()
        self.visited = set()
        self.dialogues = 0

    async def parse_line(self, line):
        self.steps += 1
        if self.steps > 100000:
            raise ValueError("Превышен лимит шагов свидетеля прохождения")
        if line.startswith("label "):
            self.visited.add((Path(self.filename).name, line.split()[1].rstrip(":")))
        await super().parse_line(line)

    async def _handle_window(self, line):
        self.app.window_visible = line == "window show"
        await self.next_line()

    async def _handle_dialogue(self, line):
        if not self.app.window_visible:
            number = self.source_line_numbers[self.index - 1]
            raise ValueError(f"Невидимая реплика: {Path(self.filename).name}:{number}: {line}")
        self.dialogues += 1
        await self.next_line()

    async def _handle_pause(self, line):
        await self.next_line()

    async def _handle_choice(self, line):
        options, _ = self.choice_targets()
        self.menu_digest.update(json.dumps(list(options), ensure_ascii=False).encode("utf-8") + b"\n")
        index = self.choose(self, options)
        if type(index) is not int or not 0 <= index < len(options):
            raise ValueError(f"Нет варианта выбора {index}")
        self.choice_indices.append(index)
        self.select_choice(list(options.values())[index])
        await self.next_line()


async def validate_release_routes(ts_dir: Path) -> list[str]:
    """Выполняет фикстуры последовательно, перенося только реально открытый прогресс."""
    saved_state = sp.get_script_state()
    errors = []
    try:
        data = json.loads(Path(__file__).with_name("release_routes.json").read_text(encoding="utf-8"))
        expected = {ending.id for ending in load_endings_catalog()}
        if (type(data.get("version")) is not int or data["version"] != 1
                or len(data["routes"]) != len(expected)
                or {route["ending"] for route in data["routes"]} != expected):
            raise ValueError("Свидетели должны покрывать все 13 концовок")
        progress = {}
        for route in data["routes"]:
            sp.set_script_state(progress)
            choices = iter(route["choices"])
            app = RouteApp()
            parser = RouteParser(ts_dir / "text/prologue.txt", app, lambda *_: next(choices))
            try:
                await parser.next_line()
                if parser.failed or parser.has_diagnostic or not parser.finished or app.ending is None:
                    raise ValueError(app.sub_title or "Не достигнут конец титров")
                if app.ending.id != route["ending"]:
                    raise ValueError(f"Получена {app.ending.id} вместо {route['ending']}")
                if next(choices, None) is not None or parser.menu_digest.hexdigest() != route["menu_hash"]:
                    raise ValueError("Изменились меню или последовательность выборов свидетеля")
                progress = sp.get_persistent_state()
                print(f"Маршрут {app.ending.id}: выборов — {len(parser.choice_indices)}, реплик — {parser.dialogues}, титры завершены.")
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append(f"Маршрут {route['ending']}: {exc}")
                break
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"Свидетели концовок: {exc}")
    finally:
        sp.set_script_state(saved_state)
    return errors
