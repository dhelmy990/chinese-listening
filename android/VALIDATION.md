# Android build validation

Validated on 2026-10-18. Deliverable: `dist/ChineseListening-arm64-debug.apk`,
75,552,664 bytes, development-signed for sideloading. The checksum is in
`dist/SHA256SUMS`. This is not a Play Store release.

## Automated and build checks

- 30 backend tests, 16 shared browser tests, 5 Android runtime/download tests,
  and 3 Android browser/lifecycle tests passed.
- ARM64 and x86_64 native builds and APK builds passed. Android lint passed
  with warnings, no errors.
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

API 36 x86_64, four CPU cores, 6 GB RAM. Tested microphone permission denial
and retry, real WebView microphone capture at 16 kHz, and automatic microphone
stop/session save on backgrounding. The existing layout was visually checked.
With both Wi-Fi and mobile data disabled, force-stopping and relaunching the
app loaded the local models successfully and preserved the saved session.
Silence returned an empty transcript and translation also passed after this
offline restart.

The full app path (WebView WebSocket, Python preprocessing/VAD, native Turbo
INT8, simplified Chinese and pinyin) transcribed a five-second Mandarin fixture:

> 欢迎大家来体验达摩院推出的语音识别模型

Independent OPUS-MT translation returned `Hello.` for `你好`.
Transcription took 266.56 seconds on this emulator. This establishes correctness,
not acceptable listening latency on a phone. Physical ARM64 phone speed, battery
usage, heat, and memory behavior remain unmeasured.

Publication recheck on 2026-10-19: all 54 automated tests passed again, the
ARM64 APK was rebuilt after whitespace cleanup, and its signature, checksum,
and all 91 native-library alignments were verified.
