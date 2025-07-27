import asyncio
import re

from textual.widget import Widget

class ScriptParser:
    def __init__(self, filename, app):
        self.filename = filename
        self.app = app
        self.lines = []
        self.index = 0
        self.backward = False  # Флаг перемотки назад
        self.last_backward = False  # Запоминаем предыдущее направление
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

    async def prev_line(self):
        """Шаг назад"""
        if self.index <= 0:
            return None
        self.backward = True
        self.index -= 1
        line = self.lines[self.index]
        await self.parse_line(line)


    async def parse_line(self, line):
        """Считывание строки сценария (асинхронно)"""
        self.app.sub_title = f"Line: {self.index} | Content: {line}"
        
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
            if self.backward:
                await self.prev_line()
            else:
                await self.next_line()
        else:
            if self.backward:
                await self.prev_line()
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

    async def _handle_dialogue(self, line):
        """Обработка строки диалога"""
        widget = self.app.query_one("#text-bar", expect_type=Widget)

        if re.match(r'[a-zA-Z_]+\s+".+"', line):  # character "Text"
            parts = line.split('"')
            speaker = parts[0].strip()
            text = parts[1].strip()
        else:
            speaker = ""
            text = line.strip('"')

        if text:  # Проверяем, что текст не пустой
            widget.border_title = speaker if speaker else ""
            widget.update_text(text)  # Обновляем текст только если он есть
        else:
            widget.update_text("")  # Убираем текст
