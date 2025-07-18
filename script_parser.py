# script_parser.py

# from textual.widget import Widget
# from main import TextBar

import re
import time

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
            pass  # можно добавить обработку времени суток
        else:
            print(f"Необработанная строка: {line}")

    def _handle_pause(self, line):
        match = re.search(r'pause\s+(hard\s+)?(\d+)', line)
        if match:
            seconds = int(match.group(2))
            time.sleep(seconds)  # можно заменить на async версию
            print(f"[Пауза {seconds} сек]")

    def _handle_scene(self, line):
        # Игнорировать 'scene color ...'
        if "scene color" in line:
            return

        match = re.search(r'scene\s+(cg|bg)\s+([a-zA-Z0-9_]+)', line)
        if match:
            category = match.group(1)  # 'cg' или 'bg'
            scene_name = match.group(2)

            # Получение размера качества из настроек
            quality = self.app.settings.get("quality", "medium")

            # Сборка пути до ASCII файла
            scene_path = f"TS/ASCII/ASCII-{quality}/{category}/{scene_name}.txt"

            try:
                with open(scene_path, "r", encoding="utf-8") as f:
                    art_content = f.read()
            except FileNotFoundError:
                art_content = f"[Файл не найден: {scene_path}]"

            # Обновляем виджет ASCII-графики
            bg_cg = self.app.query_one("#bg-cg", expect_type=Widget)
            bg_cg.update(art_content)

            # Сохраняем текущую сцену (по имени, для отладки)
            self.app.current_scene = scene_name
            self.app.sub_title = f"Scene: {scene_name}"

    def _handle_play(self, line):
        # if "music" in line:
        #     sound = line.split()[-1]
        #     self.app.audio_player.play_sound(f"audio/music/{sound}.wav", loop=True)
        # elif "sfx" in line:
        #     sound = line.split()[-1]
        #     self.app.audio_player.play_sound(f"audio/sfx/{sound}.wav", loop=False)
        pass

    def _handle_window(self, line):
        if "show" in line:
            self.app.query_one("#text-bar", expect_type=Widget).display = True
        elif "hide" in line:
            self.app.query_one("#text-bar", expect_type=Widget).display = False

    def _handle_dialogue(self, line):
        if re.match(r'[a-zA-Z_]+\s+".+"', line):  # character "Text"
            parts = line.split('"')
            speaker = parts[0].strip()
            text = parts[1].strip()
        else:
            speaker = ""
            text = line.strip('"')

        # Обновим текстовый бар
        text_widget = self.app.query_one(TextBar)
        text_widget.border_title = speaker if speaker else "..."
        text_widget.update(text)
