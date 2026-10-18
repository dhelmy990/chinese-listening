# Chinese listening

An offline Mandarin listening helper for Android and desktop. Capture a short
audio clip on demand, read simplified Chinese and pinyin, translate words into
English, and save vocabulary from each session. The Android app uses a phone-friendly layout and runs **Whisper Turbo INT8 only**.

## Download and install on Android

**[Download the ARM64 APK](https://github.com/dhelmy990/chinese-listening/releases/download/v1.1.0-preview.1/ChineseListening-arm64-debug.apk)**

[Release notes and SHA-256 checksum](https://github.com/dhelmy990/chinese-listening/releases/tag/v1.1.0-preview.1)
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

**Updating:** install the new APK over the previous preview to keep downloaded
models and saved history. Do not uninstall first.

Requires **Android 7.0/API 24 or newer**, a **64-bit ARM (arm64-v8a) device**,
and an up-to-date Android System WebView. Allow roughly **2 GB of storage plus
working space**, and several GB of available RAM for inference. Phone-specific
RAM and latency requirements have not been measured. On phones, Chinese and
English appear in stacked cards; **Listen** and **Words** tabs keep every panel
accessible. Settings collapse to leave more room for reading.

This release is an **experimental, development-signed APK for sideloading**.
It is not a Play Store release. Full transcription, translation, microphone,
session saving, and offline restart were tested on an Android emulator.
The emulator took about **4½ minutes for a five-second clip**; physical-phone
performance remains unverified. See [validation results](android/VALIDATION.md).

Models download once, then recognition, translation, pinyin, HSK highlighting,
and vocabulary history work offline. No account or API key is required. Audio
is processed locally; selected vocabulary and sentence context stay in the
app's private database. Uninstalling or clearing app data removes the models
and saved history. Leaving the app stops microphone recording. App-audio capture continues with
a foreground notification. Allow **Stop & save** to finish before closing the
app to preserve selected vocabulary. Captured app-audio snippets are stored
privately until successfully processed and their session is saved; they can be
reviewed after a process restart. Clearing app data also removes these snippets.

## Capture audio from another app

Requires **Android 10 or newer**. Tap **Capture app audio** to start a new session
or add to the session currently open. Leave **Floating capture button** enabled
in Settings. Allow audio access, **Display over other apps**, and Android’s
screen-sharing prompt. The app captures audio only; it does not record screen
images or video. Notification permission makes the capture controls accessible
from the notification shade.

Open YouTube or another player, then **hold the floating button and release** to
save a snippet. Drag its handle to move it; slide outside the hold button to
cancel. Capture uses the same lookback rule as microphone recording: one second
plus hold duration multiplied by the Settings factor, up to 15 seconds. Up to
24 snippets can wait for review.

Tap **Open app** to transcribe queued snippets in the current session, select
words, then **Stop & save**. After an app restart, **Review audio** imports retained
snippets into a new session. Saved sessions remain history; additions go into the
currently open session. Floating **Stop** stops audio sharing but keeps captured
snippets for review.

Android allows capture only when the source app permits it. Some apps, streams,
and protected content block capture, including potentially content in YouTube.
Blocked or silent audio produces a message, with no microphone fallback.

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
