# Chinese listening with Whisper

A small localhost experiment: microphone → local Whisper → Chinese text → local OPUS-MT → English.
The default is **full large-v3**, using faster-whisper on the **CPU with INT8**
at runtime. Both the model and representation can be changed in the page.
No transcription API, account, or API key is needed.

## Run

From the repository root: `just run`. Ctrl+C stops the server.

From this folder (Python 3.10+):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Or with `uv`: `uv venv && uv pip install -r requirements.txt`.

Open **http://localhost:8765** in Chrome, wait for “Ready”, click **Record**,
and grant microphone access. Transcription is **on demand only**.
Speak Mandarin, then **hold Space or the Hold to transcribe button** when you miss a word:

- Set **Seconds added per second held**, default **2**, to control the scaling.
  Lookback is **1 + seconds held × factor**, rounded to 0.01 seconds.
- With factor **1**, holding for 1 second selects **2 seconds** of audio.
  With factor **2**, holding for 1 second selects **3 seconds**; 2 seconds selects **5 seconds**.
  Decimal factors such as **1.2** work too. A quick tap selects approximately 1 second.
- The selection stops growing at **15 seconds**. Its size is shown while holding.
- Release Space or the button to submit one transcription. The audio ends at release, so it
  includes speech heard while holding. There is no inference before release.
- Escape, moving focus, leaving the tab/window, or stopping cancels a pending hold.

The factor must be at least **0.1**. You can change it while recording; each hold
uses the factor selected when that hold started. The button and Space use the
same gesture. Enter on the focused button or an assistive-technology click
provides a one-second quick action.
It includes pauses. If you have recorded less than the selected duration, it uses
what is available. Invalid input shows a message without stopping the microphone.
The microphone keeps recording during inference. You can request another clip immediately,
including while earlier clips are queued or transcribing. Holding Space submits just
one request on release, rather than repeated requests.

Each request creates a Chinese pill on the left. The dark interface has three columns:

- **Left:** Chinese transcription, HSK highlights, and tone-marked pinyin.
- **Middle:** unique highlighted words with pinyin and HSK band. This list scrolls
  independently; its footer shows how many words will be saved. Click **×** to
  exclude a word from the current recording session, including other clips and
  their translations. Each new recording session resets manual selections and dismissals.
- **Right:** the highlighted words translated individually, together in one pill
  per clip. Click the pill (or focus it and press Enter) to invert it to a light
  style and reveal the full translated fragment. Click again to return to word mode.
  Full-fragment translation is requested only on first reveal and cached afterward.

The left and right pills scroll together and remain aligned. Rows are sized for
roughly three clip pairs, growing for longer content. The middle list does not move
when the outer columns scroll. New clips follow the bottom unless you have scrolled
up. Chinese pills retain **Timing & model** measurements.

**Record** becomes **Stop & save** while recording. Press it again to release the
microphone, finish accepted transcriptions and pending translations, and save the
selected words in one local database transaction. Unrequested audio is discarded.
After saving finishes, Record becomes available again. Existing clips remain visible
until refresh, but each recording has its own word selection. Ctrl+C stops the server.

Text is converted locally to **Simplified Chinese** using
[OpenCC](https://github.com/yichen0831/opencc-python) (`t2s`).
Use the model dropdown to switch between **Large-v3** and **Turbo**.
Use **Representation** to choose **INT8** or **FP32** for either model.
Stop recording and let queued clips finish before switching. Both selectors are
disabled during recording, queue draining, or loading. Changing settings preserves
existing pills. Only one model is kept in memory; changing either setting reloads it.

INT8 quantizes model weights and selected calculations to reduce memory use and
often improve CPU speed. FP32 uses 32-bit floating-point computation, avoiding
that additional INT8 quantization; it may use more memory and take longer.
Higher precision is not a guarantee of better recognition. Short clips reduce
the transcription workload, but the entire model must still be loaded.
These settings do not change the microphone's audio format.

The app checks CPU support before offering or accepting a representation. This
machine supports INT8 and FP32; FP16 is not supported by its current CPU backend.
`int8_float32` is also reported by the backend but is equivalent to `int8` here,
so the UI offers the two distinct choices. The setting changes computation at
load time using the same cached model files. Converting to FP32 cannot restore
precision already lost in those files. See [CTranslate2's quantization documentation](https://opennmt.net/CTranslate2/quantization.html).

First startup downloads roughly 3 GB of model weights into `.models/`; later runs
reuse them. Audio and full clip history stay in memory and are not uploaded. Words selected at session end and their sentence context are stored in
`sessions.sqlite3` beside `server.py`. Raw audio is never stored in that database.
The server retains at most 15 seconds of recent audio (about 960 KB),
plus frozen snapshots for accepted clips. It does no inference until requested.
Turbo also downloads its weights once on first selection. Model downloads require
internet. Recognition and script conversion run locally after setup.

## Read or change the code

- `server.py`: model loading, recent-audio buffering, request queue, and recognition.
  `MAX_SECONDS` (15) limits the buffer; `MAX_PENDING` (8) limits waiting clips.
  `transcribe()` sets Mandarin (`zh`) and greedy decoding (`beam_size=1`).
- `mic.js`: microphone audio capture at 16 kHz, mono float32. A clip request
  flushes the current audio batch before sending its boundary marker.
- `app.js`: microphone controls, hold gestures, request IDs, and pill updates.
  Space and pointer holds call `parseLastNSeconds(seconds)` on release with
  `min(15, 1 + seconds held × factor)`, rounded to two decimals. You can also
  call `parseLastNSeconds(8)` in the browser console while recording.
  This function accepts durations from 0.1 to 15 seconds, defaulting to 1.
- `translation.py`: cached OPUS-MT loading, SentencePiece tokenization, and Chinese → English inference.
- `vocabulary.js`: HSK segmentation, clickable word selection, session snapshots, and vocabulary/history display.
- `sessions.py`: SQLite word identities, completed sessions, memberships, and save counts.
- `translations.js`: individual-word requests, caching, bounded request scheduling, and full-fragment reveal.
- `data/hsk.json`: bundled word → HSK band/pinyin lookup; sources and licenses are in `data/README.md`.
- `index.html`: the controls, dark three-column layout, vocabulary dialog, and light reveal styles.

The clip is frozen when the server receives its request marker, after the worklet
flush; new incoming audio cannot change it. Every request has an ID so its result
updates the correct pill. The boundary may trail the physical keypress slightly
because the browser must deliver that message to the audio worklet.
While recording, Space is reserved for transcription even with a button, input,
select, translation card, or vocabulary dialog focused. Enter activates focused controls.

One microphone session is accepted at a time. Requests are asynchronous from the UI's
perspective, but the CPU runs **one inference at a time**, in request order.
Up to **eight clips may wait**, in addition to the one processing. Further requests
get an individual Failed pill explaining that the queue is full; recording continues.
A failed inference does not prevent later clips from processing. Stop drains the
accepted queue and translations, then saves before enabling Record and the model selectors again.

A fixed-duration cut can start in the middle of a word or lose earlier context;
the displayed text can therefore be wrong even when buffering is correct.
Whisper's speech VAD filters silent snapshots before inference. There is no
continuous live transcription or automatic inference on pauses.

## HSK flags and vocabulary bank

**Flag HSK (2021)** controls the minimum band to highlight, default **4 and above**.
Choose any band 1–6, combined **7–9**, or **Off**. Changing the threshold updates
visible highlights, the middle list, and word translations. It does not save or
remove vocabulary. Session-dismissed words stay dismissed across threshold changes.

Click or tap a word in a Chinese transcription to toggle its highlight. Focus a word
and press Enter for the same action. Manual highlights work below the HSK threshold
and with HSK highlighting Off; words absent from the HSK list are labeled Unclassified.
Selection applies to that word throughout the current session. Highlighted words appear
in the middle column and their individual translations appear on the right.

**Stop & save** saves all remaining highlighted words, automatic and manual, once per
session. A word repeated in several clips still receives one increment; saving it in a
later session increments its count again. Each word has a stable numeric ID. The
Vocabulary dialog shows cumulative save counts and expandable saved sessions.

The SQLite database is `whisper-live/sessions.sqlite3` (ignored by git), with four tables:

- `words`: stable ID, unique word text, pinyin, HSK band (0 means unclassified), meaning.
- `sessions`: session UUID and recording start/end timestamps.
- `session_words`: session ID, word ID, first selected Chinese context and any revealed translation.
- `word_save_counts`: word ID and cumulative `save_count`.

`POST /sessions` saves one complete session atomically. Retrying the same session UUID
never increments counts twice. `GET /vocabulary` reads the bank and session history.
No word or session data is written during recording. If saving fails, keep the tab open
and use **Retry saving session**. A new recording is blocked until saving succeeds.
An unexpected connection loss does not save automatically: **End session & save** saves
the words received so far. Closing or refreshing before a successful save loses the
unsaved session. Empty completed sessions are retained with zero words.

Word translations already requested are allowed to finish before saving; failed translations
leave the word saved without a meaning. Revealing a full fragment after a session is
saved does not rewrite that completed session. Starting another session resets selection
and dismissals without altering saved history. Dismissing a word never deletes earlier saves.

The HSK preference stays in browser localStorage. Older browser-saved vocabulary remains
readable under “Previously saved in this browser” and is left untouched; those entries
are not counted as newly completed sessions. New saved sessions survive browser storage
clearing and server restarts because they live in SQLite. Back up the database file while
the server is stopped to keep a copy of the history.

This uses the **2021 HSK 3.0 grading standard (GF 0025-2021)**, not the differently
graded 2025 exam syllabus. The bundled data has 10,946 distinct headwords from
11,092 entries; duplicate meanings use the lowest listed band. It comes from
[HSK University’s word list](https://github.com/ayman-ezz/hsk-3.0-word-list), with
pinned revision, transformations, attribution and licenses in `data/README.md`.

Chinese word boundaries start with Chrome’s built-in `Intl.Segmenter`. Adjacent
Chinese segments are joined when they form a longer HSK headword (for example,
三 + 明治 → 三明治). Only exact word matches in the dataset receive a level. Words missing from the list remain
unclassified, rather than being assumed difficult. This is a difficulty heuristic,
not a personal assessment or a guarantee of correct word boundaries/senses.
HSK lookup, segmentation, saving and reading work locally without a model download.

## Local translation

Translation uses [Helsinki-NLP OPUS-MT Chinese → English](https://huggingface.co/Helsinki-NLP/opus-mt-zh-en),
via a [converted CTranslate2 model](https://huggingface.co/ooeoeo/opus-mt-zh-en-ct2-float16).
The conversion revision is pinned in `translation.py`. The upstream model is CC-BY-4.0;
see the upstream model card for attribution and training details.

The first translation downloads about **160 MB** into `.models/`. Later starts load
from that cache without a network request. Translation runs on CPU with two threads
and FP32 computation (the downloaded weights were stored in FP16). The Whisper
representation selector controls Whisper only. SentencePiece tokenizes translation text; pypinyin adds pronunciation hints;
CTranslate2 and the model downloader are already installed with faster-whisper.

`POST /translate` accepts `{ "text": "你好" }` and returns English text and timing.
It runs in a background thread, independently of Whisper's worker: **translation of
clip A can overlap transcription of clip B**. Each model handles its own requests
sequentially. The translation queue allows eight waiting requests plus one running;
excess requests show a Failed translation pill without affecting Chinese transcription.
The browser allows at most two translation requests in flight, queuing the rest.
Individual words are sent separately, never concatenated into a sentence. Repeated
words reuse their result during this page session. A newly requested full fragment
gets priority over waiting words; active requests finish normally.
Both models share CPU resources, so overlap does not guarantee faster recognition.

Empty transcriptions skip translation. Translation errors stay in the English pill.
Stop drains transcription, then waits for requested translations before saving the session.
Refreshing loses the displayed clip timeline; completed session words remain in SQLite.
A failed initial download can be retried by requesting another clip.

Each request is limited to 2,000 characters and 512 source tokens to avoid silently
truncating long text. OPUS-MT translates the individual words as well as revealed
fragments; these are model translations, not dictionary definitions. Isolated words
can be ambiguous without context. Reveal the full fragment to compare meanings.

## Understand the timings

- **Release to result**: elapsed browser time from releasing
  Space or the button until its result is handled for display.
  Includes the worklet flush, transfer, queueing, and model processing; excludes
  the preceding recorded speech, time holding Space, and initial model loading. This is the
  useful measure of how long you wait after missing a word.
- **Audio**: duration of the snapshot, including any pauses.
- **Processing**: model/VAD time, excluding queueing and initial model load.
- **Server delay**: time since the server received the end of that snapshot,
  including queueing and processing; excludes speech collection and browser/network delay.

Submitting more clips adds waiting time; accepting requests immediately does not
make either model process its own queue simultaneously. The English header shows
the number of queued and active translation requests.

These are laptop **CPU** measurements, not phone or AMD GPU performance.
Accuracy depends on your speech and room. Check silence and background noise too.

Observed smoke test on this laptop (2026-10-18): Chrome microphone pipeline fed
a prerecorded Mandarin sample, a five-second clip, CPU with 8 threads,
the model already loaded, and no queued requests:

| Model | Representation | Processing | Request to result |
| --- | --- | --- | --- |
| Turbo | INT8 | 3.75 s | 3.76 s |
| Turbo | FP32 | 5.07 s | 5.07 s |
| Large-v3 | INT8 | 4.89 s | 4.89 s |
| Large-v3 | FP32 | 7.54 s | 7.54 s |

These are single runs, not averages or latency guarantees. All four returned
the same text for this sample; this does not measure their relative accuracy
on difficult words. Stop was pressed during each inference to check that the
requested result still arrives and the selectors stay locked until it finishes.

To start with Turbo already selected:

```sh
.venv/bin/python server.py --model turbo
```

Or start with FP32:

```sh
.venv/bin/python server.py --model large-v3 --compute-type float32
```

For CPU tuning: `--threads 4` or `--threads 8`.

## Checks

```sh
.venv/bin/python -m unittest test_server.py
```

The backend checks cover Simplified Chinese output, model/representation switching,
busy/loading guards, and recovery after loading fails. Clip checks cover exact
trailing samples, short histories, duration validation, no unsolicited inference,
immutable snapshots, queued requests, per-clip failures, queue overflow, Stop draining,
rejection of live mode, translation validation and failure recovery, and a blocked
translation overlapping recognition and microphone Stop. Models are stubbed; these do not measure recognition accuracy.

Browser checks use a Python environment containing `playwright` and installed
Google Chrome at `/usr/bin/google-chrome`:

```sh
python3 test_ui.py
```

These exercise real microphone capture with fake browser audio and intercepted inference:
repeated requests, result association, hold scaling, cancellation, Stop/restart,
connection errors, synchronized scrolling, narrow screens, configurable HSK flags,
manual word selection, global Space handling, session dismissals, word-only requests, lazy
full-fragment reveal, independent middle scrolling, session isolation, translation draining,
legacy vocabulary preservation, and idempotent save retries. No running server
or model download is required for these tests.

Persistent audio recording is not implemented.
