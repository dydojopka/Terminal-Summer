"""Nonblocking audio controller with a single worker owning SDL_mixer.

UI commands update a small logical state. Only the worker loads/decodes audio,
touches the mixer and applies fades. Serial numbers invalidate stale loads.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import threading
import time

from audio_catalog import finite_number, load_audio_catalog, resolve_audio_path
from script_audio import CHANNELS, CHANNEL_GROUPS, LOOP_CHANNELS, parse_audio_command, validate_audio_key


AUDIO_DEFAULTS = {"audio_master": 1.0, "audio_music": 0.7, "audio_environment": 0.7,
                  "audio_effects": 0.8, "audio_muted": False}


def normalize_audio_settings(settings: dict) -> dict:
    result = {}
    for key, default in AUDIO_DEFAULTS.items():
        value = settings.get(key, default)
        if key == "audio_muted":
            result[key] = value if type(value) is bool else default
        else:
            try:
                result[key] = finite_number(value, maximum=1)
            except ValueError:
                result[key] = default
    return result


class NullAudioBackend:
    """Explicit silent fallback; logical channel state remains in AudioManager."""

    def prepare(self, channel, path):
        return None

    def play(self, channel, prepared, loop, volume, position):
        return position

    def discard(self, prepared):
        pass

    def stop(self, channel):
        pass

    def volume(self, channel, value):
        pass

    def load_music(self, prepared):
        pass

    def pause_music(self):
        pass

    def resume_music(self):
        pass

    def music_busy(self):
        return True  # Silent/headless backend has no native EOF notification.

    def trim(self):
        pass

    def close(self):
        pass


class PygameAudioBackend:
    """All methods are called from one worker; no pygame window/event queue."""

    CACHE_LIMIT = 128 * 1024 * 1024
    BUFFER_SAMPLES = 2048  # ~43 ms at 48 kHz; more headroom during scene redraws.

    def __init__(self):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        from pygame import mixer, error

        self.mixer = mixer
        self.error = error
        mixer.init(frequency=48000, size=-16, channels=2, buffer=self.BUFFER_SAMPLES)
        mixer.set_num_channels(5)
        self.channels = {name: mixer.Channel(index) for index, name in
                         enumerate(channel for channel in CHANNELS if channel != "music")}
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.active = {}
        self.loaded_music = None

    def prepare(self, channel, path):
        if channel == "music":
            # A filename lets SDL stream directly from native file I/O. Passing
            # BytesIO installs Python read callbacks in the mixer thread, which
            # compete for the GIL with ANSI/Rich rendering and can stall all audio.
            return str(path)
        cache_key = str(path)
        if cache_key not in self.cache:
            sound = self.mixer.Sound(str(path))
            pcm_bytes = round(sound.get_length() * 48000) * 4
            self.cache[cache_key] = (sound, pcm_bytes)
            self.cache_bytes += pcm_bytes
        self.cache.move_to_end(cache_key)
        return cache_key, self.cache[cache_key][0]

    def discard(self, prepared):
        self.trim()

    def play(self, channel, prepared, loop, volume, position):
        if channel == "music":
            if self.loaded_music != prepared:
                self.load_music(prepared)
            self.mixer.music.set_volume(volume)  # load resets volume
            try:
                self.mixer.music.play(loops=-1 if loop else 0, start=position)
            except (NotImplementedError, self.error):
                if not position:
                    raise
                self.mixer.music.play(loops=-1 if loop else 0)
                return 0.0  # caller reports a seek fallback
        else:
            cache_key, sound = prepared
            self.channels[channel].stop()
            self.channels[channel].set_volume(volume)
            self.channels[channel].play(sound, loops=-1 if loop else 0)
            self.active[channel] = cache_key
            position = 0.0  # Sound channels have no seek API
        return position

    def load_music(self, prepared):
        self.stop("music")
        self.mixer.music.load(prepared)
        self.loaded_music = prepared

    def pause_music(self):
        self.mixer.music.pause()

    def resume_music(self):
        self.mixer.music.unpause()

    def music_busy(self):
        return self.mixer.music.get_busy()

    def stop(self, channel):
        if channel == "music":
            self.mixer.music.stop()
            self.mixer.music.unload()
            self.loaded_music = None
        else:
            self.channels[channel].stop()
            self.active.pop(channel, None)

    def volume(self, channel, value):
        target = self.mixer.music if channel == "music" else self.channels[channel]
        target.set_volume(value)

    def trim(self):
        for channel in tuple(self.active):
            if not self.channels[channel].get_busy():
                self.active.pop(channel)
        pinned = set(self.active.values())
        for key in tuple(self.cache):
            if self.cache_bytes <= self.CACHE_LIMIT:
                break
            if key not in pinned:
                _, size = self.cache.pop(key)
                self.cache_bytes -= size

    def close(self):
        for channel in CHANNELS:
            self.stop(channel)
        self.cache.clear()
        self.cache_bytes = 0
        self.mixer.quit()


@dataclass
class ChannelState:
    key: str | None = None
    volume: float = 1.0
    serial: int = 0
    started_at: float | None = None
    position: float = 0.0
    # (kind, initial level, duration, anchor); pending plays have no anchor.
    fade: tuple | None = None
    paused: bool = False
    status: str = "stopped"
    error: str | None = None


class AudioManager:
    def __init__(self, ts_dir: Path, *, catalog=None, backend_factory=PygameAudioBackend,
                 clock=time.monotonic):
        self.ts_dir = ts_dir
        self.catalog = load_audio_catalog() if catalog is None else catalog
        self.backend_factory = backend_factory
        self.clock = clock
        self.settings = AUDIO_DEFAULTS.copy()
        self.states = {channel: ChannelState() for channel in CHANNELS}
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._thread = None
        self._errors = queue.SimpleQueue()
        self.music_owner = None  # None / menu / story / preview; UI audio is never saved.
        self.preview_repeat = False
        self._device_error = None

    def _start(self):
        if self._closed:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="terminal-summer-audio", daemon=True)
            self._thread.start()
        self._wake.set()

    def set_settings(self, settings):
        with self._lock:
            self.settings = normalize_audio_settings(settings)
        self._wake.set()

    def _envelope(self, state, now):
        if state.fade is None:
            return 1.0
        kind, level, duration, anchor = state.fade
        elapsed = 0 if anchor is None else max(0, now - anchor)
        fraction = min(1, elapsed / duration)
        return level + ((1 if kind == "in" else 0) - level) * fraction

    def _settle(self, channel, now):
        state = self.states[channel]
        if state.fade and state.fade[3] is not None and now - state.fade[3] >= state.fade[2]:
            if state.fade[0] == "out":
                state.key = None
                state.serial += 1
                state.started_at = None
                state.position = 0
            state.fade = None
        if (state.key and channel not in LOOP_CHANNELS and state.started_at is not None
                and now - state.started_at >= self.catalog[state.key].duration):
            state.key = None
            state.serial += 1
            state.started_at = None
            state.fade = None

    def _gain(self, channel, now):
        if self.settings["audio_muted"]:
            return 0.0
        return (self.settings["audio_master"] * self.settings["audio_" + CHANNEL_GROUPS[channel]]
                * self.states[channel].volume * self._envelope(self.states[channel], now))

    def execute(self, line):
        command = parse_audio_command(line, self.catalog)
        with self._lock:
            if self._closed:
                return
            now = self.clock()
            self._settle(command.channel, now)
            state = self.states[command.channel]
            if command.action == "volume":
                state.volume = command.value
            elif command.action == "play":
                if command.channel == "music":
                    self.music_owner = "story"
                state.key = command.key
                state.serial += 1
                state.started_at = None
                state.position = 0
                state.fade = ("in", 0.0, command.value, None) if command.value else None
                state.paused = False
                state.status = "loading"
                state.error = None
            elif command.value and state.key:
                state.fade = ("out", self._envelope(state, now), command.value, now)
            else:
                state.key = None
                state.serial += 1
                state.started_at = None
                state.position = 0
                state.fade = None
                state.paused = False
                state.status = "stopped"
            self._start()

    def play_menu(self, key):
        with self._lock:
            self.reset()
            self.execute(f"play music {key} fadein 1")
            self.music_owner = "menu"

    def start_preview(self, key, *, repeat=False):
        validate_audio_key("music", key, self.catalog)
        if type(repeat) is not bool:
            raise ValueError("Повтор должен быть bool")
        with self._lock:
            self.execute(f"play music {key}")
            self.states["music"].volume = 1.0
            self.music_owner = "preview"
            self.preview_repeat = repeat

    def pause_preview(self):
        with self._lock:
            state = self.states["music"]
            if self.music_owner != "preview" or not state.key or state.paused:
                return
            if state.started_at is not None:
                state.position += max(0, self.clock() - state.started_at)
            state.started_at = None
            state.paused = True
            if state.status != "loading":
                state.status = "paused"
        self._wake.set()

    def resume_preview(self):
        with self._lock:
            state = self.states["music"]
            if self.music_owner != "preview" or not state.key or not state.paused:
                return
            state.paused = False
            if state.status != "loading":
                state.started_at = self.clock()
                state.status = "playing"
        self._wake.set()

    def stop_preview(self):
        with self._lock:
            if self.music_owner == "preview":
                self.execute("stop music")

    def set_preview_repeat(self, repeat):
        if type(repeat) is not bool:
            raise ValueError("Повтор должен быть bool")
        with self._lock:
            self.preview_repeat = repeat
        self._wake.set()

    def music_status(self):
        with self._lock:
            state = self.states["music"]
            position = state.position
            if state.key and state.started_at is not None:
                position += max(0, self.clock() - state.started_at)
            duration = self.catalog[state.key].duration if state.key else 0
            if self.music_owner != "preview" and duration:
                position %= duration
            return {"owner": self.music_owner, "key": state.key, "status": state.status,
                    "position": min(position, duration), "duration": duration,
                    "error": state.error or self._device_error, "repeat": self.preview_repeat}

    def reset(self):
        with self._lock:
            self.music_owner = None
            for state in self.states.values():
                state.key = None
                state.volume = 1.0
                state.serial += 1
                state.started_at = None
                state.position = 0
                state.fade = None
                state.paused = False
                state.status = "stopped"
                state.error = None
        self._wake.set()

    def snapshot(self):
        channels = {}
        with self._lock:
            now = self.clock()
            for channel, state in self.states.items():
                self._settle(channel, now)
                key = state.key if channel in LOOP_CHANNELS else None
                if channel == "music" and self.music_owner != "story":
                    key = None
                position = state.position
                if key and state.started_at is not None:
                    position += max(0, now - state.started_at)
                    position %= self.catalog[key].duration
                fade = None
                if key and state.fade:
                    kind, _, duration, anchor = state.fade
                    remaining = duration if anchor is None else max(0, duration - (now - anchor))
                    fade = {"kind": kind, "remaining": remaining, "level": self._envelope(state, now)}
                volume = 1.0 if channel == "music" and self.music_owner != "story" else state.volume
                channels[channel] = {"key": key, "volume": volume,
                                     "position": position if key and channel == "music" else 0.0, "fade": fade}
        return {"version": 1, "channels": channels}

    def validate_snapshot(self, data):
        if data is None:  # Legacy save: no audio reconstruction/replay.
            return None
        if (not isinstance(data, dict) or set(data) != {"version", "channels"}
                or type(data["version"]) is not int or data["version"] != 1
                or not isinstance(data["channels"], dict) or set(data["channels"]) != set(CHANNELS)):
            raise ValueError("Некорректная аудиосекция сохранения")
        result = {"version": 1, "channels": {}}
        for channel, item in data["channels"].items():
            if not isinstance(item, dict) or set(item) != {"key", "volume", "position", "fade"}:
                raise ValueError(f"Некорректное состояние аудиоканала {channel}")
            key = item["key"]
            if key is not None:
                if not isinstance(key, str) or channel not in LOOP_CHANNELS:
                    raise ValueError("Разовые эффекты нельзя восстанавливать из save")
                validate_audio_key(channel, key, self.catalog)
            volume = finite_number(item["volume"], maximum=1)
            position = finite_number(item["position"])
            if position and (not key or channel != "music" or position >= self.catalog[key].duration):
                raise ValueError(f"Некорректная аудиопозиция {channel}")
            fade = item["fade"]
            if fade is not None:
                if (not key or not isinstance(fade, dict) or set(fade) != {"kind", "remaining", "level"}
                        or fade["kind"] not in ("in", "out")):
                    raise ValueError("Некорректное затухание в save")
                remaining = finite_number(fade["remaining"])
                level = finite_number(fade["level"], maximum=1)
                if not remaining:
                    raise ValueError("Нулевая длительность затухания в save")
                fade = {"kind": fade["kind"], "remaining": remaining, "level": level}
            result["channels"][channel] = {"key": key, "volume": volume, "position": position, "fade": fade}
        return result

    def restore(self, data):
        validated = self.validate_snapshot(data)  # Atomic validation, before reset.
        with self._lock:
            self.reset()
            if validated is not None:
                self.music_owner = "story"
                for channel, item in validated["channels"].items():
                    state = self.states[channel]
                    state.key, state.volume, state.position = item["key"], item["volume"], item["position"]
                    state.status = "loading" if state.key else "stopped"
                    fade = item["fade"]
                    if fade:
                        state.fade = (fade["kind"], fade["level"], fade["remaining"], None)
                self._start()

    def drain_errors(self):
        errors = []
        while not self._errors.empty():
            errors.append(self._errors.get())
        return errors

    def _run(self):
        backend = None
        applied = {channel: -1 for channel in CHANNELS}
        music_paused = False
        try:
            try:
                backend = self.backend_factory()
            except Exception as exc:
                self._device_error = f"Звук недоступен, игра продолжится без аудио: {exc}"
                self._errors.put(self._device_error)
                backend = NullAudioBackend()
            while True:
                self._wake.clear()
                with self._lock:
                    if self._closed:
                        break
                for channel in CHANNELS:
                    with self._lock:
                        self._settle(channel, self.clock())
                        state = self.states[channel]
                        serial, key = state.serial, state.key
                        needs_play = applied[channel] != serial
                    prepared = None
                    try:
                        if needs_play and key:
                            path = resolve_audio_path(self.ts_dir / "sound", self.catalog[key])
                            if not path.is_file():
                                raise FileNotFoundError(f"Аудиофайл не найден: {path}")
                            prepared = backend.prepare(channel, path)  # Expensive decode without UI lock.
                            if channel == "music":
                                # Native music.load can also be slow. Do it without the UI lock,
                                # then recheck generation before starting the prepared stream.
                                backend.load_music(prepared)
                        with self._lock:
                            self._settle(channel, self.clock())
                            state = self.states[channel]
                            if self._closed or state.serial != serial:
                                backend.discard(prepared)
                                continue
                            if needs_play:
                                if key:
                                    if channel == "music" and self.music_owner == "preview" and self._device_error:
                                        raise RuntimeError(self._device_error)
                                    loop = channel in LOOP_CHANNELS and not (channel == "music" and self.music_owner == "preview")
                                    position = backend.play(channel, prepared, loop,
                                                            self._gain(channel, self.clock()), state.position)
                                    if channel == "music" and position != state.position:
                                        self._errors.put("Позиция музыки не поддержана: трек начат сначала")
                                    state.position = position
                                    state.started_at = None if state.paused else self.clock()
                                    state.status = "paused" if state.paused else "playing"
                                    if channel == "music":
                                        music_paused = False
                                    if state.fade and state.fade[3] is None:
                                        kind, level, duration, _ = state.fade
                                        state.fade = (kind, level, duration, state.started_at)
                                else:
                                    backend.stop(channel)
                                applied[channel] = serial
                            if channel == "music" and key:
                                if state.paused != music_paused:
                                    if state.paused:
                                        backend.pause_music()
                                    else:
                                        backend.resume_music()
                                    music_paused = state.paused
                                # get_busy is false both at EOF and on pause: never confuse them.
                                if self.music_owner == "preview" and not state.paused and not backend.music_busy():
                                    state.serial += 1
                                    state.started_at = None
                                    state.position = 0
                                    if self.preview_repeat:
                                        state.status = "loading"
                                    else:
                                        state.key = None
                                        state.status = "stopped"
                            backend.volume(channel, self._gain(channel, self.clock()))
                    except Exception as exc:
                        backend.discard(prepared)
                        self._errors.put(f"Ошибка аудио ({channel}, {key}): {exc}")
                        with self._lock:
                            if self.states[channel].serial == serial:
                                self.states[channel].key = None
                                self.states[channel].serial += 1
                                self.states[channel].fade = None
                                self.states[channel].started_at = None
                                self.states[channel].position = 0
                                self.states[channel].paused = False
                                self.states[channel].status = "error"
                                self.states[channel].error = str(exc)
                        # A failing replacement must not leave the old track playing.
                        try:
                            backend.stop(channel)
                        except Exception:
                            backend.close()
                            backend = NullAudioBackend()
                            applied = {name: -1 for name in CHANNELS}
                backend.trim()
                self._wake.wait(0.025)
        except Exception as exc:
            self._errors.put(f"Аудиодвижок остановлен: {exc}")
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception as exc:
                    self._errors.put(f"Ошибка закрытия аудиодвижка: {exc}")

    def close(self):
        with self._lock:
            self._closed = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
