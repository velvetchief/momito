"""The dictation pipeline glue: audio in, text pasted out. No hardware, testable."""

import re
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

Replacements = Sequence[Tuple[str, str]]


def apply_replacements(text: str, pairs: Replacements) -> str:
    """Apply the user's dictionary: whole-word, case-insensitive substitution.

    Every rule is checked in a single pass, so a rule never rewrites what
    another rule just produced. Applying them one at a time meant cat->dog and
    dog->wolf turned "cat" into "wolf", which is not what either rule says.
    Longer spoken forms are tried first, so "mo mito" wins over "mito".

    If the matched word was capitalized (say, at the start of a sentence) and
    the replacement is all lowercase, the capital carries over.
    """
    lookup: dict = {}
    for spoken, written in pairs:
        spoken = spoken.strip()
        if spoken:
            lookup.setdefault(spoken.lower(), (spoken, written))  # first rule wins
    if not lookup:
        return text

    forms = sorted((v[0] for v in lookup.values()), key=len, reverse=True)
    pattern = re.compile(
        "|".join(r"(?<!\w)" + re.escape(form) + r"(?!\w)" for form in forms),
        re.IGNORECASE,
    )

    def _sub(match: "re.Match[str]") -> str:
        matched = match.group(0)
        written = lookup[matched.lower()][1]
        if matched[:1].isupper() and written[:1].islower():
            return written[:1].upper() + written[1:]
        return written

    return pattern.sub(_sub, text)


class Dictation:
    def __init__(
        self,
        transcribe: Callable[[np.ndarray], str],
        paste: Callable[[str], None],
        sample_rate: int = 16000,
        min_seconds: float = 0.25,
        trailing_space: bool = True,
        replacements: Optional[Callable[[], List[Tuple[str, str]]]] = None,
    ) -> None:
        self.transcribe = transcribe
        self.paste = paste
        self.sample_rate = sample_rate
        self.min_seconds = min_seconds
        self.trailing_space = trailing_space
        self.replacements = replacements

    def handle(self, audio: np.ndarray) -> Optional[str]:
        """Transcribe a finished recording and paste it. Returns the pasted text, or None."""
        if audio.size < int(self.min_seconds * self.sample_rate):
            return None
        text = self.transcribe(audio).strip()
        if not text:
            return None
        if self.replacements is not None:
            try:
                text = apply_replacements(text, self.replacements()).strip()
            except Exception:
                pass  # a broken dictionary must never eat a dictation
            if not text:
                return None
        if self.trailing_space and not text.endswith(" "):
            text += " "
        self.paste(text)
        return text
