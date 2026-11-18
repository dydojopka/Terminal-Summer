#!/usr/bin/env python3
"""Воспроизводимые PNG для README из ANSI-логотипа и настоящего Textual UI.

Из корня: .venv/bin/python scripts/render_readme_assets.py
Нужны игровые изображения/YAML и установленные шрифты Hack (4 начертания).
Для пробного кадра: --case 1 --output /tmp/opencode/readme-preview
Первый импорт оригиналов: --originals non-repo/Source/ES_s
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageFont
from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.text import Text


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import main as game
from script_parser import ScriptParser, get_script_state, set_script_state
from sprites_builder import parse_show_like


OUTPUT = ROOT / ".github/readme"
TERMINAL_SIZE = (192, 54)
CELL_SIZE = (10, 20)
BACKGROUND = (18, 18, 18)
STYLES = {"ansi": "ANSI", "color-ascii": "COLOR_ASCII"}


@dataclass(frozen=True)
class PreviewCase:
    number: int
    filename: str
    dialogue: str
    commands: tuple[str, ...]

    @property
    def visible_text(self) -> str:
        return self.dialogue.split('"', 1)[1].rsplit('"', 1)[0].split("<w>", 1)[0]


CASES = (
    PreviewCase(1, "prologue.txt",
                '"Я никогда не любил зиму.<w> Впрочем, и жаркое лето – тоже не моя стихия."',
                ("scene bg bus_stop with esfade",)),
    PreviewCase(2, "day7.txt",
                '"Через некоторое время все разместились в автобусе.<w> Я сел на последнее сиденье вместе с Ульянкой."',
                ("scene bg int_bus_people_day with dissolve2",)),
    PreviewCase(3, "epilogue_uv.txt",
                '"На меня смотрел облупившийся от старости потолок, большая продольная трещина разделяла его надвое, грозясь обрушить все верхние этажи."',
                ("scene bg semen_room with esfade2",)),
    PreviewCase(4, "day4.txt",
                '"У меня мурашки побежали по спине."',
                ("scene bg ext_old_building_night_moonlight with dissolve2",)),
    PreviewCase(5, "day5.txt", 'un "Но корзинки-то только две."',
                ("scene bg ext_island_day with dissolve",
                 "show un normal_pioneer size normal at cleft",
                 "show sl normal_pioneer size normal at cright",
                 "show un surprise_pioneer size normal at cleft with dspr")),
    PreviewCase(6, "day2.txt",
                '"Не удавалось вспомнить ни одного революционера с похожей фамилией."',
                ("scene cg d2_lineup with dissolve",)),
)


def validate_case(case: PreviewCase, ts_path: Path) -> int:
    """Не угадывать кадр, если сценарий или прямолинейный вход изменились."""
    parser = ScriptParser(ts_path / "text" / case.filename, None)
    matches = [pc for pc, line in enumerate(parser.lines) if line == case.dialogue]
    if len(matches) != 1:
        raise ValueError(f"Кадр {case.number}: реплика должна встречаться ровно один раз")
    pc = matches[0]
    start = next((i for i in range(pc - 1, -1, -1)
                  if parser.lines[i].startswith("scene ")), None)
    if start is None:
        raise ValueError(f"Кадр {case.number}: не найдена начальная сцена")
    block = parser.lines[start:pc]
    for line in block:
        if (line in ("{", "}", "else", "menu", "menu:")
                or line.startswith(("if ", "if(", "else if", "goto ", "load ", "label ", "mode "))):
            raise ValueError(f"Кадр {case.number}: неоднозначный вход: {line}")
    commands = tuple(line for line in block if line.startswith(("scene ", "show ", "hide ")))
    if commands != case.commands:
        raise ValueError(f"Кадр {case.number}: изменились визуальные команды: {commands!r}")
    return parser.source_line_numbers[pc]


class CellRasterizer:
    """Растеризация готовых терминальных ячеек, без повторной вёрстки UI.

    Блочные глифы, как в терминале, заполняют ячейку без шрифтовых зазоров.
    Остальные символы берутся из фиксированных начертаний Hack 16 px.
    """

    def __init__(self):
        self.fonts = {
            (False, False): ImageFont.truetype("Hack-Regular.ttf", 16),
            (True, False): ImageFont.truetype("Hack-Bold.ttf", 16),
            (False, True): ImageFont.truetype("Hack-Italic.ttf", 16),
            (True, True): ImageFont.truetype("Hack-BoldItalic.ttf", 16),
        }

    @staticmethod
    def draw_block(draw, char, left, top, color) -> bool:
        cw, ch = CELL_SIZE
        if char in "▀▄█▁▏▔":
            x1, y0, y1 = cw, 0, ch
            if char == "▀":
                y1 = ch // 2
            elif char == "▄":
                y0 = ch // 2
            elif char == "▁":
                y0 = ch - max(1, ch // 8)
            elif char == "▔":
                y1 = max(1, ch // 8)
            elif char == "▏":
                x1 = max(1, cw // 8)
            draw.rectangle((left, top + y0, left + x1 - 1, top + y1 - 1), fill=color)
            return True
        # Соединённые рамки терминала не должны зависеть от метрик шрифта.
        if char == "─":
            draw.line((left, top + 9, left + cw - 1, top + 9), fill=color)
        elif char == "│":
            draw.line((left + 4, top, left + 4, top + ch - 1), fill=color)
        elif char in "╭╮╰╯":
            upper, opening_right = char in "╭╮", char in "╭╰"
            x0 = 4 if opening_right else -6
            y0 = 9 if upper else -1
            angles = {"╭": (180, 270), "╮": (270, 360), "╰": (90, 180), "╯": (0, 90)}
            # Рисуем в ячейке: дуга не задевает соседний фон.
            tile = Image.new("L", CELL_SIZE)
            pen = ImageDraw.Draw(tile)
            pen.arc((x0, y0, x0 + 10, y0 + 10), *angles[char], fill=255)
            pen.line((4, 14 if upper else 0, 4, 19 if upper else 4), fill=255)
            draw.bitmap((left, top), tile, fill=color)
        else:
            return False
        return True

    def render(self, rows, size: tuple[int, int]) -> Image.Image:
        cw, ch = CELL_SIZE
        image = Image.new("RGB", (size[0] * cw, size[1] * ch), BACKGROUND)
        draw = ImageDraw.Draw(image)
        for y, row in enumerate(rows):
            if y >= size[1]:
                raise ValueError("Лишние строки при растеризации")
            x = 0
            for segment in row:
                if segment.control:
                    raise ValueError("Неожиданная управляющая последовательность")
                style = segment.style or Style()
                fg = tuple(style.color.get_truecolor()) if style.color and not style.color.is_default else (224, 224, 224)
                bg = tuple(style.bgcolor.get_truecolor()) if style.bgcolor and not style.bgcolor.is_default else BACKGROUND
                if style.reverse:
                    fg, bg = bg, fg
                if style.dim:
                    fg = tuple(round(b + (f - b) * 0.4) for f, b in zip(fg, bg))
                for char in segment.text:
                    width = cell_len(char)
                    if width != 1 or x >= size[0]:
                        raise ValueError(f"Неожиданная ячейка {char!r} в ({x}, {y})")
                    left, top = x * cw, y * ch
                    box = (left, top, left + cw - 1, top + ch - 1)
                    draw.rectangle(box, fill=bg)
                    if not style.conceal and char != " ":
                        if not self.draw_block(draw, char, left, top, fg):
                            # Отдельная ячейка обрезает выносы, как терминал.
                            tile = Image.new("RGB", CELL_SIZE, bg)
                            pen = ImageDraw.Draw(tile)
                            font = self.fonts[bool(style.bold), bool(style.italic)]
                            pen.text((0, 15), char, font=font, fill=fg, anchor="ls")
                            image.paste(tile, (left, top))
                        if style.underline:
                            draw.line((left, top + 18, left + cw - 1, top + 18), fill=fg)
                        if style.strike:
                            draw.line((left, top + 10, left + cw - 1, top + 10), fill=fg)
                    x += 1
        return image


def render_logo(rasterizer: CellRasterizer) -> Image.Image:
    text = Text.from_ansi((ROOT / "src/menu_logo.ansi").read_text(encoding="utf-8"))
    lines = text.split("\n")
    width = max(line.cell_len for line in lines)
    console = Console(width=width, file=io.StringIO(), color_system="truecolor")
    rows = console.render_lines(text, console.options.update(width=width), pad=True)
    image = rasterizer.render(rows, (width, len(lines)))
    bounds = ImageChops.difference(image, Image.new("RGB", image.size, BACKGROUND)).getbbox()
    if bounds is None:
        raise ValueError("ANSI-логотип пуст")
    cropped = image.crop(bounds)
    # Клетка 10×20 → 14×28: чёткие блоки внутри безопасных полей Open Graph.
    cropped = cropped.resize((cropped.width * 7 // 5, cropped.height * 7 // 5),
                             resample=Image.Resampling.NEAREST)
    result = Image.new("RGB", (1280, 640), BACKGROUND)
    if cropped.width > result.width - 160 or cropped.height > result.height - 160:
        raise ValueError("ANSI-логотип не помещается на холсте 1280×640 с полями 80 px")
    result.paste(cropped, ((result.width - cropped.width) // 2,
                          (result.height - cropped.height) // 2))
    return result


def assert_frame(app: game.TerminalSummer, case: PreviewCase) -> None:
    snapshot = app._capture_scene_snapshot()
    category, name = case.commands[0].split()[1:3]
    if (snapshot.category, snapshot.name) != (category, name):
        raise ValueError(f"Кадр {case.number}: неверная сцена")
    expected = {}
    for line in case.commands[1:]:
        request = parse_show_like(line)
        expected[request.character] = line
    actual = {sprite.character: sprite.show_line for sprite in snapshot.sprites}
    if actual != expected or any(not Path(s.image_path).is_file() for s in snapshot.sprites):
        raise ValueError(f"Кадр {case.number}: не собраны нужные спрайты: {app.sub_title}")
    art = app._render_scene_snapshot(snapshot)
    if art.plain.startswith("["):
        raise ValueError(art.plain)
    if max(map(len, art.plain.splitlines())) != 150:
        raise ValueError("Неверная ширина арта")
    widget = app.query_one("#bg-cg")
    if widget.size.width < 150 or widget.size.height < len(art.plain.splitlines()):
        raise ValueError("Арт не помещается в окно")
    bar = app.query_one("#text-bar")
    if bar.text != case.visible_text or bar.border_title != ("Лена" if case.number == 5 else ""):
        raise ValueError(f"Кадр {case.number}: неверная реплика или говорящий: {bar.text!r}")
    if bar.max_scroll_y:
        raise ValueError("Реплика не помещается в текстовую панель")
    if app.script.failed or app.script.has_diagnostic:
        raise ValueError(f"Ошибка сценария: {app.sub_title}")


async def capture_case(case: PreviewCase, style: str, rasterizer: CellRasterizer) -> Image.Image:
    with tempfile.TemporaryDirectory(prefix="ts-readme-", dir="/tmp/opencode") as temporary:
        folder = Path(temporary)
        # Только визуальные команды и точная реплика из текущего сценария.
        # Маршрут, аудио, достижения и сохранения здесь не исполняются.
        source = folder / "preview.txt"
        source.write_text("\n".join((*case.commands, case.dialogue)) + "\n", encoding="utf-8")
        config = folder / "settings.json"
        config.write_text(json.dumps({"quality": "150", "style": style, "text_speed": "0"}))
        at_wait = asyncio.Event()

        async def hold_wait(seconds, kind, **kwargs):
            if kind != "w":
                raise ValueError(f"Неожиданная пауза: {kind}")
            at_wait.set()
            await asyncio.Future()

        app = game.TerminalSummer()
        app.CONFIG_FILE = config
        app.PERSISTENT_FILE = folder / "persistent.json"
        app._sprite_runtime_dir = folder / "generated_runtime"
        try:
            with patch.object(game, "SAVES_PATH", folder / "saves"), \
                    patch.object(app, "start_menu_music"), \
                    patch.object(app, "wait_script_delay", side_effect=hold_wait):
                async with app.run_test(size=TERMINAL_SIZE) as pilot:
                    app.query_one("#main-menu").add_class("hidden")
                    for selector in ("#novel-menu", "#novel-window", "Footer"):
                        app.query_one(selector).remove_class("hidden")
                    app.script = ScriptParser(source, app)
                    task = asyncio.create_task(app.script.next_line())
                    try:
                        if "<w>" in case.dialogue:
                            waiter = asyncio.create_task(at_wait.wait())
                            try:
                                done, _ = await asyncio.wait(
                                    (task, waiter), timeout=30, return_when=asyncio.FIRST_COMPLETED)
                                if task in done:
                                    task.result()
                                    raise ValueError("Не достигнута пауза <w>")
                                if waiter not in done:
                                    raise TimeoutError("Не достигнута пауза <w> за 30 секунд")
                            finally:
                                waiter.cancel()
                                with suppress(asyncio.CancelledError):
                                    await waiter
                        else:
                            await asyncio.wait_for(asyncio.shield(task), timeout=30)
                        app.query_one("#btn-next").focus()
                        await pilot.pause()
                        assert_frame(app, case)
                        # Уже скомпонованные Textual ячейки, не макет похожего UI.
                        rows = app.screen._compositor.render_strips()
                        return rasterizer.render(rows, TERMINAL_SIZE)
                    finally:
                        task.cancel()
                        with suppress(asyncio.CancelledError):
                            await task
        finally:
            app._clear_render_caches()
            app.audio.close()


async def generate(output: Path, originals: Path, cases: tuple[PreviewCase, ...]) -> None:
    rasterizer = CellRasterizer()
    locations = {case.number: validate_case(case, ROOT / "TS") for case in cases}
    for case in cases:
        path = originals / f"ES_s{case.number}.jpg"
        with Image.open(path) as image:
            image.verify()
        if image.size != (1920, 1080):
            raise ValueError(f"Неожиданный размер оригинала: {path}")
    output.mkdir(parents=True, exist_ok=True)
    render_logo(rasterizer).save(output / "logo.png", optimize=True)
    previous_state = get_script_state()
    try:
        for case in cases:
            for directory, style in STYLES.items():
                target = output / "screenshots" / directory
                target.mkdir(parents=True, exist_ok=True)
                image = await capture_case(case, style, rasterizer)
                image.save(target / f"scene-{case.number:02}.png", optimize=True)
            target = output / "screenshots/original"
            target.mkdir(parents=True, exist_ok=True)
            src = originals / f"ES_s{case.number}.jpg"
            dst = target / src.name
            if src.resolve() != dst.resolve():
                shutil.copyfile(src, dst)
            print(f"OK {case.number}: {case.filename}:{locations[case.number]} — {case.visible_text}")
    finally:
        set_script_state(previous_state)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--originals", type=Path, default=OUTPUT / "screenshots/original")
    parser.add_argument("--case", type=int, choices=range(1, 7), help="Подготовить одну строку таблицы")
    args = parser.parse_args()
    cases = tuple(case for case in CASES if args.case is None or case.number == args.case)
    try:
        asyncio.run(generate(args.output.resolve(), args.originals.resolve(), cases))
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        parser.exit(1, f"Не удалось подготовить README: {exc}\n")


if __name__ == "__main__":
    main()
