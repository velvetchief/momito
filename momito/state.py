"""Single owner for the app's visible state.

Three threads touch this: the hotkey listener (press and release), the
transcription worker, and the main-thread timer that draws the menu bar title
and the recording pill. Without one owner they race: the worker finishing a job
would stamp "idle" over a recording that started a millisecond earlier, and the
pill would vanish mid-sentence.

Nothing here knows about AppKit, so it is fully testable.
"""

import threading

LOADING = "loading"
IDLE = "idle"
REC = "rec"
BUSY = "busy"
ERROR = "error"


class AppState:
    """Every mutation takes the lock; `label` is the one thing the UI reads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recording = False
        self._jobs = 0
        self._ready = False
        self._error = ""

    # --- recording ---

    def start_recording(self) -> bool:
        """Claim the microphone. False means someone else already has it, or
        the model is broken and there is nothing to transcribe with."""
        with self._lock:
            if self._recording or self._error:
                return False
            self._recording = True
            return True

    def stop_recording(self) -> bool:
        """Release the microphone. False means we were not recording, so the
        caller should not touch the audio device or queue a job."""
        with self._lock:
            if not self._recording:
                return False
            self._recording = False
            return True

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._recording

    # --- transcription jobs ---

    def job_queued(self) -> None:
        with self._lock:
            self._jobs += 1

    def job_done(self) -> None:
        with self._lock:
            self._jobs = max(0, self._jobs - 1)

    @property
    def jobs(self) -> int:
        with self._lock:
            return self._jobs

    # --- model ---

    def model_loaded(self) -> None:
        with self._lock:
            self._ready = True
            self._error = ""

    def model_failed(self, message: str) -> None:
        with self._lock:
            self._ready = False
            self._error = message or "unknown error"

    def model_loading(self) -> None:
        """Back to the loading state for a retry."""
        with self._lock:
            self._ready = False
            self._error = ""

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._ready

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    # --- what everything renders ---

    @property
    def label(self) -> str:
        with self._lock:
            if self._error:
                return ERROR
            if self._recording:
                return REC
            if self._jobs:
                return BUSY
            if not self._ready:
                return LOADING
            return IDLE
