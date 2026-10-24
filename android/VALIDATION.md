# Android / home-server validation

Validated on 2026-10-24 for version 1.2 (`v1.2.0-preview.1`).
ARM64 APK: 75,540,937 bytes, development-signed for sideloading.
SHA-256 is in the release's `SHA256SUMS`.

## Automated checks

85 Python/browser tests passed:

- 30 existing shared/Android backend tests.
- 14 PC server/CLI tests: authentication, PCM validation, bounded admission,
  transcription streamed before blocked translation, overlapping next recognition,
  loading/failure/disconnect paths, and the installed PyAV decoding API.
- 11 Android runtime tests: existing 5 plus remote HTTP/auth/redirect validation,
  replacing the localhost server on reconnect, no phone model download, and
  reconnecting while an old translation request is stalled.
- 16 existing shared browser tests, 3 phone-layout tests, 4 Android lifecycle/UI
  tests and 7 native-capture integration tests.

The native capture JUnit suite passed. x86_64 and ARM64 APK builds passed.
Android lint reports no errors and 19 warnings. APK signature verification and
all 91 native-library/extension 16 KB ELF LOAD-segment alignment checks passed.
No physical 16 KB device was tested.

## Real inference measurements

PC: AMD Ryzen 9 8945HS, Turbo INT8 on CPU with 8 threads; OPUS-MT CPU translation.
The existing model cache was used and both models were warm for measurements.

| Path | Audio | Transcription | Translation |
| --- | --- | --- | --- |
| PC command-line client, run 1 | 3 s | 4.55 s PC processing | 0.106 s PC processing |
| PC command-line client, run 2 | 3 s | 3.02 s PC processing | 0.104 s PC processing |
| Android WebView → phone adapter → PC → WebView | 5 s | 3.69 s total round trip | Independent `你好` request returned `Hello.` in 0.86 s including network |
| Floating button over Android player → PC → app | 3 s | 3.62 s release to result | Individual word translations returned afterward |

The command-line client emitted accepted, transcription, translation and done in
order. The five-second remote Android result included Chinese text and pinyin:

> 欢迎大家来体验达摩院推出的语音识别模型

These are smoke-test runs, not averages or latency guarantees. The Android device
was an API 36 x86_64 emulator, not a physical phone over Wi-Fi. The user's physical
phone previously took about 90 seconds for 3 seconds of local audio; its new
remote-mode latency remains to be measured on the actual home network.

## Android behavior

- Updated the emulator APK over the previous preview and preserved saved vocabulary.
- Entered a PC URL/token through the native connection form; the shared UI reported
  Home PC · Turbo INT8. Subsequent launch reused the credentials automatically.
- Changed the PC connection from Settings and reconnected in the same process.
- The remote bootstrap requires no phone model directory; its tests explicitly
  reject any attempt to call the phone model downloader.
- Live process maps contained neither `libning_inference` nor `libonnxruntime`.
  Old model files are retained but neither downloaded nor loaded by this version.
- Captured a three-second snippet with the real floating button over the separate
  Android playback test app. Returning to Chinese listening produced Chinese,
  pinyin and individual English translations through the PC. Stop & save drained
  processing and acknowledged the queued audio.

The existing capture policy and permission behavior is unchanged. Previous
preview validation covered allowed/blocked source policies, cancellation, moving
the overlay, projection revocation and process-restart recovery. This update's
browser regression suite retains the lifecycle and durability checks.

## Scope

The server binds a requested LAN address and requires a private bearer token on
all routes. It stores no audio. Android retains its authenticated localhost UI
and local session database; server-provided HTML never receives the native bridge.
Both HTTP clients reject redirects to avoid forwarding access tokens.

No VPN, router port forwarding, public HTTPS deployment, automatic server startup,
production signing or Play Store release was configured. Keep the PC awake on a
trusted local network. Physical-phone network latency and OEM background behavior
remain unverified.
