"""Generate the dictation sound cues: a soft rising blip when recording starts
(assets/cue-start.wav) and a falling one when it stops (assets/cue-stop.wav).

    .venv/bin/python scripts/make_sounds.py
"""

from pathlib import Path

import numpy as np
import soundfile as sf

ASSETS = Path(__file__).resolve().parent.parent / "assets"
RATE = 44100


def tone(freq: float, dur: float, amp: float = 0.2) -> np.ndarray:
    t = np.linspace(0.0, dur, int(RATE * dur), endpoint=False)
    envelope = np.sin(np.pi * t / dur) ** 2  # smooth fade in and out, no clicks
    return (amp * envelope * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def main() -> None:
    start = np.concatenate([tone(587.33, 0.07), tone(880.0, 0.09)])  # D5 -> A5
    stop = np.concatenate([tone(880.0, 0.07), tone(587.33, 0.09)])  # A5 -> D5
    sf.write(str(ASSETS / "cue-start.wav"), start, RATE)
    sf.write(str(ASSETS / "cue-stop.wav"), stop, RATE)
    print(f"wrote {ASSETS / 'cue-start.wav'} and {ASSETS / 'cue-stop.wav'}")


if __name__ == "__main__":
    main()
