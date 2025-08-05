import asyncio
import re

from textual.widget import Widget

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
            await self.next_line()
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
        """Обработка строки диалога с анимацией текста"""
        widget = self.app.query_one("#text-bar", expect_type=Widget)
        
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
        
        # Очистка старых ID, кроме 'text-bar'
        widget.remove_class(*[cls for cls in widget.classes if cls != "text-bar"])
        
        # Установка нового ID как класс (для CSS)
        if id_to_set:
            widget.add_class(id_to_set)
        
        # Установка имени и анимация текста
        widget.border_title = speaker if speaker else ""
        await widget.animate_text(text)

