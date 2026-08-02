"""Parakeet TDT v2 wrapper via parakeet-mlx. Fully local, nothing leaves the Mac."""

import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf

MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v2"
# Pinned so an upstream repo edit cannot silently swap the weights that run on
# every dictation. Bump this deliberately, never by accident.
MODEL_REVISION = "8ae155301e23d820d82aa60d24817c900e69e487"
MODEL_FILES = ("config.json", "model.safetensors")
SAMPLE_RATE = 16000


class Transcriber:
    def __init__(self, model_id: str = MODEL_ID, revision: Optional[str] = MODEL_REVISION) -> None:
        self.model_id = model_id
        self.revision = revision
        self._model: Optional[Any] = None

    def load(self) -> None:
        """Load the model and run a warmup pass so the first real dictation is fast."""
        if self._model is not None:
            return
        from parakeet_mlx import from_pretrained

        self._model = from_pretrained(self._model_source())
        self._transcribe_array(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))

    def _model_source(self) -> str:
        """A repo id, or a local snapshot directory when we are pinning.

        parakeet-mlx's `from_pretrained` takes no revision argument, so the only
        place a pin can live is here: fetch the exact commit ourselves and hand
        it the resulting directory, which it loads from disk.
        """
        if not self.revision:
            return self.model_id
        from huggingface_hub import hf_hub_download

        paths = [
            hf_hub_download(self.model_id, name, revision=self.revision)
            for name in MODEL_FILES
        ]
        return str(Path(paths[0]).parent)

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        return self._transcribe_array(audio)

    def _transcribe_array(self, audio: np.ndarray) -> str:
        # parakeet-mlx takes a file path; hand it a throwaway wav.
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            sf.write(path, audio, SAMPLE_RATE)
            assert self._model is not None
            result = self._model.transcribe(path)
            return str(result.text)
        finally:
            os.unlink(path)
