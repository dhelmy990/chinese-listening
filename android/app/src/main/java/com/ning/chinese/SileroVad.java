package com.ning.chinese;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import java.util.HashMap;
import java.util.Map;

/** The faster-whisper Silero v6 graph, with state scoped to one padded 16 kHz clip. */
public final class SileroVad {
    private static OrtEnvironment environment;
    private static OrtSession session;
    private static String loadedPath;

    private SileroVad() {}

    public static synchronized float[] probabilities(String modelPath, float[] pcm) {
        if (modelPath == null || modelPath.isEmpty() || pcm == null || pcm.length % 512 != 0)
            throw new IllegalStateException("VAD requires a model path and PCM padded to 512 samples");
        for (float sample : pcm) {
            if (!Float.isFinite(sample)) throw new IllegalStateException("PCM must be finite");
        }
        if (pcm.length == 0) return new float[0];
        try {
            if (session == null) {
                environment = OrtEnvironment.getEnvironment();
                try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
                    options.setInterOpNumThreads(1);
                    options.setIntraOpNumThreads(1);
                    options.setCPUArenaAllocator(false);
                    session = environment.createSession(modelPath, options);
                }
                loadedPath = modelPath;
            } else if (!loadedPath.equals(modelPath)) {
                throw new IllegalStateException("VAD is already loaded from another path");
            }

            int windows = pcm.length / 512;
            float[] probabilities = new float[windows];
            float[][][] h = new float[1][1][128];
            float[][][] c = new float[1][1][128];
            for (int start = 0; start < windows; start += 10000) {
                int count = Math.min(10000, windows - start);
                float[][] batch = new float[count][576];
                for (int i = 0; i < count; i++) {
                    int offset = (start + i) * 512;
                    if (offset > 0) System.arraycopy(pcm, offset - 64, batch[i], 0, 64);
                    System.arraycopy(pcm, offset, batch[i], 64, 512);
                }
                try (OnnxTensor input = OnnxTensor.createTensor(environment, batch);
                     OnnxTensor hidden = OnnxTensor.createTensor(environment, h);
                     OnnxTensor cell = OnnxTensor.createTensor(environment, c)) {
                    Map<String, OnnxTensor> inputs = new HashMap<>();
                    inputs.put("input", input);
                    inputs.put("h", hidden);
                    inputs.put("c", cell);
                    try (OrtSession.Result result = session.run(inputs)) {
                        float[] output = (float[]) result.get(0).getValue();
                        if (output.length != count) throw new IllegalStateException("Invalid VAD output length");
                        for (float probability : output) {
                            if (!Float.isFinite(probability))
                                throw new IllegalStateException("VAD returned a non-finite probability");
                        }
                        System.arraycopy(output, 0, probabilities, start, count);
                        h = (float[][][]) result.get(1).getValue();
                        c = (float[][][]) result.get(2).getValue();
                    }
                }
            }
            return probabilities;
        } catch (OrtException error) {
            throw new IllegalStateException("Silero VAD inference failed", error);
        }
    }
}
