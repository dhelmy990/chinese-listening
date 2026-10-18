# Chinese listening

An offline Mandarin listening helper for Android and desktop. Capture a short
audio clip on demand, read simplified Chinese and pinyin, translate words into
English, and save vocabulary from each session. The Android app preserves the
desktop interface and runs **Whisper Turbo INT8 only**.

## Download and install on Android

**[Download the ARM64 APK — 75.5 MB](https://github.com/dhelmy990/chinese-listening/releases/download/v1.0.0-preview.1/ChineseListening-arm64-debug.apk)**

[Release notes and SHA-256 checksum](https://github.com/dhelmy990/chinese-listening/releases/tag/v1.0.0-preview.1)
· [All releases](https://github.com/dhelmy990/chinese-listening/releases)

1. Download `ChineseListening-arm64-debug.apk` from the link above onto your
   phone. GitHub's **Source code** ZIP is for building the app, not installing it.
2. Open the APK. If Android asks, allow your browser or file manager to install
   apps from this source, then finish installation. You can turn that permission
   off afterward.
3. Open **Chinese listening** and tap **Set up offline models**. This downloads
   approximately **1.78 GB**. Use Wi-Fi and keep the app open until setup finishes;
   interrupted downloads resume when retried.
4. Tap **Record**, allow microphone access, then hold **Hold to transcribe** and
   release it to transcribe recent audio. Tap **Stop & save** to save selected
   vocabulary.

Requires **Android 7.0/API 24 or newer**, a **64-bit ARM (arm64-v8a) device**,
and an up-to-date Android System WebView. Allow roughly **2 GB of storage plus
working space**, and several GB of available RAM for inference. Phone-specific
RAM and latency requirements have not been measured. The original three-column
layout scrolls horizontally on narrow screens.

This first release is an **experimental, development-signed APK for sideloading**.
It is not a Play Store release. Full transcription, translation, microphone,
session saving, and offline restart were tested on an Android emulator.
The emulator took about **4½ minutes for a five-second clip**; physical-phone
performance remains unverified. See [validation results](android/VALIDATION.md).

Models download once, then recognition, translation, pinyin, HSK highlighting,
and vocabulary history work offline. No account or API key is required. Audio
is processed locally; selected vocabulary and sentence context stay in the
app's private database. Uninstalling or clearing app data removes the models
and saved history. Leaving the app stops recording; allow **Stop & save** to
finish before closing it to preserve your session.

To verify a download on a computer, download `SHA256SUMS` from the same release
into the APK's directory and run:

```sh
sha256sum -c SHA256SUMS
```

## Build or run from source

- **Android:** [toolchain requirements, build commands, and tests](android/README.md).
- **Desktop:** [setup and usage](whisper-live/README.md). Desktop also supports
  Large-v3 and FP32; the Android build is fixed to Turbo INT8.
- **Components and attribution:** [third-party notices](android/THIRD_PARTY_NOTICES.md)
  and [HSK dataset provenance](whisper-live/data/README.md).

The repository contains source, tests, build configuration, the small Silero
speech detector, and HSK vocabulary data. Large speech/translation models are
downloaded at setup. APKs and checksums are attached to GitHub releases; local
databases, credentials, signing keys, model caches, and build output are excluded
from Git.
