import asyncio
import re

from textual.widget import Widget
from textual.widgets import ListView, ListItem, Label

# Словарь имён
DISPLAY_NAMES = {
    "dreamgirl": "...",
    "sl": "Славя",
    "slp": "Пионерка",
    "slg": "Девушка",
    "sa": "Саша",
    "un": "Лена",
    "unp": "Пионерка",
    "dv": "Алиса",
    "dvp": "Пионерка",
    "dvg": "Девушка",
    "el": "Электроник",
    "elp": "Пионер",
    "ro": "Роутер",
    "us": "Ульяна",
    "usp": "Пионерка",
    "usg": "Девушка",
    "mt": "Ольга Дмитриевна",
    "mtp": "Вожатая",
    "mt_voice": "Голос",
    "cs": "Виола",
    "mz": "Женя",
    "mi": "Мику",
    "ma": "Маша",
    "uv": "Юля",
    "uvp": "Странная девочка",
    "sh": "Шурик",
    "pi": "Пионер",
    "me": "Семён",
    "FIXME_voice": "Голос",
    "bush": "Голос", 
    "message": "Сообщение", 
    "odn": "Одногруппник", 
    "all": "Пионеры"
}

class ScriptParser:
    def __init__(self, filename, app):
        self.filename = filename
        self.app = app
        self.lines = []
        self.index = 0
        self.load_script()


    def load_script(self):
        """Загрузка файла сценария"""
        with open(self.filename, 'r', encoding='utf-8') as f:
            self.lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    async def next_line(self):
        """Шаг вперёд"""
        if self.index >= len(self.lines):
            return None
        self.backward = False
        line = self.lines[self.index]
        self.index += 1
        await self.parse_line(line)

    async def parse_line(self, line):
        """Считывание строки сценария (асинхронно)"""
        self.app.sub_title = f"Content: {line}"
        
        if line.startswith("pause"):
            await self._handle_pause(line)
        elif line.startswith("scene"):
            await self._handle_scene(line)
        elif line.startswith("play"):
            await self._handle_play(line)
        elif line.startswith("window"):
            await self._handle_window(line)
        elif '"' in line:
            await self._handle_dialogue(line)
        elif line.startswith("time"):
            await self.next_line()
        elif line.startswith("menu"):
            await self._handle_choice(line)

        else:
            await self.next_line()             


    async def _handle_pause(self, line):
        """Обработка строки pause"""
        match = re.search(r'pause\s+(hard\s+)?(\d+)', line)
        if match:
            seconds = int(match.group(2))
            if not self.backward:
                await asyncio.sleep(seconds)
                await self.next_line()
            # else: ничего не делаем — просто пропускаем паузу


    async def _handle_scene(self, line):
        """Обработка строки scene cg/bg/color"""
        if "scene color" in line:
            if not self.backward:
                await self.next_line()
            return

        match = re.search(r'scene\s+(cg|bg)\s+([a-zA-Z0-9_]+)', line)
        if match:
            category = match.group(1)
            scene_name = match.group(2)
            quality = self.app.settings.get("quality", "medium")

            scene_path = f"TS/ASCII/ASCII-{quality}/{category}/{scene_name}.txt"
            try:
                with open(scene_path, "r", encoding="utf-8") as f:
                    art_content = f.read()
            except FileNotFoundError:
                art_content = f"[Файл не найден: {scene_path}]"

            bg_cg = self.app.query_one("#bg-cg", expect_type=Widget)
            bg_cg.update(art_content)
            self.app.current_scene = scene_name

            if not self.backward:
                await self.next_line()


    async def _handle_play(self, line):
        """Обработка строки play"""
        if not self.backward:
            await self.next_line()


    async def _handle_window(self, line):
        """Обработка строки window"""
        widget = self.app.query_one("#text-bar", expect_type=Widget)
        widget.display = "show" in line
        if not self.backward:
            await self.next_line()


    async def _handle_choice(self, line):
        """Обработка строки menu и логика выбора"""

        options = {}
        self.index += 1  # пропускаем "menu"

        while self.index < len(self.lines):
            line = self.lines[self.index].strip()

            # конец всего блока меню
            if line == "}":
                self.index += 1
                break

            # начало варианта
            if line.startswith('"'):
                choice_text = re.match(r'"(.+)"', line).group(1)
                self.index += 1
                block_lines = []

                # собираем строки внутри { ... }
                if self.lines[self.index] == "{":
                    self.index += 1
                    depth = 1
                    while self.index < len(self.lines) and depth > 0:
                        l = self.lines[self.index]
                        if l == "{":
                            depth += 1
                        elif l == "}":
                            depth -= 1
                            if depth == 0:
                                self.index += 1
                                break
                        if depth > 0:
                            block_lines.append(l)
                        self.index += 1

                options[choice_text] = block_lines
            else:
                self.index += 1

        # показать ChoiceBar
        choice_bar = self.app.query_one("#choice-bar")
        list_view = choice_bar.query_one(ListView)

        list_view.clear()
        for opt in options:
            list_view.append(ListItem(Label(opt)))

        # сохранить варианты в app
        self.app.pending_choices = options

        # отобразить ChoiceBar и скрыть фон
        choice_bar.remove_class("hidden")
        self.app.query_one("#bg-cg").add_class("hidden")

        # дождаться одного кадра, чтобы Textual успел пересчитать фокус
        await asyncio.sleep(0)

        # найти ListView и перевести на него фокус 
        if list_view.children:
            list_view.index = 0
            list_view.focus() 
            # (есть визуальный баг при последующих появлениях окна, но бля, как же мне похуй)


    async def _handle_dialogue(self, line):
        """Обработка строки диалога с анимацией текста"""
        widget = self.app.query_one("#text-bar", expect_type=Widget)
        btn = self.app.query_one("#btn-next")

        # Скрываем кнопку на время показа текста
        btn.add_class("invisible")

        match = re.match(r'([a-zA-Z0-9_-]+)\s+"(.+)"', line)
        if match:
            raw_speaker, text = match.groups()
            raw_speaker = raw_speaker.strip()
            text = text.strip()

            if raw_speaker == "th":
                speaker = ""
                text = f"~ {text} ~"
                id_to_set = None
            else:
                speaker = DISPLAY_NAMES.get(raw_speaker, raw_speaker)
                id_to_set = raw_speaker
        else:
            speaker = ""
            text = line.strip().strip('"')
            id_to_set = None

        widget.remove_class(*[cls for cls in widget.classes if cls != "text-bar"])
        if id_to_set:
            widget.add_class(id_to_set)

        widget.border_title = speaker if speaker else ""

        # Конвертируем <i>, <b> в rich-разметку
        text = re.sub(r'<i>(.*?)</i>', r'[italic]\1[/italic]', text)
        text = re.sub(r'<b>(.*?)</b>', r'[bold]\1[/bold]', text)

        # Разбиваем текст на части по <w> с паузами
        parts = text.split("<w>")
        for i, part in enumerate(parts):
            part = part.strip()
            if part:
                prefix = "" if i == 0 else " "
                await widget.animate_text(prefix + part, append=(i > 0))

            if i < len(parts) - 1:
                await asyncio.sleep(1)

       # Показать кнопку обратно
        btn.remove_class("invisible")

        # Фокусируем кнопку только если меню выбора НЕ открыто
        choice_bar = self.app.query_one("#choice-bar")
        if choice_bar.has_class("hidden"):
           btn.focus()
