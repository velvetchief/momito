# Momito

[![tests](https://github.com/velvetchief/momito/actions/workflows/tests.yml/badge.svg)](https://github.com/velvetchief/momito/actions/workflows/tests.yml)

Hold **Right Option** anywhere on your Mac, talk, release. Your words get typed
into whatever app has focus, like Wispr Flow or FluidVoice, except everything
runs on your own machine. Transcription is NVIDIA Parakeet TDT v2 running
locally on Apple silicon via MLX: free, offline, nothing leaves the Mac.

Momito lives in the menu bar as a small schnauzer, with a badge for what it is
doing right now:

- ⏳ loading the model (a minute or two after launch, longer the first time)
- no badge: ready, hold Right Option to dictate
- 🔴 listening
- ✍️ transcribing and typing
- ⚠️ the model failed to load; click the menu item to retry

While you hold the key, a small pill appears near the bottom of the screen so
you can see you are being recorded without looking at the menu bar, and a soft
tone plays on start and on release. Press **Esc** while still holding Right
Option to throw the recording away: nothing is transcribed, nothing is pasted.

The menu shows the last thing it typed, and **Paste Last Transcription** puts
it back on the clipboard and into the focused field, for when your click landed
in the wrong window.

## The dashboard

Click the menu bar icon and choose **Open Momito**. A native window opens, like
FluidVoice's, with three views:

- **History**: everything you have dictated, searchable, with the app each one
  was typed into, when, word and character counts, and how long you spoke.
  Delete single entries, or Clear All (it asks first).
- **Dictionary**: spoken-form to written-form rules, applied to every
  transcript before it is pasted. Say "mo mito", get "Momito". Matching is
  whole-word and case-insensitive, a leading capital in your speech is carried
  over to the replacement, and each rule is applied to the original text only,
  so rules cannot chain into each other.
- **Stats**: dictations and words today, all-time totals, minutes of talking.

History is stored locally in
`~/Library/Application Support/Momito/history.db`, created with owner-only
permissions, and never leaves the Mac.

Under the hood the window is a WebView onto a small HTTP server bound to
127.0.0.1. Loopback is not a security boundary on a shared machine, so the
server also requires a per-launch secret token on every request, and rejects
requests whose `Host` or `Origin` header is not its own. That is what stops a
web page you happen to have open from reading your transcripts or quietly
adding a dictionary rule. The token lives in
`~/Library/Application Support/Momito/instance.json` (owner-only), which is
also how a second launch finds the running copy instead of starting a duplicate.

Momito stays out of the Dock while you dictate; it appears in the Dock (with
the schnauzer icon) only while the dashboard window is open.

## Requirements

- A Mac with Apple silicon (M1 or later). MLX runs on the Apple GPU, so Intel
  Macs are out.
- macOS 13 or later and the Xcode Command Line Tools
  (`xcode-select --install`) for the compiled launcher.
- Python 3.11 or later, installed as a shared library, which the Homebrew and
  python.org builds both are. Momito is developed and tested on 3.14; earlier
  versions should work but are not exercised in CI.
- About 2.3 GB of disk for the model, downloaded once on first launch, and
  another 700 MB or so for the Python packages.

## Install (once)

Momito installs from source. There is no signed disk image, because notarizing
a Mac app means paying Apple $99 a year, and this is a free tool. That is the
only reason: the build itself is a two-line script.

```bash
git clone https://github.com/velvetchief/momito.git
cd momito
./install.sh
```

That sets up the Python environment and puts **Momito.app** in /Applications.
Add `--login` to also start Momito automatically when you log in.

Momito.app is a thin launcher that runs the code in this folder, so keep the
folder where it is (rerun `./install.sh` if you move it). The launcher is a
tiny native binary rather than a shell script so macOS sees the app as Momito,
not Python: schnauzer icon in the Dock, "Momito" in the menu bar, and
permissions that attach to Momito by name.

macOS permissions, one-time, granted to "Momito":

1. **Microphone**: macOS asks on your first dictation.
2. **Accessibility**: System Settings > Privacy & Security > Accessibility >
   enable Momito. Needed for both the global hotkey and the paste keystroke.
   Momito notices the moment you flip the switch, so you should not have to
   restart it.

Permission grants are tied to the app's code signature. Reinstalling only
replaces the installed app when the build actually changed, and when it does,
the installer clears the stale Accessibility row and tells you to re-enable it.

## Run

Open **Momito** from /Applications (or Spotlight). Click into any text field,
hold Right Option, say something, release. The text pastes in with punctuation
and capitalization handled by the model.

For development you can run it straight from the terminal:

```bash
.venv/bin/python run.py
```

## How the text lands, and what that costs you

Momito has no way to type text directly into another app, so it uses the
clipboard: it snapshots what is there, writes the transcript, sends Cmd-V, and
puts the old contents back 0.6 seconds later. Be aware of what that means:

- For roughly 0.7 seconds your transcript is on the system clipboard, where any
  running app can read it. If you use a clipboard manager, it will keep your
  dictations in its own history, and clearing Momito's history does not touch
  that.
- The snapshot and restore covers every type on the pasteboard, not just text,
  so copied images and rich text survive. Contents that an app only *promises*
  lazily (some apps write a placeholder and produce the real data on demand)
  cannot be captured, and are lost.
- Only one dictation touches the clipboard at a time; the paste path is
  serialized so two transcripts cannot interleave.

## Tests

Tests go in their own environment, not `.venv`. The app's venv runs with
Accessibility and Microphone granted, and test tooling has no business in that
blast radius.

```bash
python3 -m venv .venv-dev
.venv-dev/bin/pip install -r requirements-dev.txt
.venv-dev/bin/python -m pytest
.venv-dev/bin/python -m mypy momito tests conftest.py run.py
```

100 tests. The same two commands run on every push and pull request, on an
Apple silicon runner, via `.github/workflows/tests.yml`.

Covered: the dictation pipeline (min-length gate, whitespace, paste rules,
dictionary replacement including no-chaining and longest-match-first), the
history store (add, search, delete, clear, stats math, schema migration), the
clipboard paste path against a fake pasteboard, the state machine, the
instance file, and the dashboard server's auth (missing token, wrong Host,
cross-origin, malformed and oversized bodies).

Not covered by automation: the model itself, live mic capture, and the real
paste keystroke. Those need a microphone, a GPU, and a human, and are checked
by hand.

Development dependencies live in `requirements-dev.txt` and are deliberately
kept out of the venv the installed app runs from.

## Licensing

Momito is Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Two things worth knowing before you build on it:

- The speech model, NVIDIA Parakeet TDT 0.6B v2, is CC-BY-4.0. Commercial use
  is fine, attribution is required. It is downloaded at a pinned revision, not
  bundled here.
- `pynput`, which provides the global hotkey, is LGPL-3.0. Importing it as an
  unmodified library from PyPI does not put Momito's own code under the LGPL.
  Bundling a *modified* pynput into a binary you distribute does bring
  obligations with it.

Everything else in the dependency tree is MIT, BSD, or Apache. The full list is
in NOTICE.

## What happened to the voice commander?

This app's predecessor, Shiva (Grok Voice Think Fast 2.0 agent orchestrator),
is preserved in `archive/voice-commander/`, self-contained, with a note on how
to run it.
