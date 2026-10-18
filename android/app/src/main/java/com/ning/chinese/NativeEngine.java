package com.ning.chinese;

/** CPU-only CTranslate2 inference. Models remain loaded for the process lifetime. */
public final class NativeEngine {
    static {
        System.loadLibrary("ning_inference");
    }

    private NativeEngine() {}

    public static native void loadWhisper(String modelDir, int threads);
    public static native int[] transcribe(float[] mel, int frames, int[] prompt);
    public static native void loadTranslator(String modelDir, int threads);
    public static native String[] translate(String[] sourceTokens);
    public static native String translateText(String text);
}
