"""16 kHz mono microphone capture, the rate Parakeet expects."""

import threading
from typing import Any, List, Optional

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK_FRAMES = 1600  # 100 ms


class Recorder:
    def __init__(self) -> None:
        self._frames: List[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._frames = []
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=BLOCK_FRAMES,
                callback=self._on_block,
            )
            self._stream.start()

    def _on_block(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        self._frames.append(indata[:, 0].copy())

    def stop(self) -> np.ndarray:
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            frames, self._frames = self._frames, []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames)
