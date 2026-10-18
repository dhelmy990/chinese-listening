import com.ning.chinese.SileroVad;
import java.io.DataInputStream;
import java.io.FileInputStream;

/** Runs on a host JVM with the desktop ONNX Runtime jar and the real bundled v6 model. */
public final class SileroVadTest {
    private static void rejects(Runnable call) {
        try { call.run(); }
        catch (IllegalStateException expected) { return; }
        throw new AssertionError("Invalid input was accepted");
    }

    public static void main(String[] args) throws Exception {
        String model = args[0];
        rejects(() -> SileroVad.probabilities(model, null));
        rejects(() -> SileroVad.probabilities(model, new float[513]));
        float[] invalid = new float[512];
        invalid[2] = Float.NaN;
        rejects(() -> SileroVad.probabilities(model, invalid));
        invalid[2] = Float.POSITIVE_INFINITY;
        rejects(() -> SileroVad.probabilities(model, invalid));
        if (SileroVad.probabilities(model, new float[0]).length != 0)
            throw new AssertionError("Empty PCM must produce no windows");
        try (DataInputStream input = new DataInputStream(new FileInputStream(args[1]))) {
            float[] pcm = new float[input.readInt()];
            for (int i = 0; i < pcm.length; i++) pcm[i] = input.readFloat();
            float[] expected = new float[pcm.length / 512];
            for (int i = 0; i < expected.length; i++) expected[i] = input.readFloat();
            float[] actual = SileroVad.probabilities(model, pcm);
            SileroVad.probabilities(model, new float[512]);
            float[] repeated = SileroVad.probabilities(model, pcm);
            if (actual.length != expected.length) throw new AssertionError("Wrong window count");
            for (int i = 0; i < expected.length; i++) {
                if (Math.abs(actual[i] - expected[i]) > 1e-5f)
                    throw new AssertionError("Upstream probability differs at window " + i);
                if (actual[i] != repeated[i]) throw new AssertionError("State leaked between clips");
            }
        }
        System.out.println("Silero probabilities match upstream; state reset and invalid inputs passed");
    }
}
