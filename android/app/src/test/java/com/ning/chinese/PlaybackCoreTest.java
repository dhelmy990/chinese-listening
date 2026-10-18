package com.ning.chinese;

import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;

/** Runs with plain javac/java; no emulator, model downloads, or Android dependencies. */
public final class PlaybackCoreTest {
    public static void main(String[] args) throws Exception {
        PcmRing ring = new PcmRing(5);
        check(ring.snapshot(5).length == 0, "empty ring");
        ring.append(new short[]{1, 2, 3}, 3);
        check(Arrays.equals(ring.snapshot(2), new short[]{2, 3}), "newest samples");
        ring.append(new short[]{4, 5, 6, 7}, 4);
        check(Arrays.equals(ring.snapshot(99), new short[]{3, 4, 5, 6, 7}), "bounded wrap");
        ring.append(new short[]{8, 9, 10, 11, 12, 13, 14}, 7);
        check(Arrays.equals(ring.snapshot(5), new short[]{10, 11, 12, 13, 14}), "oversized append");
        File dir = Files.createTempDirectory("playback-test").toFile();
        try {
            PlaybackStore initial = new PlaybackStore(dir);
            expectFailure(() -> initial.save(new short[0]), "empty rejected");
            expectFailure(() -> initial.save(new short[100]), "silence rejected");
            expectFailure(() -> initial.save(new short[240001]), "long clips rejected");
            PlaybackStore.Clip clip = initial.save(new short[]{32767, -32768, 256});
            check(clip.seconds == 3.0 / 16000, "duration");
            check(Arrays.equals(initial.read(clip.id), new byte[]{-1, 127, 0, -128, 0, 1}), "PCM16 little endian");
            File partial = new File(dir, "orphan.part");
            Files.write(partial.toPath(), new byte[]{1, 2});
            PlaybackStore store = new PlaybackStore(dir);
            check(!partial.exists(), "partial cleaned on restart");
            check(store.list().size() == 1 && store.list().get(0).id.equals(clip.id), "survives restart");
            check(store.list().get(0).createdAt.endsWith("Z"), "UTC metadata");
            PlaybackStore reopened = store;
            expectFailure(() -> reopened.read("../other"), "read path traversal");
            expectFailure(() -> reopened.ack("../other"), "ack path traversal");
            for (int i = 1; i < PlaybackStore.MAX_CLIPS; i++) store.save(new short[]{123});
            expectFailure(() -> reopened.save(new short[]{123}), "full queue rejects without eviction");
            check(store.list().size() == 24, "bounded queue");
            check(store.read(clip.id).length == 6, "oldest not lost");
            store.ack(clip.id);
            store.ack(clip.id);
            check(store.list().size() == 23, "explicit ack idempotent");
            store.save(new short[]{123});
            check(store.list().size() == 24, "space reclaimed");
        } finally {
            for (File file : dir.listFiles()) file.delete();
            dir.delete();
        }
        System.out.println("PlaybackCoreTest: all checks passed");
    }
    private interface Action { void run() throws Exception; }
    private static void expectFailure(Action action, String label) throws Exception {
        try { action.run(); } catch (IllegalArgumentException | java.io.IOException expected) { return; }
        throw new AssertionError(label);
    }
    private static void check(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
    }
}
