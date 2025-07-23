# script_parser.py

import re
import time
from textual.widget import Widget

class ScriptParser:
    def __init__(self, filename, app):
        self.filename = filename
        self.app = app
        self.lines = []
        self.index = 0
        self.load_script()

    def load_script(self):
        with open(self.filename, 'r', encoding='utf-8') as f:
            self.lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    def next_line(self):
        if self.index >= len(self.lines):
            return None  # конец
        line = self.lines[self.index]
        self.index += 1
        self.parse_line(line)
        return line

    def parse_line(self, line):
        self.app.sub_title = f"Line: {self.index} | Content: {self.lines[self.index - 1]}"
        if line.startswith("pause"):
            self._handle_pause(line)
        elif line.startswith("scene"):
            self._handle_scene(line)
        elif line.startswith("play"):
            self._handle_play(line)
        elif line.startswith("window"):
            self._handle_window(line)
        elif '"' in line:
            self._handle_dialogue(line)
        elif line.startswith("time"):
            self.next_line() # Следующая строка
        else:
            self.next_line() # Следующая строка
            print(f"Необработанная строка: {line}")

        # self.next_line()

    def _handle_pause(self, line):
        match = re.search(r'pause\s+(hard\s+)?(\d+)', line)
        if match:
            seconds = int(match.group(2))
            time.sleep(seconds)
            # print(f"[Пауза {seconds} сек]")
        
        self.next_line()

    def _handle_scene(self, line):
        if "scene color" in line:
            self.next_line() # Следующая строка
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

        # self.next_line()

    def _handle_play(self, line):
        self.next_line()
        pass  # позже

    def _handle_window(self, line):
        widget = self.app.query_one("#text-bar", expect_type=Widget)
        widget.display = "show" in line

        self.next_line()

    def _handle_dialogue(self, line):
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

