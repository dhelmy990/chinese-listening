#!/usr/bin/env bash
# Usage: build.sh [output-directory] [16kHz mono PCM16 WAV fixture]
# This standalone test APK never enters the production Gradle build.
set -euo pipefail
fixture_source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fixture_output=${1:-/tmp/ning-playback-fixture}
fixture_wav=${2:-"$fixture_source_dir/../../../whisper-live/.checks/mandarin.wav"}
fixture_sdk=${ANDROID_HOME:-${ANDROID_SDK_ROOT:?Set ANDROID_HOME or ANDROID_SDK_ROOT to the Android SDK}}
fixture_jdk=${JAVA_HOME:?Set JAVA_HOME to a complete JDK 17}
fixture_tools="$fixture_sdk/build-tools/36.0.0"
mkdir -p "$fixture_output/assets" "$fixture_output/classes" "$fixture_output/dex"
python3 - "$fixture_wav" "$fixture_output/assets/mandarin.pcm" <<'PY'
import pathlib, sys, wave
with wave.open(sys.argv[1], 'rb') as source:
    assert (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getcomptype()) == (16000, 1, 2, 'NONE'), 'Expected 16 kHz mono PCM16 WAV'
    audio = source.readframes(source.getnframes())
    assert audio and any(audio), 'Fixture must contain audio'
    pathlib.Path(sys.argv[2]).write_bytes(audio)
PY
"$fixture_jdk/bin/javac" -source 8 -target 8 -Xlint:-options -cp "$fixture_sdk/platforms/android-36/android.jar" \
    -d "$fixture_output/classes" "$fixture_source_dir/PlaybackFixtureActivity.java"
JAVA_HOME="$fixture_jdk" "$fixture_tools/d8" --min-api 29 --lib "$fixture_sdk/platforms/android-36/android.jar" \
    --output "$fixture_output/dex" "$fixture_output/classes/com/ning/playbackfixture/PlaybackFixtureActivity.class"
"$fixture_tools/aapt2" link -o "$fixture_output/unsigned.apk" --manifest "$fixture_source_dir/AndroidManifest.xml" \
    -I "$fixture_sdk/platforms/android-36/android.jar" -A "$fixture_output/assets"
python3 - "$fixture_output/unsigned.apk" "$fixture_output/dex/classes.dex" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'a') as apk:
    apk.write(sys.argv[2], 'classes.dex')
PY
if [ ! -f "$fixture_output/test.keystore" ]; then
    "$fixture_jdk/bin/keytool" -genkeypair -noprompt -keystore "$fixture_output/test.keystore" \
        -storepass android -keypass android -alias fixture -keyalg RSA -keysize 2048 -validity 3650 \
        -dname "CN=Ning Playback Test Fixture"
fi
"$fixture_tools/zipalign" -f 4 "$fixture_output/unsigned.apk" "$fixture_output/aligned.apk"
JAVA_HOME="$fixture_jdk" "$fixture_tools/apksigner" sign --ks "$fixture_output/test.keystore" \
    --ks-key-alias fixture --ks-pass pass:android --key-pass pass:android \
    --out "$fixture_output/playback-fixture.apk" "$fixture_output/aligned.apk"
JAVA_HOME="$fixture_jdk" "$fixture_tools/apksigner" verify "$fixture_output/playback-fixture.apk"
printf '%s\n' "$fixture_output/playback-fixture.apk"
