"""Music gallery widgets. Selection is independent of playback and story choices."""

from rich.text import Text
from textual.containers import Grid, Vertical
from textual.widgets import Input, Label, ListItem, ListView, Static

from console_button import ConsoleButton as Button

from music_catalog import filter_music, format_duration, load_music_catalog


class MusicRow(ListItem):
    def __init__(self, track):
        self.track = track
        super().__init__(Label(Text(track.title), classes="music-title"),
                         Label(format_duration(track.duration), classes="music-duration"))


class MusicRoom(Vertical):
    BUTTON_LABELS = {
        "music-previous": "Предыдущий", "music-pause": "Пауза", "music-stop": "Стоп",
        "music-next": "Следующий", "music-repeat": "Повтор: выкл.",
        "music-volume-minus": "Музыка −10%", "music-volume-plus": "Музыка +10%",
    }
    PLAYBACK_LABELS = {"loading": "Загрузка", "playing": "Сейчас играет", "paused": "Пауза",
                       "stopped": "Остановлено", "error": "Ошибка"}
    SEARCH_PLACEHOLDER = "Поиск по названию"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tracks = ()
        self.filtered = ()
        self.selected_id = None
        self.last_track = None
        self.repeat = False
        self.catalog_error = None
        self._rebuilding = False
        self._last_display = None
        self.strings: dict[str, str] = {}

    def compose(self):
        yield Input(placeholder=self.SEARCH_PLACEHOLDER, id="music-search")
        yield ListView(id="music-list")
        yield Static("", id="music-empty", classes="hidden")
        yield Static("Фоновая музыка меню", id="music-status")
        with Grid(id="music-controls"):
            for key, label in self.BUTTON_LABELS.items():
                if key == "music-volume-plus":
                    yield Label("", id="music-volume")
                yield Button(label, id=key, disabled=key in {"music-pause", "music-stop"})

    def apply_language(self, strings: dict[str, str]) -> None:
        self.strings = strings
        self.query_one("#music-search", Input).placeholder = strings.get("music-search", self.SEARCH_PLACEHOLDER)
        for key, label in self.BUTTON_LABELS.items():
            self.query_one(f"#{key}", Button).label = strings.get(key, label)
        self.update_empty()
        self._last_display = None
        self.update_player()

    def update_empty(self) -> None:
        empty = self.query_one("#music-empty", Static)
        empty.set_class(bool(self.filtered), "hidden")
        message = (self.strings.get("music.catalog-error", self.catalog_error) if self.catalog_error
                   else self.strings.get("music.empty", "Ничего не найдено"))
        empty.update(Text(message))

    async def on_mount(self):
        try:
            self.tracks = load_music_catalog(audio_catalog=self.app.audio.catalog)
        except ValueError as exc:
            self.catalog_error = str(exc)
        await self.rebuild_list("")
        self.set_interval(0.2, self.update_player)

    def on_resize(self):
        columns = 4 if self.size.width >= 56 else 2
        controls = self.query_one("#music-controls", Grid)
        controls.styles.grid_size_columns = columns
        controls.styles.grid_size_rows = 8 // columns
        controls.styles.height = 3 * (8 // columns)

    async def on_input_changed(self, event: Input.Changed):
        event.stop()
        await self.rebuild_list(event.value)

    async def rebuild_list(self, query):
        self._rebuilding = True
        listing = self.query_one("#music-list", ListView)
        self.filtered = filter_music(self.tracks, query)
        await listing.clear()
        await listing.extend(MusicRow(track) for track in self.filtered)
        listing.index = next((i for i, track in enumerate(self.filtered)
                              if track.id == self.selected_id), 0) if self.filtered else None
        if listing.index is not None:
            self.selected_id = self.filtered[listing.index].id
        self.update_empty()
        self._rebuilding = False
        self._last_display = None
        self.update_player()

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        event.stop()
        if not self._rebuilding and isinstance(event.item, MusicRow):
            self.selected_id = event.item.track.id

    def on_list_view_selected(self, event: ListView.Selected):
        event.stop()  # Never bubble into the novel's choice handler.
        if isinstance(event.item, MusicRow):
            self.play_track(event.item.track)

    def play_track(self, track):
        self.last_track = track
        self.app.start_music_preview(track.audio_key, repeat=self.repeat)
        self.update_player()

    def step_track(self, direction):
        if not self.filtered:
            return
        status = self.app.audio.music_status()
        current_key = status["key"] if status["owner"] == "preview" else None
        index = next((i for i, track in enumerate(self.filtered) if track.audio_key == current_key), None)
        if index is None:
            index = next((i for i, track in enumerate(self.filtered) if track.id == self.selected_id), 0)
        index = (index + direction) % len(self.filtered)
        self.query_one("#music-list", ListView).index = index
        self.selected_id = self.filtered[index].id
        self.play_track(self.filtered[index])

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        identity = event.button.id
        audio = self.app.audio
        if identity == "music-previous":
            self.step_track(-1)
        elif identity == "music-next":
            self.step_track(1)
        elif identity == "music-pause":
            if audio.music_status()["status"] == "paused":
                audio.resume_preview()
            else:
                audio.pause_preview()
        elif identity == "music-stop":
            audio.stop_preview()
        elif identity == "music-repeat":
            self.repeat = not self.repeat
            audio.set_preview_repeat(self.repeat)
        elif identity in {"music-volume-minus", "music-volume-plus"}:
            delta = 0.1 if identity.endswith("plus") else -0.1
            settings = self.app.settings
            settings["audio_music"] = max(0.0, min(1.0, round(settings["audio_music"] + delta, 2)))
            self.app.apply_audio_settings()
            self.app.save_settings()
        self.update_player()

    def update_player(self):
        # Hidden tabs do not continually redraw the gallery or touch native audio.
        if self._rebuilding or not self.is_on_screen:
            return
        status = self.app.audio.music_status()
        preview = status["owner"] == "preview"
        active = preview and status["key"] is not None
        display = (status["owner"], status["key"], status["status"], int(status["position"]),
                   status["error"], self.repeat, self.app.settings["audio_music"],
                   self.app.settings["audio_muted"], len(self.filtered))
        if display == self._last_display:
            return
        self._last_display = display
        title = self.last_track.title if self.last_track and preview else ""
        strings = self.strings
        if status["error"]:
            message = strings.get("music.playback-error", status["error"])
        elif preview:
            duration = self.last_track.duration if self.last_track else 0
            playback = status["status"]
            label = strings.get(f"music.{playback}", self.PLAYBACK_LABELS[playback])
            message = (f"{label}: {title}  "
                       f"{format_duration(status['position'])} / {format_duration(duration)}")
        else:
            message = f"{strings.get('music.menu-theme', 'Фоновая музыка меню')}: Blow With The Fires"
        if self.app.settings["audio_muted"]:
            message += " · " + strings.get("music.muted", "Без звука")
        self.query_one("#music-status", Static).update(Text(message))
        pause = self.query_one("#music-pause", Button)
        pause.label = (strings.get("music.resume", "Продолжить") if status["status"] == "paused"
                       else strings.get("music-pause", self.BUTTON_LABELS["music-pause"]))
        pause.disabled = not active or status["status"] == "loading"
        self.query_one("#music-stop", Button).disabled = not active
        for identity in ("music-previous", "music-next"):
            self.query_one(f"#{identity}", Button).disabled = not self.filtered
        self.query_one("#music-repeat", Button).label = (
            strings.get("music.repeat-on", "Повтор: вкл.") if self.repeat
            else strings.get("music-repeat", self.BUTTON_LABELS["music-repeat"])
        )
        self.query_one("#music-volume", Label).update(f"{round(self.app.settings['audio_music'] * 100)}%")
        for row in self.query(MusicRow):
            playing = active and row.track.audio_key == status["key"]
            row.set_class(playing, "music-playing")
            marker = "Ⅱ " if status["status"] == "paused" else "▶ "
            row.query_one(".music-title", Label).update(Text((marker if playing else "  ") + row.track.title))
