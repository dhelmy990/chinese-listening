# Android build validation

Validated on 2026-10-19. Version 1.1. Deliverable: `dist/ChineseListening-arm64-debug.apk`,
75,540,469 bytes, development-signed for sideloading. The checksum is in
`dist/SHA256SUMS`. This is not a Play Store release.

## Automated and build checks

- 30 backend tests, 16 shared browser tests, 5 Android runtime/download tests,
  3 Android browser/lifecycle tests, 3 phone-layout tests, and 7 device-audio
  integration tests passed (64 total). Native ring-buffer, private-inbox and
  delayed-save/drain checks also passed through the JUnit suite.
- ARM64 and x86_64 native builds and APK builds passed. Android lint passed
  with 18 warnings, no errors.
- APK signature verification passed. All 91 native libraries/extensions in
  the ARM64 APK, including those inside Chaquopy archives, passed the recursive
  16 KB ELF LOAD-segment alignment check. A physical 16 KB device was not tested.
- Native input/Unicode validation, SentencePiece translation, and Silero
  probability/state-reset parity checks passed.
- Download checks covered checksum verification, reuse, interrupted-transfer
  resumption, and a real pinned HTTPS configuration download. The emulator's
  large model files were seeded from the existing cache and verified during
  setup; a complete 1.78 GB mobile-network download was not exercised.

## Android emulator

API 36 x86_64, four CPU cores, 6 GB RAM. The 1.1 phone layout was visually
checked on the WebView at 412 CSS pixels. Automated layout checks also cover
360/390-pixel phones and 740×360 landscape, including long Chinese text, paired
English cards and access to Words/Settings. A manual browser check at 320 pixels
with enlarged text also kept the page within the viewport.

The previous preview validation tested microphone permission denial and retry,
real WebView microphone capture at 16 kHz, and automatic microphone stop/session
save on backgrounding. These behaviors also have browser regression coverage.
With both Wi-Fi and mobile data disabled, force-stopping and relaunching the
app loaded the local models successfully and preserved the saved session.
Silence returned an empty transcript and translation also passed after this
offline restart.

The full app path (WebView WebSocket, Python preprocessing/VAD, native Turbo
INT8, simplified Chinese and pinyin) transcribed a five-second Mandarin fixture:

> 欢迎大家来体验达摩院推出的语音识别模型

Independent OPUS-MT translation returned `Hello.` for `你好`.
The previous preview transcription took 266.56 seconds on this emulator. This establishes correctness,
not acceptable listening latency on a phone. Physical ARM64 phone speed, battery
usage, heat, and memory behavior remain unmeasured.

## App-audio capture

The API 36 emulator granted audio, overlay, notification and MediaProjection
permissions. A separate test app played a looping Mandarin PCM fixture with
capture allowed. Holding the real floating control for two seconds saved a
5.02-second snippet while Chinese listening was backgrounded; transcription
waited until returning to the app. Dragging moved the overlay; sliding outside
canceled a hold without saving another clip. Canceling the system consent prompt
reported cancellation and allowed another attempt. Switching
the source to a blocking capture policy produced a clear no-audio error and no
additional file. Android’s Stop sharing control stopped the capture service and
retained the pending snippet.

After stopping capture, force-stopping and reopening Chinese listening retained
the snippet. Review audio opened a new session without microphone capture.
The recovered clip completed the real WebSocket/Python/native Turbo INT8 path
in 273.56 seconds and displayed Chinese text and pinyin. Selecting a word and
using Stop & save completed the session and removed the private PCM snippet.

The browser/native bridge tests additionally cover appending to the current
session, failed-save retry without deleting audio, and Stop & save waiting for
an accepted native disk write before closing the session.

This validates a controlled player on an emulator, not YouTube or every OEM's
background behavior. Android 7–9 microphone compatibility is retained in code;
playback capture is gated to Android 10+. No physical phone, accessibility-service
session or production-signed/Play Store build was tested.
