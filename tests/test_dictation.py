"""Dictation pipeline tests. Pure logic, no mic, no model, no keystrokes."""

import unittest

import numpy as np

from momito.dictation import Dictation, apply_replacements

RATE = 16000


def audio(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds), dtype=np.float32)


class DictationTest(unittest.TestCase):
    def setUp(self):
        self.pasted = []
        self.transcripts = []

    def make(self, transcript: str) -> Dictation:
        def transcribe(a: np.ndarray) -> str:
            self.transcripts.append(a)
            return transcript

        return Dictation(transcribe, self.pasted.append, sample_rate=RATE)

    def test_transcribes_and_pastes_with_trailing_space(self):
        out = self.make("Hello there.").handle(audio(1.0))
        self.assertEqual(out, "Hello there. ")
        self.assertEqual(self.pasted, ["Hello there. "])

    def test_strips_surrounding_whitespace(self):
        out = self.make("  padded text \n").handle(audio(1.0))
        self.assertEqual(out, "padded text ")

    def test_too_short_recording_is_ignored(self):
        out = self.make("should never run").handle(audio(0.1))
        self.assertIsNone(out)
        self.assertEqual(self.transcripts, [])
        self.assertEqual(self.pasted, [])

    def test_empty_transcript_is_not_pasted(self):
        out = self.make("   ").handle(audio(1.0))
        self.assertIsNone(out)
        self.assertEqual(self.pasted, [])

    def test_no_double_trailing_space(self):
        out = self.make("already spaced ").handle(audio(1.0))
        self.assertEqual(out, "already spaced ")

    def test_trailing_space_can_be_disabled(self):
        d = Dictation(lambda a: "no space", self.pasted.append, trailing_space=False)
        self.assertEqual(d.handle(audio(1.0)), "no space")

    def test_replacements_applied_before_paste(self):
        d = Dictation(
            lambda a: "email mo mito about it",
            self.pasted.append,
            sample_rate=RATE,
            replacements=lambda: [("mo mito", "Momito")],
        )
        self.assertEqual(d.handle(audio(1.0)), "email Momito about it ")
        self.assertEqual(self.pasted, ["email Momito about it "])

    def test_broken_replacements_source_does_not_break_dictation(self):
        def boom():
            raise RuntimeError("db is on fire")

        d = Dictation(lambda a: "still works", self.pasted.append, replacements=boom)
        self.assertEqual(d.handle(audio(1.0)), "still works ")


class ApplyReplacementsTest(unittest.TestCase):
    def test_whole_word_only(self):
        out = apply_replacements("the cat saw a catalog", [("cat", "dog")])
        self.assertEqual(out, "the dog saw a catalog")

    def test_case_insensitive_match(self):
        out = apply_replacements("KUBERNETES is hard", [("kubernetes", "Kubernetes")])
        self.assertEqual(out, "Kubernetes is hard")

    def test_sentence_capital_is_preserved(self):
        out = apply_replacements("Teh thing is teh same.", [("teh", "the")])
        self.assertEqual(out, "The thing is the same.")

    def test_multiword_phrase(self):
        out = apply_replacements("ping wisper flow now", [("wisper flow", "Wispr Flow")])
        self.assertEqual(out, "ping Wispr Flow now")

    def test_punctuation_boundary(self):
        out = apply_replacements("Is it teh?", [("teh", "the")])
        self.assertEqual(out, "Is it the?")

    def test_blank_spoken_side_is_skipped(self):
        out = apply_replacements("unchanged text", [("  ", "boom")])
        self.assertEqual(out, "unchanged text")

    def test_no_pairs_is_identity(self):
        self.assertEqual(apply_replacements("hello", []), "hello")

    def test_rules_do_not_chain(self):
        """cat -> dog and dog -> wolf must not turn a spoken cat into a wolf.
        Every rule sees the original text, never another rule's output."""
        out = apply_replacements("cat dog", [("cat", "dog"), ("dog", "wolf")])
        self.assertEqual(out, "dog wolf")

    def test_a_rule_that_reintroduces_its_own_trigger_terminates(self):
        out = apply_replacements("teh teh", [("teh", "teh the")])
        self.assertEqual(out, "teh the teh the")

    def test_longest_match_wins(self):
        pairs = [("mito", "Mito"), ("mo mito", "Momito")]
        self.assertEqual(apply_replacements("call mo mito now", pairs), "call Momito now")

    def test_first_rule_wins_on_duplicates(self):
        pairs = [("teh", "the"), ("TEH", "THE")]
        self.assertEqual(apply_replacements("teh thing", pairs), "the thing")

    def test_regex_characters_are_literal(self):
        out = apply_replacements("what a c++ mess", [("c++", "C++")])
        self.assertEqual(out, "what a C++ mess")

    def test_identity_rule_changes_nothing(self):
        out = apply_replacements("say teh", [("teh", "teh")])
        self.assertEqual(out, "say teh")


if __name__ == "__main__":
    unittest.main()
