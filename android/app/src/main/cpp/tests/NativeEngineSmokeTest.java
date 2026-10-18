import com.ning.chinese.NativeEngine;
import java.io.DataInputStream;
import java.io.FileInputStream;
import java.util.Arrays;

/** Run with Android app_process and the built JNI library on its library path. */
public final class NativeEngineSmokeTest {
    private static void rejects(Runnable call) {
        try { call.run(); }
        catch (IllegalStateException expected) { return; }
        throw new AssertionError("Invalid input was accepted");
    }

    public static void main(String[] args) throws Exception {
        int[] prompt = {50258, 50260, 50360, 50364};
        float[] mel = new float[128 * 3000];
        rejects(() -> NativeEngine.loadWhisper(null, 2));
        rejects(() -> NativeEngine.loadTranslator("", 2));
        rejects(() -> NativeEngine.loadWhisper("/missing", 0));
        rejects(() -> NativeEngine.loadTranslator("/missing", 33));
        rejects(() -> NativeEngine.transcribe(null, 3000, prompt));
        rejects(() -> NativeEngine.transcribe(new float[0], 3000, prompt));
        rejects(() -> NativeEngine.transcribe(mel, 3000, new int[] {-1}));
        rejects(() -> NativeEngine.transcribe(mel, 3000, new int[] {51866}));
        rejects(() -> NativeEngine.transcribe(mel, 3000, new int[448]));
        mel[0] = Float.NaN;
        rejects(() -> NativeEngine.transcribe(mel, 3000, prompt));
        mel[0] = 0;
        rejects(() -> NativeEngine.transcribe(mel, 3000, prompt));
        rejects(() -> NativeEngine.translate(null));
        rejects(() -> NativeEngine.translate(new String[513]));
        rejects(() -> NativeEngine.translate(new String[] {null}));
        rejects(() -> NativeEngine.translate(new String[] {""}));
        rejects(() -> NativeEngine.translate(new String[] {"▁你好", "</s>"}));
        rejects(() -> NativeEngine.translateText(null));
        rejects(() -> NativeEngine.translateText(""));
        rejects(() -> NativeEngine.translateText("你好"));
        System.out.println("JNI malformed-input and unloaded-model checks passed");

        if (args.length > 0) {
            NativeEngine.loadTranslator(args[0], 2);
            NativeEngine.loadTranslator(args[0], 2);
            String[] result = NativeEngine.translate(new String[] {"▁你好", "</s>"});
            if (!Arrays.equals(result, new String[] {"▁Hello", "."}))
                throw new AssertionError("Unexpected translation: " + Arrays.toString(result));
            String text = NativeEngine.translateText("你好");
            if (!"Hello.".equals(text)) throw new AssertionError("Unexpected text translation: " + text);
            String longText = String.join("", java.util.Collections.nCopies(600, "你好 "));
            rejects(() -> NativeEngine.translateText(longText));
            rejects(() -> NativeEngine.loadTranslator("/different-model", 2));
            System.out.println("Local OPUS-MT FP32 tokens and native SentencePiece text translation passed: Hello.");
        }
        if (args.length > 2) {
            try (DataInputStream input = new DataInputStream(new FileInputStream(args[2]))) {
                for (int i = 0; i < mel.length; i++) mel[i] = input.readFloat();
            }
            NativeEngine.loadWhisper(args[1], 2);
            int[] tokens = NativeEngine.transcribe(mel, 3000, prompt);
            if (tokens.length == 0) throw new AssertionError("Speech fixture returned no tokens");
            for (int token : tokens) {
                if (token < 0 || token >= 50257) throw new AssertionError("Non-text output token: " + token);
            }
            System.out.println("Local Turbo INT8 transcription token IDs: " + Arrays.toString(tokens));
        }
    }
}
