import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from textual.widget import Widget
from textual.widgets import ListView, ListItem, Label
from textual import _time

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
    "csp": "Медсестра",
    "mz": "Женя",
    "mi": "Мику",
    "mip": "Пионерка",
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

# Состояние прохождения. Ключи совпадают с именами DSL без `$`.
DEFAULT_SCRIPT_STATE = {
    "lp_sl": 0, "lp_un": 0, "lp_dv": 0, "lp_us": 0,
    "prologue": 0, "d1_keys": False,
    "day2_map_necessary_done": 0,
    "day2_map_clubs": False, "day2_map_musclub": False,
    "day2_map_dinning_hall": False, "day2_map_aidpost": False,
    "day2_map_library": False, "day2_cards_with_sl": 0,
    "day2_dv_bet": 0, "day2_un": 0, "day2_card_result": None,
    "d2_gave_keys": False, "d2_cardgame_block_rollback": False,
    "persistent.CardsDemo": False, "persistent.CardsWon1": False,
    "persistent.CardsWon2": False, "persistent.CardsWon3": False,
    "persistent.CardsFail": False,
}
SCRIPT_STATE = DEFAULT_SCRIPT_STATE.copy()

# Совместимые поля для текущего UI и старых сохранений.
SL = UN = DV = US = PROLOGUE = 0
D1_KEYS = False


def _sync_legacy_globals() -> None:
    global SL, UN, DV, US, PROLOGUE, D1_KEYS
    SL = SCRIPT_STATE["lp_sl"]
    UN = SCRIPT_STATE["lp_un"]
    DV = SCRIPT_STATE["lp_dv"]
    US = SCRIPT_STATE["lp_us"]
    PROLOGUE = SCRIPT_STATE["prologue"]
    D1_KEYS = SCRIPT_STATE["d1_keys"]


def get_script_state() -> dict:
    """Возвращает копию сериализуемого состояния прохождения."""
    return SCRIPT_STATE.copy()


def set_script_state(state: dict) -> None:
    """Восстанавливает состояние, дополняя его новыми значениями по умолчанию."""
    SCRIPT_STATE.clear()
    SCRIPT_STATE.update(DEFAULT_SCRIPT_STATE)
    SCRIPT_STATE.update(state)
    _sync_legacy_globals()


def ensure_day2_state() -> None:
    """Добавляет флаги второго дня при входе в его первую метку."""
    for key in DEFAULT_SCRIPT_STATE:
        if key.startswith("day2_") or key.startswith("d2_"):
            SCRIPT_STATE.setdefault(key, DEFAULT_SCRIPT_STATE[key])


def reset_globals():
    """Сброс всех очков и флагов"""
    set_script_state({})


@dataclass(frozen=True)
class ExecutionFrame:
    """Диапазон исходного сценария, выполняемый вместо вставки строк."""

    end: int
    return_pc: int

    def to_save_data(self) -> dict:
        return {"end": self.end, "return_pc": self.return_pc}


@dataclass(frozen=True)
class ChoiceTarget:
    """Неизменяемая ссылка на тело пункта меню в исходном сценарии."""

    start: int
    end: int
    return_pc: int


class ScriptParser:
    def __init__(self, filename, app):
        self.filename = filename
        self.app = app
        self.lines: tuple[str, ...] = ()
        self.labels = {}
        self.index = 0
        self.frames: list[ExecutionFrame] = []
        self.content_hash = ""
        self.resource_manifest = {"scenes": (), "show_lines": ()}
        self.backward = False
        self.load_script()


    def load_script(self, filename=None):
        """Загрузка файла сценария"""
        if filename:
            self.filename = str(filename)
        with open(self.filename, 'r', encoding='utf-8') as f:
            self.lines = tuple(
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            )
        self.content_hash = hashlib.sha256("\n".join(self.lines).encode("utf-8")).hexdigest()
        self._index_labels()
        self.index = 0
        self.frames.clear()
        self._build_resource_manifest()

    def restore_runtime_lines(self, lines: list[str]) -> None:
        """Поддержка save format 2 с ранее вставленными строками.

        Новые сохранения этот метод не используют: их сценарий всегда неизменяем.
        """
        self.lines = tuple(lines)
        self.content_hash = hashlib.sha256("\n".join(self.lines).encode("utf-8")).hexdigest()
        self._index_labels()
        self.frames.clear()
        self._build_resource_manifest()

    def _build_resource_manifest(self) -> None:
        """Лёгкий индекс ресурсов текущего файла, без открытия изображений."""
        scenes = set()
        shows = set()
        for line in self.lines:
            match = re.match(r"scene\s+(bg|cg)\s+([a-zA-Z0-9_]+)", line)
            if match:
                scenes.add(match.groups())
            elif line.startswith("show "):
                shows.add(line)
        self.resource_manifest = {
            "scenes": tuple(sorted(scenes)),
            "show_lines": tuple(sorted(shows)),
        }

    def get_runtime_state(self) -> dict:
        """Компактное, не зависящее от копии сценария состояние выполнения."""
        return {
            "filename": str(Path(self.filename).resolve()),
            "content_hash": self.content_hash,
            "pc": self.index,
            "frames": [frame.to_save_data() for frame in self.frames],
        }

    def restore_runtime_state(self, state: dict) -> bool:
        """Восстанавливает позицию и вложенные выбранные блоки save format 3."""
        if not isinstance(state, dict):
            return False
        saved_hash = state.get("content_hash")
        if saved_hash and saved_hash != self.content_hash:
            self.app.sub_title = "[Load error] Script was changed since this save was created"
            return False
        pc = state.get("pc", 0)
        frames_data = state.get("frames", [])
        if not isinstance(pc, int) or not 0 <= pc <= len(self.lines):
            return False
        frames = []
        if not isinstance(frames_data, list):
            return False
        for frame in frames_data:
            if not isinstance(frame, dict):
                return False
            end = frame.get("end")
            return_pc = frame.get("return_pc")
            if not all(isinstance(value, int) and 0 <= value <= len(self.lines)
                       for value in (end, return_pc)):
                return False
            frames.append(ExecutionFrame(end=end, return_pc=return_pc))
        self.index = pc
        self.frames = frames
        return True

    def _index_labels(self) -> None:
        """Строит индекс меток для текущего набора строк."""
        self.labels = {}
        for index, line in enumerate(self.lines):
            match = re.fullmatch(r"label\s+([a-zA-Z0-9_]+):?", line)
            if match:
                self.labels[match.group(1)] = index

    async def next_line(self):
        """Шаг вперёд"""
        while self.frames and self.index >= self.frames[-1].end:
            self.index = self.frames.pop().return_pc
        if self.index >= len(self.lines):
            return None
        self.backward = False
        line = self.lines[self.index]
        self.index += 1
        await self.parse_line(line)

    async def parse_line(self, line):
        """Считывание строки сценария (асинхронно)"""

        # Формируем строку статуса поинтов
        lp_status = f"[SL:{SL}] [UN:{UN}] [DV:{DV}] [US:{US}] [PROLOGUE:{PROLOGUE}] [D1_KEYS:{D1_KEYS}]"

        self.app.sub_title = lp_status

        # ---- Логика обработки строк ----
        if line.startswith("label"):
            await self._handle_label(line)
        elif line.startswith("goto"):
            await self._handle_goto(line)
        elif line.startswith("if ") or line.startswith("if("):
            await self._handle_if(line)
        elif line.startswith("pause"):
            await self._handle_pause(line)
        elif line.startswith("scene"):
            await self._handle_scene(line)
        elif line.startswith("show"):
            await self._handle_show(line)
        elif line.startswith("hide"):
            await self._handle_hide(line)
        elif line.startswith("play"):
            await self._handle_play(line)
        elif line.startswith("window"):
            await self._handle_window(line)
        elif line.startswith("time"):
            self.app.current_time = line.split(maxsplit=1)[1].strip() if " " in line else "day"
            await self.next_line()
        elif line.startswith("mode"):
            mode = line.split(maxsplit=1)[1].strip() if " " in line else "adv"
            self.app.set_text_mode(mode)
            await self.next_line()
        elif line == "clear":
            widget = self.app.query_one("#text-bar", expect_type=Widget)
            widget.text = ""
            widget.refresh()
            await self.next_line()
        elif line.startswith("menu"):
            await self._handle_choice(line)
        elif line.startswith("$"):
            await self._handle_changeLP(line)
        elif line.startswith("load"):
            await self._handle_load(line)
        elif '"' in line:
            await self._handle_dialogue(line)
        else:
            await self.next_line()

    async def _handle_label(self, line):
        """Пропускает метку: она нужна только для переходов."""
        match = re.fullmatch(r"label\s+([a-zA-Z0-9_]+):?", line)
        if match and match.group(1) == "day2_main1":
            ensure_day2_state()
        if not self.backward:
            await self.next_line()

    async def _handle_goto(self, line):
        """Переходит на строку с именованной меткой."""
        match = re.fullmatch(r"goto\s+([a-zA-Z0-9_]+)", line)
        if not match:
            self.app.sub_title = f"[Script error] Invalid goto: {line}"
            return

        label = match.group(1)
        target_index = self.labels.get(label)
        if target_index is None:
            self.app.sub_title = f"[Script error] Label not found: {label}"
            return

        self.index = target_index
        # Переход по метке выходит из текущих структурных блоков так же,
        # как это происходило при старой подмене общего массива строк.
        self.frames.clear()
        if not self.backward:
            await self.next_line()

    def _read_block_range(self, start: int) -> tuple[int, int]:
        """Возвращает полуоткрытый диапазон тела `{ ... }` в исходном сценарии."""
        if start >= len(self.lines) or self.lines[start] != "{":
            raise ValueError("Expected `{` after conditional")

        depth = 1
        index = start + 1
        while index < len(self.lines) and depth:
            line = self.lines[index]
            if line == "{":
                depth += 1
            elif line == "}":
                depth -= 1
                if depth == 0:
                    return start + 1, index
            index += 1

        raise ValueError("Unclosed conditional block")

    def _enter_range(self, start: int, end: int, return_pc: int) -> None:
        """Переходит в неизменяемый диапазон, запоминая адрес продолжения."""
        if start >= end:
            self.index = return_pc
            return
        self.frames.append(ExecutionFrame(end=end, return_pc=return_pc))
        self.index = start

    def _state_value(self, name: str, state: dict | None = None):
        key = name.strip().lstrip("$")
        values = SCRIPT_STATE if state is None else state
        if key not in values:
            raise ValueError(f"Unknown script variable: ${key}")
        return values[key]

    def _evaluate_condition(self, expression: str, state: dict | None = None) -> bool:
        """Вычисляет ограниченное логическое выражение DSL."""
        expression = expression.strip()
        if expression.startswith("(") and expression.endswith(")"):
            expression = expression[1:-1].strip()

        expression = re.sub(
            r"\$[a-zA-Z0-9_.]+",
            lambda match: f'V("{match.group(0)[1:]}")',
            expression,
        )
        expression = expression.replace("&&", " and ").replace("||", " or ")
        expression = re.sub(r"!(?!=)", " not ", expression)
        expression = re.sub(r"\btrue\b", "True", expression, flags=re.IGNORECASE)
        expression = re.sub(r"\bfalse\b", "False", expression, flags=re.IGNORECASE)
        expression = re.sub(r"\bnull\b", "None", expression, flags=re.IGNORECASE)

        try:
            return bool(
                eval(
                    expression,
                    {"__builtins__": {}},
                    {"V": lambda name: self._state_value(name, state)},
                )
            )
        except Exception as exc:
            self.app.sub_title = f"[Script error] Invalid condition: {exc}"
            return False

    @staticmethod
    def _predict_change_state(line: str, state: dict) -> None:
        """Применяет простое присваивание к копии состояния для look-ahead."""
        match = re.match(
            r'\$(lp_)?([a-zA-Z0-9_.]+)\s*([+\-]?=)\s*(true|false|null|-?\d+)\s*$',
            line,
            re.IGNORECASE,
        )
        if not match:
            return
        prefix, target, operation, raw_value = match.groups()
        value_lower = raw_value.lower()
        if value_lower == "true":
            value = True
        elif value_lower == "false":
            value = False
        elif value_lower == "null":
            value = None
        else:
            value = int(raw_value)
        key = f"lp_{target}" if prefix == "lp_" else target
        if key not in state:
            return
        if operation == "=":
            state[key] = value
        elif operation == "+=":
            state[key] = int(state[key]) + int(value)
        elif operation == "-=":
            state[key] = int(state[key]) - int(value)

    def predict_visual_commands(
        self,
        start: int | None = None,
        frames: list[ExecutionFrame] | None = None,
        max_steps: int = 2000,
    ) -> tuple[str, ...]:
        """Возвращает изменения сцены до следующей видимой точки без side effects."""
        pc = self.index if start is None else start
        predicted_frames = list(self.frames if frames is None else frames)
        state = SCRIPT_STATE.copy()
        visual_commands = []

        for _ in range(max_steps):
            while predicted_frames and pc >= predicted_frames[-1].end:
                pc = predicted_frames.pop().return_pc
            if pc >= len(self.lines):
                break

            line = self.lines[pc]
            pc += 1
            if line.startswith("label"):
                continue
            if line.startswith("goto"):
                match = re.fullmatch(r"goto\s+([a-zA-Z0-9_]+)", line)
                if not match or match.group(1) not in self.labels:
                    break
                pc = self.labels[match.group(1)]
                predicted_frames.clear()
                continue
            if line.startswith("if ") or line.startswith("if("):
                branches = []
                condition = line[2:].strip()
                cursor = pc
                while True:
                    try:
                        block_start, block_end = self._read_block_range(cursor)
                    except ValueError:
                        return tuple(visual_commands)
                    cursor = block_end + 1
                    branches.append((condition, block_start, block_end))
                    if cursor >= len(self.lines):
                        break
                    next_line = self.lines[cursor]
                    if next_line.startswith("else if"):
                        condition = next_line[len("else if"):].strip()
                        cursor += 1
                        continue
                    if next_line == "else":
                        cursor += 1
                        try:
                            block_start, block_end = self._read_block_range(cursor)
                        except ValueError:
                            return tuple(visual_commands)
                        cursor = block_end + 1
                        branches.append((None, block_start, block_end))
                    break
                pc = cursor
                for branch_condition, block_start, block_end in branches:
                    if branch_condition is None or self._evaluate_condition(
                        branch_condition, state
                    ):
                        predicted_frames.append(
                            ExecutionFrame(end=block_end, return_pc=cursor)
                        )
                        pc = block_start
                        break
                continue
            if line.startswith("menu"):
                break
            if line.startswith("load"):
                break
            # Пауза — граница видимого кадра. Команды перед ней должны быть
            # показаны игроку, а не слиты с визуальными командами после неё.
            if line.startswith("pause"):
                break
            if line.startswith("$"):
                self._predict_change_state(line, state)
                continue
            if line.startswith(("scene", "show", "hide")):
                visual_commands.append(line)
                continue
            if '"' in line:
                break

        return tuple(visual_commands)

    def predict_choice_visual_commands(
        self, choice: ChoiceTarget
    ) -> tuple[str, ...]:
        """Прогнозирует первый кадр конкретного доступного пункта меню."""
        frames = list(self.frames)
        frames.append(ExecutionFrame(end=choice.end, return_pc=choice.return_pc))
        return self.predict_visual_commands(start=choice.start, frames=frames)

    async def _handle_if(self, line):
        """Выполняет первую истинную ветку цепочки if/else if/else."""
        branches = []
        condition = line[2:].strip()
        cursor = self.index

        while True:
            try:
                start, end = self._read_block_range(cursor)
            except ValueError as exc:
                self.app.sub_title = f"[Script error] {exc}"
                return
            cursor = end + 1
            branches.append((condition, start, end))

            if cursor >= len(self.lines):
                break
            next_line = self.lines[cursor]
            if next_line.startswith("else if"):
                condition = next_line[len("else if"):].strip()
                cursor += 1
                continue
            if next_line == "else":
                cursor += 1
                try:
                    start, end = self._read_block_range(cursor)
                except ValueError as exc:
                    self.app.sub_title = f"[Script error] {exc}"
                    return
                cursor = end + 1
                branches.append((None, start, end))
            break

        selected = None
        for branch_condition, start, end in branches:
            if branch_condition is None or self._evaluate_condition(branch_condition):
                selected = (start, end)
                break

        return_pc = cursor
        if selected:
            self._enter_range(*selected, return_pc)
        else:
            self.index = return_pc

        if not self.backward:
            await self.next_line()
           


    async def _handle_pause(self, line):
        """Обработка строки pause"""
        match = re.search(r'pause\s+(hard\s+)?(\d+(?:\.\d+)?)', line)
        if match:
            is_hard_pause = bool(match.group(1))
            seconds = float(match.group(2))
            if not self.backward:
                # В сценариях встречаются короткие pause между scene cg:
                # фиксируем текущий кадр до ожидания, иначе отложенный рендер
                # покажет только последний фон из всей последовательности.
                await self.app.flush_scene_render()
                self.app.prefetch_next_scene(self)
                self.app._space_require_idle = True
                await self.app.wait_script_delay(
                    seconds,
                    "hard_pause" if is_hard_pause else "pause",
                    skippable=not is_hard_pause,
                )
                await self.next_line()


    async def _handle_scene(self, line):
        """Обработка строки scene cg/bg"""
        if "scene color" in line:
            self.app.current_scene = ""
            self.app.current_scene_category = ""
            self.app.clear_active_sprites()
            self.app.mark_scene_dirty()
            if not self.backward:
                await self.next_line()
            return
    
        match = re.search(r'scene\s+(cg|bg)\s+([a-zA-Z0-9_]+)', line)
        if match:
            category = match.group(1)
            scene_name = match.group(2)

            # Смена сцены всегда очищает активные спрайты.
            self.app.current_scene = scene_name
            self.app.current_scene_category = category
            self.app.clear_active_sprites()

            self.app.mark_scene_dirty()
    
            if not self.backward:
                await self.next_line()


    async def _handle_show(self, line):
        """Обработка show: собрать спрайт, добавить/заменить его на сцене."""
        self.app.show_sprite_from_script_line(line)
        self.app.mark_scene_dirty()

        if not self.backward:
            await self.next_line()


    async def _handle_hide(self, line):
        """Обработка hide: убрать персонажа со сцены."""
        match = re.search(r'hide\s+([a-zA-Z0-9_]+)', line)
        if match:
            character_id = match.group(1)
            self.app.hide_sprite_by_id(character_id)
            self.app.mark_scene_dirty()

        if not self.backward:
            await self.next_line()


    async def _handle_play(self, line):
        """Обработка строки play"""
        if not self.backward:
            await self.next_line()


    async def _handle_window(self, line):
        """Обработка строки window"""
        novel_menu = self.app.query_one("#novel-menu", expect_type=Widget)
        novel_menu.set_class("show" not in line, "invisible")
        if not self.backward:
            await self.next_line()


    async def _handle_choice(self, line):
        """Обработка строки menu и логика выбора"""

        options = {}
        cursor = self.index  # строка после "menu"

        while cursor < len(self.lines):
            line = self.lines[cursor].strip()

            # конец всего блока меню
            if line == "}":
                cursor += 1
                break

            # начало варианта
            if line.startswith('"'):
                choice_match = re.match(r'"(.+?)"(?:\s+if\s+(.+))?$', line)
                if not choice_match:
                    cursor += 1
                    continue
                choice_text, condition = choice_match.groups()
                cursor += 1

                if condition and not self._evaluate_condition(condition):
                    # Пропускаем тело недоступного пункта.
                    if cursor < len(self.lines) and self.lines[cursor] == "{":
                        _, cursor = self._read_block_range(cursor)
                        cursor += 1
                    continue

                if cursor < len(self.lines) and self.lines[cursor] == "{":
                    start, end = self._read_block_range(cursor)
                    cursor = end + 1
                    options[choice_text] = ChoiceTarget(start, end, 0)
            else:
                cursor += 1

        # Выполнение продолжится после закрывающей скобки выбранного меню.
        options = {
            text: ChoiceTarget(target.start, target.end, cursor)
            for text, target in options.items()
        }
        self.index = cursor

        # показать ChoiceBar
        choice_bar = self.app.query_one("#choice-bar")
        list_view = choice_bar.query_one(ListView)

        list_view.clear()
        for opt in options:
            list_view.append(ListItem(Label(opt)))

        # сохранить варианты в app
        self.app.pending_choices = options

        await self.app.flush_scene_render()
        self.app.prefetch_choice_scenes(self, options.values())

        # отобразить ChoiceBar и скрыть фон
        choice_bar.remove_class("hidden")
        self.app.query_one("#bg-cg").add_class("hidden")
        if self.app.current_text_mode == "nvl":
            self.app.query_one("#novel-window").remove_class("hidden")
            self.app.query_one("#novel-menu").add_class("hidden")

        # дождаться одного кадра, чтобы Textual успел пересчитать фокус
        await asyncio.sleep(0.01)

        # изменение высоты окна от кол-ва элементов
        rows = len(list_view.children)
        row_height = 3
        list_view.styles.height = max(1, rows) * row_height

        # найти ListView и перевести на него фокус 
        if list_view.children:
            list_view.index = 0
            list_view.focus() 

    def select_choice(self, choice: ChoiceTarget) -> None:
        """Выполняет выбранный пользователем неизменяемый диапазон меню."""
        self._enter_range(choice.start, choice.end, choice.return_pc)


    @staticmethod
    def _normalize_log_text(text: str) -> str:
        """Подготовка текста для окна истории."""
        text = " ".join(part.strip() for part in text.split("<w>") if part.strip())
        text = re.sub(r"</?(i|b)>", "", text)
        return text.strip()


    async def _handle_dialogue(self, line):
        """Обработка строки диалога с анимацией текста"""
        await self.app.flush_scene_render()
        self.app.prefetch_next_scene(self)
        widget = self.app.query_one("#text-bar", expect_type=Widget)
        btn = self.app.query_one("#btn-next")

        # Скрываем кнопку на время показа текста
        btn.add_class("invisible")
        self.app._text_animating = True
        self.app._text_animating_since = _time.get_time()
        self.app._text_animating_until = self.app._text_animating_since
        self.app._space_require_idle = True

        try:
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

            self.app.add_log_entry(
                text=self._normalize_log_text(text),
                speaker=speaker,
                speaker_id=id_to_set,
            )

            is_nvl = self.app.current_text_mode == "nvl"
            widget.remove_class(*[cls for cls in widget.classes if cls != "text-bar"])
            if id_to_set:
                widget.add_class(id_to_set)

            widget.border_title = "" if is_nvl else speaker

            # Конвертируем <i>, <b> в rich-разметку
            text = re.sub(r'<i>(.*?)</i>', r'[italic]\1[/italic]', text)
            text = re.sub(r'<b>(.*?)</b>', r'[bold]\1[/bold]', text)

            if is_nvl:
                if widget.text:
                    widget.text += "\n"
                if speaker:
                    widget.text += f"[bold]{speaker}:[/bold] "
                widget.refresh()

            # Разбиваем текст на части по <w> с паузами
            parts = text.split("<w>")
            for i, part in enumerate(parts):
                part = part.strip()
                if part:
                    prefix = "" if i == 0 else " "
                    await widget.animate_text(
                        prefix + part,
                        append=is_nvl or i > 0,
                    )

                if i < len(parts) - 1:
                    # В отличие от посимвольной печати, пауза <w> может быть
                    # пропущена пробелом или кнопкой «Продолжить».
                    show_skip_button = not self.app.query_one(
                        "#novel-menu", expect_type=Widget
                    ).has_class("invisible")
                    if show_skip_button:
                        btn.remove_class("invisible")
                    try:
                        await self.app.wait_script_delay(1, "w")
                    finally:
                        if (
                            show_skip_button
                            and getattr(self.app, "script", None) is self
                        ):
                            btn.add_class("invisible")
        finally:
            # При сбросе/загрузке app.script заменяется или удаляется до
            # отмены старой задачи. Не позволяем её finally-блоку менять UI
            # уже нового сценария.
            if getattr(self.app, "script", None) is self:
                self.app._text_animating = False
                self.app._text_animating_until = _time.get_time()

                # Показать кнопку обратно
                btn.remove_class("invisible")

                # Фокусируем кнопку только если меню выбора НЕ открыто
                choice_bar = self.app.query_one("#choice-bar")
                if choice_bar.has_class("hidden"):
                    btn.focus()


    async def _handle_changeLP(self, line):
        """Обработка изменения поинтов и флагов"""
        global SL, UN, DV, US  # Поинты
        global PROLOGUE, D1_KEYS # Флаги

        # Парсим строку ($lp_sl += 1, $day2_flag = true, $persistent.flag = false)
        match = re.match(
            r'\$(lp_)?([a-zA-Z0-9_.]+)\s*([+\-]?=)\s*(true|false|null|-?\d+)\s*$',
            line,
            re.IGNORECASE,
        )
        if not match:
            if not self.backward:
                await self.next_line()
            return

        prefix, target, operation, raw_value = match.groups()
        value_lower = raw_value.lower()
        if value_lower == "true":
            value = True
        elif value_lower == "false":
            value = False
        elif value_lower == "null":
            value = None
        else:
            value = int(raw_value)

        state_key = f"lp_{target}" if prefix == "lp_" else target
        if state_key not in SCRIPT_STATE:
            self.app.sub_title = f"[Script error] Unknown script variable: ${state_key}"
            if not self.backward:
                await self.next_line()
            return

        # Извлекаем текущее значение
        current = SCRIPT_STATE[state_key]

        # Применяем операцию
        if operation == "+=":
            if isinstance(current, bool):
                current = int(current)
            if isinstance(value, bool):
                value = int(value)
            current += value
        elif operation == "-=":
            if isinstance(current, bool):
                current = int(current)
            if isinstance(value, bool):
                value = int(value)
            current -= value
        elif operation == "=":
            current = value
        else:
            return

        # Обновляем единое состояние и совместимые поля UI.
        SCRIPT_STATE[state_key] = current
        _sync_legacy_globals()

        # Продолжаем выполнение
        if not self.backward:
            await self.next_line()

    async def _handle_load(self, line):
        """Переход к файлу сценария"""
        match = re.match(r'load\s+(.+)$', line)
        if not match:
            return

        raw_target = match.group(1).strip().strip('"').strip("'")
        if not raw_target:
            return

        current_dir = Path(self.filename).resolve().parent
        target_path = Path(raw_target)

        if target_path.suffix.lower() != ".txt":
            target_path = target_path.with_suffix(".txt")
        if not target_path.is_absolute():
            target_path = current_dir / target_path

        target_path = target_path.resolve()
        if not target_path.exists():
            self.app.sub_title = f"[Load error] File not found: {target_path}"
            return

        self.load_script(target_path)
        self.app.start_script_preload(self)
        if not self.backward:
            await self.next_line()
