# Chinese listening

A Mandarin listening helper with a phone-friendly Android interface and a home
PC inference server. Hold to capture a short microphone or app-audio snippet,
read simplified Chinese and pinyin, translate words into English, and save
vocabulary from each session.

**Android uses the PC for transcription and translation by default.** It does
not download or load speech models on the phone. Whisper Turbo INT8 and OPUS-MT
run on the PC; the interface, floating capture button and vocabulary history
remain on the phone.

## Download Android

**[Download the ARM64 APK](https://github.com/dhelmy990/chinese-listening/releases/download/v1.2.0-preview.1/ChineseListening-arm64-debug.apk)**

[Release notes and SHA-256 checksum](https://github.com/dhelmy990/chinese-listening/releases/tag/v1.2.0-preview.1)
· [All releases](https://github.com/dhelmy990/chinese-listening/releases)

Download the APK, open it on your phone, and allow installation from your browser
or file manager if Android asks. Install over the previous preview to preserve
vocabulary and queued audio. GitHub's source-code ZIP is not an installer.

Requires Android 7.0/API 24+, an ARM64 device, and an up-to-date Android System
WebView. Capturing another app's audio requires Android 10+. This remains an
experimental development-signed APK for sideloading, not a Play Store release.

## Start the home PC server

Run from this repository on the PC:

```sh
./home-server --host 0.0.0.0
```

Wait for `Home inference ready: turbo INT8 and OPUS-MT.` Keep the terminal open
and the PC awake. Ctrl+C stops the server. It listens on port **8766**. Models
remain loaded between requests; transcription and translation have independent
workers and bounded queues.

The command uses `whisper-live/.venv` and the existing PC model cache. For a
fresh source clone, install the [desktop dependencies](whisper-live/README.md#run)
and prepare the PC models once:

```sh
cd whisper-live
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('turbo', device='cpu', compute_type='int8', download_root='.models'); from translation import load_translator; load_translator()"
cd ..
```

The server creates a random access token in **`.checks/home-server.token`**, with
owner-only permissions. To display it for entry on your phone:

```sh
cat .checks/home-server.token
```

Keep the token private. It is excluded from Git and reused when the server
restarts. The direct HTTP address works on your trusted home network. For mobile
data or another Wi-Fi network, use the HTTPS tunnel below. No router port
forwarding is needed.

## Connect the phone on home Wi-Fi

For mobile data or another network, follow [the tunnel instructions](#use-mobile-data-or-restart-the-cloudflare-tunnel) instead.

1. Connect the phone to your home Wi-Fi.
2. Open Chinese listening and tap **Connect to PC server**.
3. Enter `http://YOUR-PC-LAN-IP:8766` and the token. On Linux, `hostname -I`
   lists addresses; choose the home-network address, not a Docker interface.
4. Tap **Connect**. Later launches reconnect automatically using these settings.
5. Tap **Record**, then hold/release **Hold to transcribe**. Choose words and tap
   **Stop & save** to save vocabulary locally.

Use **Settings → PC connection settings** to change the address/token after
saving the current session. If connection fails, check the server terminal,
token, Wi-Fi, PC firewall and client isolation on guest Wi-Fi. If the PC address
changes, update the saved address. Existing phone model files from older previews
are left untouched but are not loaded or used by this version.

On phones, Chinese and English use stacked cards, **Listen/Words** tabs, and
collapsible Settings. The desktop interface retains its three columns.

## Use mobile data or restart the Cloudflare tunnel

The existing Android APK supports HTTPS server addresses, so restarting the
[Cloudflare Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
does not require a new APK, Cloudflare account, or Cloudflare API key. Keep using
the access token from `.checks/home-server.token`.

1. **Keep the PC server running.** If it is stopped, open a terminal in this
   repository and run:

   ```sh
   ./home-server --host 0.0.0.0
   ```

   Wait for `Home inference ready: turbo INT8 and OPUS-MT.` If it is already
   running, leave that process alone; starting a second server will report that
   port 8766 is in use.

2. **Stop the old tunnel, if it is still running.** Press Ctrl+C in its terminal.
   If it was started in the background during setup, find its process:

   ```sh
   pgrep -af '[c]loudflared tunnel --url http://127.0.0.1:8766'
   ```

   Check that the displayed command is the tunnel for this app, then run
   `kill PID`, replacing `PID` with that process number. If no process is listed,
   continue. This stops the tunnel, not the inference server.

3. **Start a fresh tunnel in a separate terminal:**

   ```sh
   cloudflared tunnel --url http://127.0.0.1:8766 --no-autoupdate
   ```

   `cloudflared` is already installed on the setup PC. On another computer,
   install it using the linked Cloudflare instructions first. Keep this terminal
   open. The command prints a new address like
   `https://random-words.trycloudflare.com`; wait for the tunnel connection to
   register. The address generally changes each time you restart the tunnel.

4. **Update the Android app.** Finish the current session with **Stop & save**,
   then open **Settings → PC connection settings**. If the app is on its startup
   screen, use **Connect to PC server** or **Check PC connection** instead.
   Replace the old address with the full new `https://…trycloudflare.com` URL.
   **Do not append `:8766` or `/api`.** Keep the same garbled access token and tap
   **Connect**. The app remembers this address until you change it again.

5. **Test before leaving.** Turn off the phone's Wi-Fi and submit a short clip
   over mobile data. You can also test the public address from the PC:

   ```sh
   ./request-clip /path/to/clip.wav --duration 3 --server https://YOUR-NEW-TUNNEL.trycloudflare.com
   ```

Leave the PC awake and connected to the internet, with both the inference server
and tunnel running. Quick Tunnels are temporary and have no uptime guarantee;
the URL stops working when the tunnel stops. `--no-autoupdate` prevents the tunnel
process from automatically restarting for an update. To stop remote access,
press Ctrl+C in the tunnel terminal; you can keep the PC server running locally.
Audio travels through Cloudflare to your PC, and the server still requires your
access token. Opening the URL in a browser without that token can show an
authentication error; use the app or authenticated command-line client to test it.

## Capture audio from another app

Tap **Capture app audio** to start or join the current recording session. Leave
**Floating capture button** enabled in Settings. Allow audio access, **Display
over other apps**, and Android's screen-sharing prompt. Only audio is captured;
no screen images or video are recorded.

Open a player, hold the floating button, then release it to save a snippet. Drag
its handle to move it; slide outside the hold button to cancel. The lookback is
one second plus hold duration multiplied by the Settings factor, up to 15 seconds.
Tap **Open app** to send queued snippets to your PC for processing. Up to 24
snippets can wait privately on the phone. **Review audio** recovers them after an
app restart. Successful snippets are removed after their vocabulary session saves.

Android respects the source app's capture policy. Some apps/streams and protected
content block capture, potentially including content in YouTube. Blocked or silent
audio produces a message; the app does not fall back to microphone capture.
Leaving the app stops microphone recording, while app-audio capture continues
with its foreground notification. Floating **Stop** ends audio sharing and keeps
queued snippets for review.

## Send an audio file from the command line

With the server running:

```sh
./request-clip /path/to/clip.wav
# Select 3 seconds from a longer file:
./request-clip /path/to/audio.mp3 --start 10 --duration 3
# A client on another machine needs the server address and a private copy of its token:
./request-clip /path/to/clip.wav --server http://YOUR-PC-LAN-IP:8766 --token-file /private/path/token
```

The client prints newline-delimited JSON immediately as each event arrives:
`accepted`, `transcription` (Chinese, pinyin and timing), `translation` (English),
then `done`. Errors exit nonzero. Translation follows recognition without blocking
the server from transcribing the next clip. Clips are limited to 15 seconds; use
`--no-translate` for transcription alone.

The authenticated API is documented in [android/README.md](android/README.md#pc-api).

## Data, builds and validation

Audio and requested text travel to your PC for inference. The server keeps audio
in memory only and does not save recordings. Selected vocabulary and sentence
context stay in the phone's private database. Clearing app data/uninstalling
removes history and queued snippets. No cloud transcription account is required.

- [Android build instructions and API](android/README.md)
- [Validation and measured latency](android/VALIDATION.md)
- [Desktop usage](whisper-live/README.md)
- [Third-party notices](android/THIRD_PARTY_NOTICES.md) and [HSK data provenance](whisper-live/data/README.md)

APKs/checksums are release assets. Models, local databases, tokens, signing keys,
audio fixtures and build output are excluded from Git. Verify an APK by downloading
its release's `SHA256SUMS` alongside it and running `sha256sum -c SHA256SUMS`.
