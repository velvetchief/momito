"""Transcriber tests. A stub model stands in for the 2.3 GB Parakeet weights;
the preprocessing in front of it is the real parakeet-mlx code."""

import shutil
import unittest
from unittest import mock

import numpy as np
from parakeet_mlx.audio import PreprocessArgs

from momito.asr import SAMPLE_RATE, Transcriber

# The preprocessor settings Parakeet TDT v2 ships in its config.json. Spelled
# out here so the test exercises get_logmel with the shapes production sees.
PREPROCESS = PreprocessArgs(
    sample_rate=SAMPLE_RATE,
    normalize="per_feature",
    window_size=0.025,
    window_stride=0.01,
    window="hann",
    features=128,
    n_fft=512,
    dither=1e-5,
)


class StubResult:
    def __init__(self, text: str) -> None:
        self.text = text


class StubModel:
    """Records the mel it receives and returns a canned transcript."""

    def __init__(self, text: str = "hello world") -> None:
        self.preprocessor_config = PREPROCESS
        self.mels: list = []
        self._text = text

    def generate(self, mel):
        self.mels.append(mel)
        return [StubResult(self._text)]


def transcriber_with(model: StubModel) -> Transcriber:
    t = Transcriber()
    t._model = model
    return t


class TranscriberTest(unittest.TestCase):
    def test_transcribes_without_ffmpeg_installed(self):
        """The launch-blocking bug: parakeet-mlx's own transcribe() shells out
        to ffmpeg, which fresh Macs do not have and Finder-launched apps cannot
        find on PATH even when installed. Momito must never need it."""
        model = StubModel("no ffmpeg here")
        with mock.patch.object(shutil, "which", return_value=None):
            out = transcriber_with(model).transcribe(
                np.zeros(SAMPLE_RATE, dtype=np.float32)
            )
        self.assertEqual(out, "no ffmpeg here")

    def test_mel_shape_matches_preprocessor_config(self):
        model = StubModel()
        transcriber_with(model).transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
        (mel,) = model.mels
        # [batch, frames, mel bins]; one second at a 10 ms hop is ~100 frames.
        self.assertEqual(mel.shape[0], 1)
        self.assertEqual(mel.shape[2], PREPROCESS.features)
        self.assertAlmostEqual(mel.shape[1], 100, delta=2)

    def test_int16_style_input_is_coerced_to_float32(self):
        model = StubModel()
        audio = (np.random.default_rng(0).standard_normal(SAMPLE_RATE) * 1000).astype(
            np.int16
        )
        out = transcriber_with(model).transcribe(audio)
        self.assertEqual(out, "hello world")

    def test_load_is_skipped_when_model_present(self):
        """transcribe() on a loaded Transcriber must not re-download anything."""
        model = StubModel()
        t = transcriber_with(model)
        with mock.patch.object(t, "_model_source", side_effect=AssertionError):
            t.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
