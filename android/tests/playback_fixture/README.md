# Separate playback test app

This test-only APK plays a looping Mandarin fixture with Android playback capture
explicitly allowed or blocked. It is not included in Chinese listening or its
release APK. Supply your own 16 kHz mono PCM16 WAV speech fixture.

```sh
export JAVA_HOME=/path/to/jdk17
export ANDROID_HOME=/path/to/android-sdk
bash android/tests/playback_fixture/build.sh /tmp/ning-playback-fixture /path/to/mandarin.wav
adb install -r /tmp/ning-playback-fixture/playback-fixture.apk
adb shell am start -n com.ning.playbackfixture/.PlaybackFixtureActivity --ez autoplay true --ez allowCapture true
```

Start app-audio capture in Chinese listening and approve permissions first. With
the player in front, hold/release the floating control, then Open app and confirm
transcription. Repeat with `--ez allowCapture false`; allow earlier sound to leave
the selected lookback interval. Capture should report no audio and create no clip.
Slide outside the hold button to cancel. Stop sharing and force-stop/reopen Chinese
listening before reviewing a queued clip to test process-restart recovery.

Outputs and the disposable test signing key stay in the supplied temporary
output directory. Do not commit or distribute these test artifacts.
