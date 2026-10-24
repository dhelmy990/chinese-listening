# Chinese listening for Android

Android is a client of the home PC inference server. Transcription uses Turbo
INT8 and translation uses OPUS-MT on the PC. The phone does not download or load
speech models. The shared interface, microphone/app-audio capture, pinyin display,
HSK highlighting and saved vocabulary remain on the phone.

## Install and connect

**[Download the ARM64 APK](https://github.com/dhelmy990/chinese-listening/releases/download/v1.2.0-preview.1/ChineseListening-arm64-debug.apk)**

Follow the [server and phone setup instructions](../README.md#start-the-home-pc-server).
Run `./home-server --host 0.0.0.0` on the PC, then enter its LAN URL and private
token in the Android app once. Subsequent starts reconnect automatically.
Settings → PC connection settings changes the saved address/token after the
current session has been saved. History stays in app-private SQLite storage.

Requires Android 7/API 24+, ARM64, and current Android System WebView. Playback
capture requires Android 10/API 29+ and a source app that allows capture. The
floating button and queued snippets behave as described in the [capture guide](../README.md#capture-audio-from-another-app).
There is no microphone fallback for blocked app audio.

The APK is development-signed for sideloading. Install over the previous preview
to keep history. Old downloaded phone models are retained but unused; no native
speech engine is initialized in this version. Existing native libraries remain
packaged for build compatibility, so the APK is still about 75 MB. Clearing app
data removes history, connection settings, queued audio and old models together.

## PC API

All endpoints require `Authorization: Bearer <token>`. The server is on port 8766.
HTTP is intended for a trusted LAN; no router port forwarding or VPN is configured.

| Endpoint | Request | Response |
| --- | --- | --- |
| `GET /api/status` | None | JSON `ready`, `model`, `compute_type`, `error` |
| `POST /api/transcribe` | Raw 16 kHz mono little-endian float32, 1–240,000 samples, values −1…1; `Content-Type: application/octet-stream` | Streaming `application/x-ndjson` |
| `POST /api/transcribe?translate=0` | Same PCM format | Recognition only |
| `POST /api/translate` | JSON `{ "text": "你好" }`, 1–2,000 characters | JSON English `text` and `compute_seconds` |

A transcription request first emits `{ "type": "accepted", "id": "…" }`.
The next event is `transcription` with the same ID, Chinese `text`, `pinyin` and
timing. With translation enabled, a `translation` event follows, then `done`.
An `error` event signals an accepted request failed; HTTP 400/401/413/429/503
rejects invalid, unauthenticated, oversized, busy or unavailable requests before
streaming. No result polling or audio persistence is needed. Disconnecting does
not provide durable job recovery; the Android inbox retains original snippets
until successful processing and session saving.

Recognition is serialized independently of translation, so another clip can be
transcribed while a previous translation runs. Admission limits bound pending
memory. `./request-clip` handles file decoding and prints events as they arrive.
The Android adapter requests recognition alone and uses `/api/translate` for the
existing independent word/full-fragment translation flow.

The phone's **Processing** timing includes the request to the PC and its response;
the CLI's `compute_seconds` measures PC model processing. Initial model load and
queueing also affect response time.

## Build

Requirements: complete JDK 17, Python 3.13 plus Python 3 with pip, Android SDK
36/build-tools 36.0.0, NDK 27.2.12479018 and CMake 3.22.1. Set `JAVA_HOME` and
`ANDROID_HOME` (or untracked `local.properties`). The existing native dependencies
remain in the build, although the Android startup path no longer loads them.

```sh
cd android
./build.sh
# Emulator variant:
./build.sh -Pabi=x86_64 assembleDebug
# If Python 3.13 is not on PATH:
./build.sh -PbuildPython=/absolute/path/to/python3.13 assembleDebug
```

The output is `app/build/outputs/apk/debug/app-debug.apk`. Shared web assets and
server/session code are copied at build time rather than maintained as a UI fork.
Prepared release APKs are in ignored `dist/` and attached to GitHub releases.

## Checks

```sh
# From repository root:
whisper-live/.venv/bin/python -m unittest discover -s android/tests
python3 android/tests/check_android_ui.py
python3 android/tests/check_device_audio_ui.py
python3 android/tests/check_apk_alignment.py android/dist/ChineseListening-arm64-debug.apk
cd whisper-live
.venv/bin/python -m unittest test_server test_android_server test_home_server
python3 test_ui.py
python3 test_phone_ui.py
cd ../android
./build.sh testDebugUnitTest lintDebug assembleDebug
```

[Validation results](VALIDATION.md) distinguish PC/emulator measurements from
physical-phone behavior. The [separate playback test app](tests/playback_fixture/README.md)
exercises capture policy. Test fixtures, tokens, model caches and session data
must remain untracked.

## Implementation

- `MainActivity` stores the PC URL/token in private preferences and automatically
  reconnects. Its WebView still loads only the authenticated localhost app;
  remote HTML never receives the native audio bridge.
- `ListeningApplication` copies UI assets and starts the lightweight Python server.
- `ning_android.bootstrap` selects only `RemoteRuntime`, with no phone model setup.
  Reconnection closes the previous localhost listener before binding another.
- `RemoteRuntime` sends PCM and text to the PC using authenticated HTTP, rejects
  redirects, and provides the same inference interface used by the shared server.
- `PlaybackCaptureService` and `PlaybackStore` retain the existing floating capture
  control and bounded private inbox. Session data stays local; backup is disabled.

See [third-party notices](THIRD_PARTY_NOTICES.md). Debug builds enable WebView
inspection; Play Store distribution and production signing are separate work.
