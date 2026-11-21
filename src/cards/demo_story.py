"""Изолированный фрагмент day2.rpy: от стола Лены до конца турнира.

Реплики и точки остановки — из оригинала (1573–2064), не новый DSL.
Прогресс стенда локален; сценарный runtime и persistent не используются.
"""

from collections import deque
from dataclasses import dataclass

from cards.game import CardGame, Phase
from cards.scene import CardScene


@dataclass(frozen=True)
class StoryLine:
    speaker: str
    text: str
    scene: CardScene | None = None
    reveal: bool = False


def line(speaker, text, *, character=None, expression="normal", background=None, reveal=False):
    scene = None
    if character is not None or background is not None:
        category, name = background or ("bg", "int_dining_hall_sunset")
        scene = CardScene(category, name, character or "", expression + "_pioneer")
    return StoryLine(speaker, text, scene, reveal)


# day2.rpy:1573–1585.
INTRO = (
    line("", "Я подошёл к столу, за которым сидела Лена.", character=""),
    line("me", "Не возражаете?", character="un"),
    line("", "Она подняла на меня глаза и покраснела."),
    line("me", "Не волнуйся, я тоже правил не знаю.", character="un", expression="shy"),
    line("th", "И почему «тоже»?"),
    line("", "Я сел."),
    line("me", "Вот вышло так, что первый тур нам с тобой играть."),
    line("un", "Да."),
    line("", "Наконец Электроник начал объяснять правила."),
)

# В оригинале VISIBLE становится True ПОСЛЕ «Теперь можете их открыть».
TUTORIAL_INTRO = (
    line("el", "Посмотрите на карты внимательно.", character="el"),
    line("el", "Перед вами их ровно шесть!"),
    line("th", "Надеюсь, считать здесь все умеют."),
    line("el", "Теперь можете их открыть."),
    line("", "Когда все посмотрели свои карты, Электроник продолжил.", reveal=True),
    line("el", "Правила такие же, как в покере."),
    line("el", "Думаю, все играть умеют?"),
    line("", "Я-то умел, но вот в остальных не был уверен."),
    line("el", "Сначала идёт самая старшая карта, потом пара, потом две пары, потом тройка... Ну и так далее."),
    line("el", "Первым ходом вы выбираете карту, которую хотите забрать у противника."),
    line("el", "У него же в свою очередь есть возможность поменять карты местами два раза."),
    line("el", "Но можно и не менять, если собираются забрать ненужную карту."),
    line("el", "Но учтите – противник видит, какие карты вы меняете местами."),
    line("el", "Далее соперник забирает у вас одну карту."),
    line("el", "Ну, и так далее – думаю, всё понятно."),
    line("", "Мне было совершенно ничего не понятно."),
    line("us", "Эй, ты, Эйнштейн недоделанный!"),
    line("", "Послышался издалека голос Ульянки."),
    line("us", "Ничегошеньки не понятно!"),
    line("el", "По ходу разберёшься."),
    line("", "Электроник отошёл к столу со схемой, оставив Ульяну злиться в одиночестве.", character=""),
    line("me", "Ходи первая."),
    line("", "Я надеялся, что быстро смогу вникнуть в игру."),
    line("", "И Лена, смутившись ещё больше, чем обычно, потянулась к моим картам."),
)
TUTORIAL_DEFEND = (
    line("", "Но на середине стола её рука застыла."),
    line("un", "Ты будешь..."),
    line("th", "Точно! Я же должен защищать свою карту!"),
    line("th", "И что там говорил Электроник..."),
    line("", "Чтобы попытаться запутать соперника, можно поменять карты местами. И так два раза."),
    line("", "А можно и не менять."),
    line("", "Защищать мне эту карту или нет?"),
    line("", "К тому же я могу сразу согласиться и отдать ей карту, которую она выбрала."),
    line("", "А Лена может изменить свой выбор, взяв другую карту. А может и не менять."),
)
TUTORIAL_SELECT = (
    line("", "Понемногу всё становилось понятно! Или хотя бы понятнее..."),
    line("me", "Теперь моя очередь."),
    line("", "Я могу вернуть карту, которую она забрала, или выбрать любую другую."),
)
TUTORIAL_RIVAL_DEFEND = (
    line("", "Лена может попробовать защитить свою карту."),
    line("", "Но если я буду внимателен, то всё равно возьму ту, что выбрал с самого начала."),
)
AFTER_TUTORIAL = (
    line("", "Электроник, до этого лишь молча наблюдавший за игрой, удовлетворённо кивнул.", character=""),
    line("", "Похоже, теперь мы действительно немного разобрались, что к чему."),
    line("el", "Итак, во время игры противники три раза обмениваются картами, а потом вскрываются.", character="el"),
    line("", "У меня вырвался невольный смешок от слова «вскрываются»."),
    line("el", "Что смешного?", character="el", expression="angry"),
    line("me", "Нет, ничего."),
    line("", "Сдерживаясь из последних сил, чтобы не прыснуть, ответил я."),
    line("", "Он пристально посмотрел на меня и продолжил."),
    line("el", "И мы смотрим, у кого лучше карты.", character="el"),
    line("", "Электроник вернулся к своему ватману.", character=""),
)

# day2.rpy:1790–1857. Ветка стенда по умолчанию — без спора с Алисой.
LENA_WIN = (
    line("", "Я победил!", character=""),
    line("", "Вот уж действительно – трудно играть в игру, только что придуманную, да ещё и не тобой!"),
    line("", "Но я выиграл!"),
    line("", "Правда, радость победы немного омрачало то, что проигравшей оказалась Лена."),
    line("", "Она и без того была не особо уверена в себе."),
    line("th", "Теперь мне даже неудобно смотреть на неё."),
    line("", "Возможно, следовало всё-таки проиграть, чтобы повысить её самооценку."),
)
SECOND_ROUND = (
    line("", "Электроник тем временем с гордостью объявил, что первый тур окончен."),
    line("", "Через некоторое время на ватмане появилась схема участников второго тура.",
         background=("cg", "lvl_2_semen_win")),
    line("", "Пары полуфиналистов составили: Алиса и Женя, Ульяна и..."),
    line("", "Я."),
    line("", "У меня вырвался обречённый вздох."),
)
ULYANA_INTRO = (
    line("", "И тут же напротив уселась Ульяна!", character="us", expression="grin"),
    line("us", "Хы!"),
    line("", "С улыбкой до ушей она уставилась на меня.", character="us", expression="laugh"),
    line("us", "Как это ты Лену обыграл?"),
    line("us", "Жульничал, наверное?"),
    line("me", "Я же не ты."),
    line("me", "Просто я умею играть в карты."),
    line("th", "Пусть она хотя бы так думает."),
    line("me", "А ты как Шурика обыграла?"),
    line("us", "А...", character="us", expression="grin"),
    line("", "Ульянка махнула рукой, показывая, как это было просто."),
    line("us", "Пригрозила, что вступлю в его клуб."),
    line("", "И снова широко улыбнулась.", character="us", expression="laugh"),
    line("us", "Будешь мне поддаваться?"),
    line("me", "И не надейся!"),
    line("us", "Ну вот...", character="us", expression="dontlike"),
    line("us", "Тогда я сама буду выбирать, какую карту тебе отдать!", character="us", expression="laugh"),
    line("me", "Ты правила слышала?"),
    line("us", "Да плевать!", character="us", expression="laugh2"),
    line("", "Похоже, её действительно это мало волновало."),
    line("me", "Ладно, тогда и я буду отдавать тебе только те карты, что выберу сам."),
    line("us", "Договорились!", character="us", expression="laugh"),
    line("", "Воодушевлённый победой в первом туре, я решился на этот опасный шаг."),
    line("", "Можно было ввязаться в спор, позвать Электроника и в конце концов настоять на своём, но я почему-то был полностью уверен в исходе этой партии."),
    line("", "Да, мы нарушали правила игры, но находились с Ульянкой в равных условиях."),
    line("", "Я посмотрел на Электроника."),
    line("el", "Время начинать второй тур!"),
    line("", "Скомандовал он."),
    line("", "Я аккуратно открыл карты, стараясь не дать Ульянке заглянуть в них."),
)
ULYANA_WIN = (
    line("us", "Эй! Так нечестно!", character="us", expression="dontlike"),
    line("us", "Ты должен был поддаваться и проиграть!"),
    line("", "От недовольства она надула щёки и стала похожа на колобка."),
    line("us", "Давай переиграем, только ты теперь поддавайся, слышишь?!"),
    line("", "Но её слышал не только я, а весь зал."),
    line("", "И даже Электроник."),
    line("el", "Никаких переигровок!"),
    line("", "Ульяна не обратила на него ни малейшего внимания."),
    line("us", "Ты должен проиграть!", character="us", expression="angry"),
    line("me", "Я вообще с тобой не собираюсь играть второй раз."),
    line("", "Спокойно сказал я."),
    line("us", "Ах, так?"),
    line("me", "Да, так."),
    line("us", "Тогда я всем расскажу о том, что ты к Алисе приставал.", character="us", expression="grin"),
    line("", "Сказала она шёпотом."),
    line("me", "Чего?!"),
    line("", "Я перегнулся через стол и грозно посмотрел на неё."),
    line("me", "Значит, подслушивала?"),
    line("us", "Не подслушивала, а просто мимо проходила."),
    line("", "В конце концов, сыграть лишний раунд – это куда лучше, чем..."),
    line("th", "А ведь она может!"),
    line("", "Я вздохнул и обратился к Электронику."),
    line("me", "Переиграем, ничего страшного."),
    line("el", "Как знаете..."),
    line("", "Он пожал плечами."),
    line("", "Итак, матч-реванш начался."),
)
ULYANA_REMATCH_WIN = (
    line("me", "Проще простого.", character="us", expression="dontlike"),
    line("", "Сказал я и вальяжно развалился на стуле."),
    line("us", "Так нечестно!"),
    line("th", "Надеюсь, она не потребует ещё одной переигровки!"),
    line("me", "Почему же нечестно?"),
    line("", "Усмехнулся я."),
    line("us", "Ладно..."),
    line("", "Обиженно сказала Ульяна и встала из-за стола."),
    line("", "Я внимательно посмотрел на схему турнира, пытаясь понять, кто же мне достался в соперники по финалу.", character=""),
)
ALISA_INTRO = (
    line("", "В ту же секунду ко мне за стол села Алиса.", character="dv"),
    line("", "Я глупо и неестественно улыбнулся."),
    line("th", "Как будто боюсь её!"),
    line("me", "Поздравляю с победой."),
)
ALISA_NO_BET = (
    line("dv", "Ты ещё пожалеешь, что струсил.", character="dv", expression="angry"),
    line("th", "Да я уже жалею..."),
    line("", "И не о том, что струсил – не надо вообще было участвовать в этой дурацкой игре."),
)
ALISA_START = (line("dv", "Ладно, погнали!", character="dv", expression="smile"),)
DRAW = (line("el", "Ничья! Играйте ещё раз."),)
ENDINGS = {
    0: (line("", "Как обидно всё-таки проигрывать...", background=("cg", "lvl_2_lena_win")),),
    1: (line("", "Хотя бы один раунд я выиграл.", character=""),),
    2: (
        line("", "Двачевской я проиграл.", character=""),
        line("th", "И это ой как нехорошо."),
        line("th", "Можно только предполагать, что она завтра выкинет."),
        line("th", "Опозорит меня на линейке (если я её, конечно, не просплю), расскажет Ольге Дмитриевне."),
        line("th", "Просто пустит слухи по лагерю."),
        line("th", "Причём самое страшное, что поверят наверняка ей, а не мне."),
        line("", "Я даже не знал точно почему, но был в этом уверен на 100%."),
    ),
    3: (
        line("th", "И неважно, что я не стал спорить с Алисой, главное – выиграл.", character=""),
        line("th", "А то, зная её, можно только предполагать, что бы она завтра выкинула."),
        line("th", "Опозорила бы меня на линейке, рассказала бы Ольге Дмитриевне."),
        line("th", "Просто пустила бы слухи по лагерю."),
        line("th", "Причём самое страшное, что поверили бы наверняка ей, а не мне. Я даже не знаю точно почему, но уверен в этом на 100%."),
    ),
}
EXIT = (line("", "Я вышел из столовой.", background=("bg", "ext_dining_hall_away_night")),)


class CardStory:
    """Сюжетные паузы привязаны к фазам одной настоящей партии.

    advance() продвигает только реплику/результат; игровые действия проходят
    через CardTable. poll() останавливает игру перед сюжетным прерыванием.
    """

    def __init__(self, *, seed=None, rival=None):
        self.seed = seed
        self.deal_number = -1
        self.stage = "intro"
        self.game: CardGame | None = None
        self.dialogue: StoryLine | None = None
        self.scene = CardScene()
        self.on_table = False
        self.player_visible = True
        self.targets_visible = True
        self.done = False
        self.result: int | None = None
        self.history: list[StoryLine] = []
        self._lines = deque()
        self._resume = None
        self._hooks = set()
        if rival is None:
            self._say(INTRO, lambda: self._begin("tutorial"))
        elif rival == "un":
            self._begin("un")
        elif rival == "us":
            self._say(ULYANA_INTRO, lambda: self._begin("us"))
        elif rival == "dv":
            self._say(ALISA_INTRO + ALISA_NO_BET + ALISA_START, lambda: self._begin("dv"))
        else:
            raise ValueError("Неизвестная соперница")

    def _say(self, lines, resume):
        self._lines = deque(lines)
        self._resume = resume
        self.advance()

    def advance(self):
        if self._lines:
            self.dialogue = self._lines.popleft()
            if self.dialogue.scene is not None:
                self.scene = self.dialogue.scene
            if self.dialogue.reveal:
                self.player_visible = True
            self.history.append(self.dialogue)
        elif self.dialogue is not None:
            self.dialogue = None
            resume, self._resume = self._resume, None
            resume()
        elif self.game is not None and self.game.phase == Phase.RESULT and not self.done:
            self._resolve()

    def _begin(self, stage):
        self.stage = stage
        self.deal_number += 1
        seed = None if self.seed is None else self.seed + self.deal_number
        self.game = CardGame({"tutorial": "un", "un": "un", "us": "us", "us2": "us", "dv": "dv"}[stage],
                             seed=seed)
        self.on_table = True
        self.scene = CardScene()
        self._hooks.clear()
        self.player_visible = stage != "tutorial"
        self.targets_visible = stage != "tutorial"
        if stage == "tutorial":
            self._say(TUTORIAL_INTRO, self._tutorial_defend)

    def _tutorial_defend(self):
        self.targets_visible = True
        self._say(TUTORIAL_DEFEND, lambda: None)

    def poll(self):
        """Вызывать после изменения игрового состояния, до следующего хода."""
        if self.dialogue is not None or self.done or self.stage != "tutorial":
            return
        if self.game.round == 2:
            self._say((line("", "Получилось!"),), self._after_tutorial)
        elif self.game.phase == Phase.SELECT and "select" not in self._hooks:
            self._hooks.add("select")
            self._say(TUTORIAL_SELECT, lambda: None)
        elif self.game.phase == Phase.RIVAL_DEFEND and "defend" not in self._hooks:
            self._hooks.add("defend")
            self._say(TUTORIAL_RIVAL_DEFEND, lambda: None)

    def _after_tutorial(self):
        self.on_table = False
        self._say(AFTER_TUTORIAL, lambda: self._begin("un"))

    def _resolve(self):
        result = self.game.result
        if result == "draw":
            self._say(DRAW, lambda: self._begin(self.stage))
            return
        self.on_table = False
        if result == "fail":
            self._end({"un": 0, "us": 1, "us2": 1, "dv": 2}[self.stage])
        elif self.stage == "un":
            self._say(LENA_WIN + SECOND_ROUND + ULYANA_INTRO, lambda: self._begin("us"))
        elif self.stage == "us":
            self._say(ULYANA_WIN, lambda: self._begin("us2"))
        elif self.stage == "us2":
            self._say(ULYANA_REMATCH_WIN + ALISA_INTRO + ALISA_NO_BET + ALISA_START,
                      lambda: self._begin("dv"))
        else:
            self._end(3)

    def _end(self, result):
        self.stage = "ending"
        self.result = result
        self._say(ENDINGS[result] + EXIT, self._finish)

    def _finish(self):
        self.done = True
