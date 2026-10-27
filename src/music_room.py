"""Music gallery widgets. Selection is independent of playback and story choices."""

from rich.text import Text
from textual.containers import Grid, Vertical
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from music_catalog import filter_music, format_duration, load_music_catalog


class MusicRow(ListItem):
    def __init__(self, track):
        self.track = track
        super().__init__(Label(Text(track.title), classes="music-title"),
                         Label(format_duration(track.duration), classes="music-duration"))


class MusicRoom(Vertical):
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

    def compose(self):
        yield Input(placeholder="Поиск по названию", id="music-search")
        yield Static("↑/↓ - выбор · Enter/клик - слушать · Tab - кнопки · Esc - меню",
                     id="music-help")
        yield ListView(id="music-list")
        yield Static("", id="music-empty", classes="hidden")
        yield Static("Фоновая музыка меню", id="music-status")
        with Grid(id="music-controls"):
            yield Button("Предыдущий", id="music-previous")
            yield Button("Пауза", id="music-pause", disabled=True)
            yield Button("Стоп", id="music-stop", disabled=True)
            yield Button("Следующий", id="music-next")
            yield Button("Повтор: выкл.", id="music-repeat")
            yield Button("Музыка −10%", id="music-volume-minus")
            yield Label("", id="music-volume")
            yield Button("Музыка +10%", id="music-volume-plus")

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
        empty = self.query_one("#music-empty", Static)
        empty.set_class(bool(self.filtered), "hidden")
        empty.update(Text(self.catalog_error or "Ничего не найдено"))
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
        labels = {"loading": "Загрузка", "playing": "Сейчас играет", "paused": "Пауза",
                  "stopped": "Остановлено", "error": "Ошибка"}
        if status["error"]:
            message = status["error"]
        elif preview:
            duration = self.last_track.duration if self.last_track else 0
            message = (f"{labels[status['status']]}: {title}  "
                       f"{format_duration(status['position'])} / {format_duration(duration)}")
        else:
            message = "Фоновая музыка меню: Blow With The Fires"
        if self.app.settings["audio_muted"]:
            message += " · Без звука"
        self.query_one("#music-status", Static).update(Text(message))
        pause = self.query_one("#music-pause", Button)
        pause.label = "Продолжить" if status["status"] == "paused" else "Пауза"
        pause.disabled = not active or status["status"] == "loading"
        self.query_one("#music-stop", Button).disabled = not active
        for identity in ("music-previous", "music-next"):
            self.query_one(f"#{identity}", Button).disabled = not self.filtered
        self.query_one("#music-repeat", Button).label = "Повтор: вкл." if self.repeat else "Повтор: выкл."
        self.query_one("#music-volume", Label).update(f"{round(self.app.settings['audio_music'] * 100)}%")
        for row in self.query(MusicRow):
            playing = active and row.track.audio_key == status["key"]
            row.set_class(playing, "music-playing")
            marker = "Ⅱ " if status["status"] == "paused" else "▶ "
            row.query_one(".music-title", Label).update(Text((marker if playing else "  ") + row.track.title))
