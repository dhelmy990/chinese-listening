# Native inference checks

Run from the repository root. The C++ boundary checks need only a host C++17 compiler:

```sh
c++ -std=c++17 -Wall -Wextra -Werror android/app/src/main/cpp/tests/native_input_test.cpp -o /tmp/ning-native-input-test
/tmp/ning-native-input-test
```

For the real-model VAD comparison, put the Maven artifact
`com.microsoft.onnxruntime:onnxruntime:1.20.0` at `/tmp/ning-onnxruntime-1.20.0.jar`
and use a JDK on `PATH`. This desktop test artifact covers the Java API used by the
app's `onnxruntime-android` dependency. The 10001-window fixture crosses the
upstream encoder batch boundary; the Java test compares every probability,
checks recurrent-state reset, and rejects non-finite or unpadded PCM.

```sh
whisper-live/.venv/bin/python android/app/src/main/cpp/tests/make_vad_fixture.py /tmp/ning-vad.bin
javac -cp /tmp/ning-onnxruntime-1.20.0.jar -d /tmp/ning-java-tests android/app/src/main/java/com/ning/chinese/SileroVad.java android/app/src/main/cpp/tests/SileroVadTest.java
java -cp /tmp/ning-java-tests:/tmp/ning-onnxruntime-1.20.0.jar SileroVadTest whisper-live/.venv/lib/python3.13/site-packages/faster_whisper/assets/silero_vad_v6.onnx /tmp/ning-vad.bin
```

`NativeEngineSmokeTest.java` runs on Android with `app_process`; compile it with
`NativeEngine.java`, dex both with the SDK's `d8`, and push that dex JAR together
with the matching ABI's `libning_inference.so` and `libc++_shared.so` to a test
directory. Set `CLASSPATH` to the JAR and pass `-Djava.library.path=<test-directory>`
to `app_process`. With no arguments it checks JNI validation and unloaded-model
errors. Pass an OPUS-MT model directory (including `source.spm` and `target.spm`)
to verify both token-array translation and `translateText("你好")`, including the
512-token limit after encoding and appending EOS. Also pass
a Turbo model directory and a file of 128×3000 big-endian float32 mel features
to verify actual transcription. Models must be readable by the test process.

The CMake build pins CTranslate2 v4.6.0 by commit, recursively fetches its CPU
dependencies, uses static PIC libraries with Ruy for INT8/FP32, and links the JNI
library with 16 KB ELF alignment and `NODELETE` so runtime thread-local cleanup
cannot call into an unloaded library. NDK 27.2 and CMake 3.22.1 are configured by the
app. A generated build-tree copy of `thread_pool.cc` disables unsupported Android
thread affinity without changing the downloaded source. Full APK page-size support
also depends on the separately packaged Python, ONNX Runtime, and C++ libraries.

SentencePiece v0.2.1 is pinned by commit and linked statically with PIC into the
same JNI library. Only its inference library is built; shared libraries, tests,
TCMalloc, training, and CLI targets are excluded. The source and target tokenizers
load once with OPUS-MT, so Python requires no SentencePiece extension wheel.
