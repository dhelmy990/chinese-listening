# Live Chinese with Whisper

A small localhost experiment: microphone → local Whisper → Chinese text.
The default is **full large-v3**, using faster-whisper on the **CPU with INT8**
weights at runtime. No transcription API, account, or API key is needed.

## Run

From this folder (Python 3.10+):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Or with `uv`: `uv venv && uv pip install -r requirements.txt`.

Open **http://localhost:8765** in Chrome, wait for “Ready”, click **Start microphone**,
and grant microphone access. Speak Mandarin; pause briefly between sentences.
Click **Stop** to release the microphone and finish the remaining text.
Starting again clears the previous transcript. Ctrl+C in the terminal stops the server.

All provisional and final text is converted locally to **Simplified Chinese**
using [OpenCC](https://github.com/yichen0831/opencc-python) (`t2s`).
Use the dropdown beside “Whisper” to switch between **Large-v3** and **Turbo**.
Stop recording and let queued speech finish before switching. The selector is
disabled during recording or loading. Existing text stays visible until you start again.
Only one model is kept in memory; switching loads the selected model from disk.

First startup downloads roughly 3 GB of model weights into `.models/`; later runs
reuse them. Audio and transcripts stay in memory and are not saved or uploaded.
Turbo also downloads its weights once on first selection. Model downloads require
internet. Recognition and script conversion run locally after setup.

## Read or change the code

- `server.py`: model loading, phrase boundaries, and recognition. Change
  `PARTIAL_SECONDS` (2), `PAUSE_SECONDS` (0.7), `MAX_SECONDS` (15), or
  `VOICE_THRESHOLD` (0.008) at the top. `transcribe()` sets Mandarin (`zh`),
  transcription rather than translation, and greedy decoding (`beam_size=1`).
- `mic.js`: microphone audio capture at 16 kHz, mono float32.
- `index.html`: Start/Stop, Chinese text, microphone meter, and timing.

Whisper does not natively stream individual words. This demo re-transcribes the
current phrase every two seconds when the model is free. Gray hypotheses are
replaced, not appended. A pause finalizes the phrase; continuous speech splits
at about 15 seconds, which can cut words at that boundary. The initial pause
detector uses audio energy, so background noise may delay finalization.
Whisper's speech VAD additionally filters silent snapshots before inference.

Only one microphone session and one inference run are accepted at a time.
Old pending partials are replaced by newer snapshots; final phrases are retained.
If eight phrases accumulate, the session reports overload rather than dropping
audio silently. Stop lets queued inference finish, so it can take a while.

## Understand the timings

- **Audio**: duration of the snapshot, including any pauses.
- **Processing**: model/VAD time, excluding queueing and initial model load.
- **Result delay**: time since the server received the end of that snapshot,
  including queueing and processing; excludes speech collection and browser/network delay.
- **Processing/audio**: real-time factor for that snapshot. Less than 1 is faster
  than its audio duration. Repeated overlapping partials add work, so this alone
  does not prove the live session can keep up. Watch whether result delay grows.

These are laptop **CPU** measurements, not phone or AMD GPU performance.
Accuracy depends on your speech and room. Check silence and background noise too.

To start with Turbo already selected:

```sh
.venv/bin/python server.py --model turbo
```

For CPU tuning: `--threads 4` or `--threads 8`.

## Checks

```sh
.venv/bin/python -m unittest test_server.py
```

The checks exercise phrase buffering, Simplified Chinese output, model switching,
busy/loading guards, and recovery after loading fails. Model-loading tests use a
stub to avoid downloads. They do not measure recognition accuracy.
