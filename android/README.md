# Chinese listening for Android

The desktop interface and listening/session behavior, packaged for Android with **Turbo INT8 only**. Recognition, Chinese-to-English translation, pinyin, HSK highlighting and vocabulary history run locally. There are no transcription API calls.

## Install

**[Download the prepared ARM64 APK](https://github.com/dhelmy990/chinese-listening/releases/download/v1.1.0-preview.1/ChineseListening-arm64-debug.apk)**
or read the [step-by-step installation instructions](../README.md#download-and-install-on-android).
The APK and `SHA256SUMS` are release attachments, not files included in a source clone.

The prepared ARM64 APK is `dist/ChineseListening-arm64-debug.apk`. After a fresh build, use `app/build/outputs/apk/debug/app-debug.apk`. This is a development-signed APK for sideloading, not a Play Store release. Android 7.0/API 24 or newer, a 64-bit ARM device, and an up-to-date Android System WebView are required. Allow microphone permission when you press Record.

First launch offers **Set up offline models**. It downloads about **1.78 GB** using pinned model revisions, verifies SHA-256 checksums, and saves them in private application storage. Use Wi-Fi and keep the app open during setup. Interrupted downloads resume on retry. Subsequent launches check and reuse local models without network access. Reserve additional space for the app and several GB of available RAM for inference; memory and latency must be measured on the target phone.

Phones use stacked Chinese/English cards, Listen/Words tabs, collapsible Settings,
and accessible recording controls. Desktop screens retain the three-column view.
Hold the on-screen button and release to transcribe. Record becomes Stop & save
during a session. Leaving the app stops the microphone; device-audio capture
continues in a foreground service.

On Android 10+, **Capture app audio** starts or joins the current session. Enable
the floating button, grant overlay/audio permissions and approve the system's
screen-sharing prompt. No screen images or video are collected. Hold the floating
button over a player and release to queue recent audio; use Open app to transcribe
it. Android respects the source app's capture policy, so protected or blocked
sources cannot be recorded. See [the capture walkthrough](../README.md#capture-audio-from-another-app).

App-audio snippets survive process restarts in a bounded private inbox (24 clips,
15 seconds each, 16 kHz mono PCM16: at most 11.52 MB). Successful snippets are
removed only after their vocabulary session saves; failed snippets remain for
retry. The rolling audio buffer is 480 KB. Raw microphone audio is not persisted.
Saved sessions survive restarts. Unsaved screen contents can be lost if Android
kills the process. Clearing app data or uninstalling removes models, history and
queued snippets. Capture needs new Android consent after it stops.

## Build

Requirements: a complete JDK 17 (including `jlink`), Python 3.13 plus Python 3 with pip, Android SDK platform 36/build-tools 36.0.0, NDK 27.2.12479018 and CMake 3.22.1. Set `ANDROID_HOME` or `sdk.dir` in an untracked `local.properties` file. Set `JAVA_HOME` to the JDK. If Python 3.13 is not on PATH, run `./build.sh -PbuildPython=/absolute/path/to/python3.13 assembleDebug`.

```sh
cd android
./build.sh
# Emulator variant; output uses the same APK filename:
./build.sh -Pabi=x86_64 assembleDebug
```

The build creates a pure-Python aiohttp wheel, downloads pinned native dependencies and Android Python wheels, and compiles CTranslate2. Large model files are not bundled in the APK. Gradle copies the shared web assets and `server.py`/`sessions.py` at build time, so the UI is not maintained as a separate fork. CTranslate2 uses Ruy rather than the desktop x86 math backend.

## Checks

```sh
../whisper-live/.venv/bin/python -m unittest discover -s tests
python3 tests/check_android_ui.py
python3 tests/check_device_audio_ui.py
python3 tests/check_apk_alignment.py dist/ChineseListening-arm64-debug.apk
cd ../whisper-live
.venv/bin/python -m unittest test_server test_android_server
python3 test_ui.py
python3 test_phone_ui.py
cd ../android
./build.sh testDebugUnitTest lintDebug assembleDebug
```

The separate [playback test app](tests/playback_fixture/README.md) exercises allowed
and blocked playback capture without relying on a third-party player.

Native input/Unicode tests and ONNX parity checks are documented in `app/src/main/cpp/tests/README.md`. Device checks must cover microphone permission denial/retry, a real Mandarin clip, silence, independent translation, Stop & save, history after restart, backgrounding and an offline restart. Desktop tests do not establish Android device performance.

## Implementation

- `ListeningApplication` handles setup and one backend per Android process.
- `MainActivity` hosts the existing UI and restricts WebView navigation and microphone access to the private loopback origin.
- `PlaybackCaptureService` uses Android AudioPlaybackCapture with a draggable hold control; `PlaybackStore` retains snippets until the shared session flow acknowledges them.
- `ning_android` supplies checked downloads, native model adapters and shared-server startup.
- `NativeEngine` runs CTranslate2 Turbo INT8 and OPUS-MT FP32, with native SentencePiece tokenization. `SileroVad` runs the same silence detector with Android ONNX Runtime. Python 3.13 is used for compatible ARM64 NumPy binaries on 16 KB devices.
- The loopback server requires a random per-process HttpOnly cookie, including read endpoints. Session SQLite data is stored in app-private files. Android backup is disabled.
- Debug builds enable WebView debugging for emulator inspection. Do not distribute a debug APK as a production release.

See [third-party notices](THIRD_PARTY_NOTICES.md), also accessible through Licenses in the Android footer. Play Store publication, production signing, and physical-phone performance testing are separate from producing the sideloadable APK.

See [validation results](VALIDATION.md) for the tested scope and measured emulator latency.
