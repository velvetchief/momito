"""Menu bar app: hold Right Option anywhere, speak, release, text appears."""

import atexit
import queue
import threading
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import rumps
from AppKit import NSSound, NSWorkspace
from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)
from pynput import keyboard

from . import instance, state as state_mod
from .asr import Transcriber
from .dictation import Dictation
from .history import History
from .overlay import RecordingOverlay
from .paste import paste_text
from .recorder import SAMPLE_RATE, Recorder
from .server import TOKEN_HEADER, DashboardServer
from .state import AppState
from .window import DashboardWindow, setup_app_identity

PTT_KEY = keyboard.Key.alt_r

# monochrome schnauzer template icon; the title only carries transient state
ASSETS = Path(__file__).parent.parent / "assets"
MENUBAR_ICON = ASSETS / "menubar-template.png"
TITLES = {
    state_mod.LOADING: "⏳",
    state_mod.IDLE: "",
    state_mod.REC: "🔴",
    state_mod.BUSY: "✍️",
    state_mod.ERROR: "⚠️",
}

def _load_cue(name: str) -> Optional[Any]:
    """Preload a short wav so playback is instant when it is asked for."""
    path = ASSETS / name
    if not path.exists():
        return None
    sound = NSSound.alloc().initWithContentsOfFile_byReference_(str(path), True)
    if sound is not None:
        sound.setVolume_(0.35)
    return sound


def _play(sound: Optional[Any]) -> None:
    if sound is None:
        return
    try:
        sound.stop()  # rewind if a previous play is still going
        sound.play()
    except Exception:
        pass  # a missing cue must never break dictation


Job = Tuple[np.ndarray, str]


def _frontmost_app() -> str:
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.localizedName()) if app else ""
    except Exception:
        return ""


class MomitoApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(
            "Momito",
            icon=str(MENUBAR_ICON) if MENUBAR_ICON.exists() else None,
            template=True,
            quit_button="Quit Momito",
        )
        setup_app_identity()
        if not AXIsProcessTrusted():
            # registers "Momito" in System Settings > Accessibility and asks the user
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        self.status_item = rumps.MenuItem("Loading Parakeet…")
        self.open_item = rumps.MenuItem("Open Momito", callback=self._open_dashboard)
        self.paste_item = rumps.MenuItem("Paste Last Transcription", callback=self._paste_last)
        self.menu = [self.open_item, self.paste_item, self.status_item]
        self.state = AppState()
        self._status_clickable = False
        self.last_text = ""
        self.last_pasted = ""  # only successful dictations, never error strings
        self.recorder = Recorder()
        self.transcriber = Transcriber()
        self.history = History()
        self.dictation = Dictation(
            self.transcriber.transcribe,
            paste_text,
            sample_rate=SAMPLE_RATE,
            replacements=self.history.replacement_pairs,
        )
        self.overlay = RecordingOverlay()
        self.cue_start = _load_cue("cue-start.wav")
        self.cue_stop = _load_cue("cue-stop.wav")
        self.cues: "queue.Queue[Any]" = queue.Queue()
        threading.Thread(target=self._cue_worker, daemon=True).start()
        self.server: Optional[DashboardServer] = None
        self.window: Optional[DashboardWindow] = None
        try:
            self.server = DashboardServer(self.history, self._status, on_open=self._open_async)
            self.server.start()
            # tell the next launch where to find us, port and token both
            instance.write(self.server.port, self.server.token)
            atexit.register(instance.clear)
            self.window = DashboardWindow(self.server.url)
            if not self.window.install_reopen_handler():
                # the dashboard still opens from the menu bar; only the
                # click-the-Dock-icon shortcut is gone. Say so rather than
                # letting the feature die silently on a rumps upgrade.
                print("momito: could not install the reopen handler; "
                      "opening Momito.app again will not show the dashboard")
        except Exception as exc:
            print(f"momito: dashboard unavailable: {exc}")
            self.server = None
        self.jobs: "queue.Queue[Optional[Job]]" = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        self._listener_trusted = bool(AXIsProcessTrusted())
        rumps.Timer(self._refresh, 0.2).start()
        if not self._listener_trusted:
            self._trust_timer = rumps.Timer(self._watch_trust, 2)
            self._trust_timer.start()

    def _open_async(self) -> None:
        if self.window:
            self.window.show_async()

    def _watch_trust(self, timer: Any) -> None:
        """A hotkey listener started before the Accessibility grant gets a dead
        event tap; restart it the moment the grant lands so the user does not
        have to quit and reopen."""
        if not AXIsProcessTrusted():
            return
        timer.stop()
        if not self._listener_trusted:
            self._listener.stop()
            self._listener = keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release
            )
            self._listener.start()
            self._listener_trusted = True

    def _status(self) -> dict:
        return {
            "app": "momito",
            "state": self.state.label,
            "model_ready": self.state.ready,
            "error": self.state.error,
            "last_text": self.last_text,
            "trusted": bool(AXIsProcessTrusted()),
        }

    def _open_dashboard(self, _item: Any) -> None:
        if self.window:
            self.window.show()

    def _paste_last(self, _item: Any) -> None:
        """Clicking the menu bar does not switch apps, so Cmd-V still lands in
        the field that had focus. paste_text blocks ~0.7s restoring the
        clipboard, so run it off the menu (main) thread."""
        text = self.last_pasted
        if not text:
            return
        threading.Thread(target=paste_text, args=(text + " ",), daemon=True).start()

    def _retry_model(self, _item: Any) -> None:
        self.jobs.put(None)  # None on the job queue means "reload the model"

    # --- cue thread: decoding and starting playback is not the hotkey's job ---

    def _cue_worker(self) -> None:
        while True:
            _play(self.cues.get())

    def _cue(self, sound: Optional[Any]) -> None:
        if sound is not None:
            self.cues.put(sound)

    # --- pynput thread ---

    def _on_press(self, key: Any) -> None:
        if key == PTT_KEY:
            if not self.state.start_recording():
                return  # already recording, or the model is broken
            try:
                # the recorder only opens a stream, which is fast; doing it here
                # rather than on a worker keeps press-to-capture immediate
                self.recorder.start()
                self._cue(self.cue_start)
            except Exception as exc:
                self.state.stop_recording()
                self.last_text = f"mic error: {exc}"
        elif key == keyboard.Key.esc and self.state.recording:
            # cancel: throw the audio away, paste nothing, no stop cue
            if self.state.stop_recording():
                try:
                    self.recorder.stop()
                except Exception:
                    pass

    def _on_release(self, key: Any) -> None:
        if key == PTT_KEY and self.state.stop_recording():
            audio = self.recorder.stop()
            self.state.job_queued()
            self._cue(self.cue_stop)
            self.jobs.put((audio, _frontmost_app()))

    # --- worker thread: model load, then one job at a time ---

    def _load_model(self) -> None:
        self.state.model_loading()
        try:
            self.transcriber.load()
        except Exception as exc:
            # a failed load must show as failed: reporting ready would send
            # every dictation into a retry that re-downloads gigabytes
            self.state.model_failed(str(exc))
            self.last_text = f"model failed to load: {exc}"
            return
        self.state.model_loaded()

    def _worker(self) -> None:
        self._load_model()
        while True:
            job = self.jobs.get()
            if job is None:  # the retry sentinel; not a dictation, so no job_done
                self._load_model()
                continue
            audio, app_name = job
            try:
                text = self.dictation.handle(audio)
                if text:
                    self.last_text = text.strip()
                    self.last_pasted = self.last_text
                    try:
                        self.history.add(
                            self.last_text, app_name, seconds=len(audio) / SAMPLE_RATE
                        )
                    except Exception:
                        pass  # history must never break dictation
            except Exception as exc:
                self.last_text = f"error: {exc}"
            finally:
                self.state.job_done()

    # --- main thread: menu bar refresh ---

    def _refresh(self, _timer: Any) -> None:
        label = self.state.label
        self.title = TITLES.get(label, "🎙")
        try:
            self.overlay.update(label)
        except Exception:
            pass  # the pill is decoration; never let it kill the refresh timer
        if label == state_mod.ERROR:
            self.status_item.title = "Model failed. Click to retry."
            self._set_status_clickable(True)
            return
        self._set_status_clickable(False)
        if label == state_mod.LOADING:
            self.status_item.title = "Loading Parakeet…"
        elif self.last_text:
            self.status_item.title = f"Last: {self.last_text[:60]}"
        else:
            self.status_item.title = "Hold Right Option to dictate"

    def _set_status_clickable(self, clickable: bool) -> None:
        if clickable == self._status_clickable:
            return
        self.status_item.set_callback(self._retry_model if clickable else None)
        self._status_clickable = clickable


def _hand_off_to_running_instance() -> bool:
    """If another Momito is already up, ask it to show its window and bow out."""
    import json
    import urllib.request

    running = instance.read()
    if not running:
        return False
    base = f"http://127.0.0.1:{running['port']}"
    headers = {TOKEN_HEADER: running["token"]}
    try:
        req = urllib.request.Request(f"{base}/api/status", headers=headers)
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            data = json.load(resp)
        if data.get("app") != "momito":
            return False  # port recycled by something else since we wrote the file
        opener = urllib.request.Request(
            f"{base}/api/open", data=b"{}", headers=headers, method="POST"
        )
        urllib.request.urlopen(opener, timeout=2)
        return True
    except Exception:
        return False  # stale file, or nothing listening: we are the instance


def main() -> None:
    if _hand_off_to_running_instance():
        return
    MomitoApp().run()
