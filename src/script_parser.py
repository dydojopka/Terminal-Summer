import asyncio
import re
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


class ScriptParser:
    def __init__(self, filename, app):
        self.filename = filename
        self.app = app
        self.lines = []
        self.labels = {}
        self.index = 0
        self.backward = False
        self.load_script()


    def load_script(self, filename=None):
        """Загрузка файла сценария"""
        if filename:
            self.filename = str(filename)
        with open(self.filename, 'r', encoding='utf-8') as f:
            self.lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
        self._index_labels()
        self.index = 0

    def restore_runtime_lines(self, lines: list[str]) -> None:
        """Восстанавливает строки с уже вставленными блоками выбранных меню."""
        self.lines = lines.copy()
        self._index_labels()

    def _index_labels(self) -> None:
        """Строит индекс меток для текущего набора строк."""
        self.labels = {}
        for index, line in enumerate(self.lines):
            match = re.fullmatch(r"label\s+([a-zA-Z0-9_]+):?", line)
            if match:
                self.labels[match.group(1)] = index

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
        if not self.backward:
            await self.next_line()

    def _read_block(self, start: int) -> tuple[list[str], int]:
        """Читает блок `{ ... }` и возвращает строки и индекс после него."""
        if start >= len(self.lines) or self.lines[start] != "{":
            raise ValueError("Expected `{` after conditional")

        depth = 1
        index = start + 1
        block = []
        while index < len(self.lines) and depth:
            line = self.lines[index]
            if line == "{":
                depth += 1
            elif line == "}":
                depth -= 1
                if depth == 0:
                    return block, index + 1
            block.append(line)
            index += 1

        raise ValueError("Unclosed conditional block")

    def _state_value(self, name: str):
        key = name.strip().lstrip("$")
        if key not in SCRIPT_STATE:
            raise ValueError(f"Unknown script variable: ${key}")
        return SCRIPT_STATE[key]

    def _evaluate_condition(self, expression: str) -> bool:
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
            return bool(eval(expression, {"__builtins__": {}}, {"V": self._state_value}))
        except Exception as exc:
            self.app.sub_title = f"[Script error] Invalid condition: {exc}"
            return False

    async def _handle_if(self, line):
        """Выполняет первую истинную ветку цепочки if/else if/else."""
        branches = []
        condition = line[2:].strip()
        cursor = self.index

        while True:
            try:
                block, cursor = self._read_block(cursor)
            except ValueError as exc:
                self.app.sub_title = f"[Script error] {exc}"
                return
            branches.append((condition, block))

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
                    block, cursor = self._read_block(cursor)
                except ValueError as exc:
                    self.app.sub_title = f"[Script error] {exc}"
                    return
                branches.append((None, block))
            break

        selected = None
        for branch_condition, block in branches:
            if branch_condition is None or self._evaluate_condition(branch_condition):
                selected = block
                break

        insertion_index = cursor
        self.index = insertion_index
        if selected:
            self.lines[insertion_index:insertion_index] = selected
            self._index_labels()
            self.index = insertion_index

        if not self.backward:
            await self.next_line()
           


    async def _handle_pause(self, line):
        """Обработка строки pause"""
        match = re.search(r'pause\s+(hard\s+)?(\d+)', line)
        if match:
            seconds = int(match.group(2))
            if not self.backward:
                self.app._input_blocked = True
                self.app._input_blocked_since = _time.get_time()
                self.app._input_blocked_until = self.app._input_blocked_since
                self.app._space_require_idle = True
                try:
                    await asyncio.sleep(seconds)
                finally:
                    self.app._input_blocked = False
                    self.app._input_blocked_until = _time.get_time()
                await self.next_line()


    async def _handle_scene(self, line):
        """Обработка строки scene cg/bg"""
        if "scene color" in line:
            self.app.current_scene = ""
            self.app.current_scene_category = ""
            self.app.clear_active_sprites()
            bg_cg = self.app.query_one("#bg-cg", expect_type=Widget)
            bg_cg.update("")
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

            ansi_art = self.app.generate_scene_with_sprites_ansi()

            bg_cg = self.app.query_one("#bg-cg", expect_type=Widget)
            bg_cg.update(ansi_art)
    
            if not self.backward:
                await self.next_line()


    async def _handle_show(self, line):
        """Обработка show: собрать спрайт, добавить/заменить его на сцене."""
        ansi_art = self.app.show_sprite_from_script_line(line)
        if ansi_art is not None:
            bg_cg = self.app.query_one("#bg-cg", expect_type=Widget)
            bg_cg.update(ansi_art)

        if not self.backward:
            await self.next_line()


    async def _handle_hide(self, line):
        """Обработка hide: убрать персонажа со сцены."""
        match = re.search(r'hide\s+([a-zA-Z0-9_]+)', line)
        if match:
            character_id = match.group(1)
            ansi_art = self.app.hide_sprite_by_id(character_id)
            bg_cg = self.app.query_one("#bg-cg", expect_type=Widget)
            bg_cg.update(ansi_art)

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
                choice_match = re.match(r'"(.+?)"(?:\s+if\s+(.+))?$', line)
                if not choice_match:
                    self.index += 1
                    continue
                choice_text, condition = choice_match.groups()
                self.index += 1
                block_lines = []

                if condition and not self._evaluate_condition(condition):
                    # Пропускаем тело недоступного пункта.
                    if self.index < len(self.lines) and self.lines[self.index] == "{":
                        _, self.index = self._read_block(self.index)
                    continue

                # собираем строки внутри { ... }
                if self.index < len(self.lines) and self.lines[self.index] == "{":
                    block_lines, self.index = self._read_block(self.index)

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
        await asyncio.sleep(0.01)

        # изменение высоты окна от кол-ва элементов
        rows = len(list_view.children)
        row_height = 3
        list_view.styles.height = max(1, rows) * row_height

        # найти ListView и перевести на него фокус 
        if list_view.children:
            list_view.index = 0
            list_view.focus() 


    @staticmethod
    def _normalize_log_text(text: str) -> str:
        """Подготовка текста для окна истории."""
        text = " ".join(part.strip() for part in text.split("<w>") if part.strip())
        text = re.sub(r"</?(i|b)>", "", text)
        return text.strip()


    async def _handle_dialogue(self, line):
        """Обработка строки диалога с анимацией текста"""
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
        finally:
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
        if not self.backward:
            await self.next_line()
