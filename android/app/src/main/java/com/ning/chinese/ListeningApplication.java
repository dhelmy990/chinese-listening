package com.ning.chinese;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.security.SecureRandom;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;

/** One backend per process, retained across Activity recreation. */
public final class ListeningApplication extends Application {
    public interface Observer { void changed(); }
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    public volatile String message = "First setup downloads about 1.8 GB. Use Wi-Fi and keep this app open. Models stay on this device for offline use.";
    public volatile String url;
    public volatile boolean running;
    public volatile boolean failed;
    public String token;
    public Observer observer;
    public volatile boolean audioRunning;
    public volatile boolean audioRequesting;
    public volatile String audioError;
    public volatile long audioGeneration;
    public volatile PlaybackCaptureService audioService;
    private PlaybackStore playbackStore;

    public synchronized PlaybackStore playbackStore() throws java.io.IOException {
        if (playbackStore == null) playbackStore = new PlaybackStore(new File(getFilesDir(), "playback-clips"));
        return playbackStore;
    }

    public synchronized long beginAudioRequest() {
        if (audioRunning || audioRequesting || audioService != null) return -1;
        audioRequesting = true;
        audioError = null;
        return ++audioGeneration;
    }

    public synchronized void cancelAudio() {
        ++audioGeneration;
        audioRequesting = false;
        audioRunning = false;
    }

    public synchronized void failAudio(long generation, String error) {
        if (audioGeneration != generation) return;
        audioRequesting = false;
        audioError = error;
    }

    @Override public void onCreate() {
        super.onCreate();
        byte[] bytes = new byte[32];
        new SecureRandom().nextBytes(bytes);
        StringBuilder result = new StringBuilder();
        for (byte value : bytes) result.append(String.format("%02x", value & 255));
        token = result.toString();
    }

    public boolean hasModels() {
        return new File(getFilesDir(), "models/whisper/model.bin").isFile()
            && new File(getFilesDir(), "models/translation/model.bin").isFile();
    }

    public synchronized void start() {
        if (running || url != null) return;
        running = true;
        failed = false;
        update("Preparing offline app…");
        worker.execute(() -> {
            try {
                copyAssets("web", new File(getFilesDir(), "web"));
                copyAssets("silero_vad_v6.onnx", new File(getFilesDir(), "silero_vad_v6.onnx"));
                if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
                url = Python.getInstance().getModule("ning_android.bootstrap")
                    .callAttr("start", getFilesDir().getAbsolutePath(), token, this).toString();
                update("Ready");
            } catch (Exception | LinkageError error) {
                failed = true;
                update("Setup could not finish: " + error.getMessage());
            } finally {
                running = false;
                notifyObserver();
            }
        });
    }

    // Called by Python on its worker thread; never touch Android views there.
    public void update(String value) { message = value; notifyObserver(); }

    private void notifyObserver() {
        main.post(() -> { if (observer != null) observer.changed(); });
    }

    private void copyAssets(String name, File destination) throws Exception {
        String[] children = getAssets().list(name);
        if (children != null && children.length > 0) {
            if (!destination.isDirectory() && !destination.mkdirs()) throw new Exception("Cannot create app storage");
            for (String child : children) copyAssets(name + "/" + child, new File(destination, child));
        } else {
            try (InputStream input = getAssets().open(name); FileOutputStream output = new FileOutputStream(destination)) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            }
        }
    }
}
