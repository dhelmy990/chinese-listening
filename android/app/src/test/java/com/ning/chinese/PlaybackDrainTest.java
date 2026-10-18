package com.ning.chinese;

/** A stopped capture keeps its pending writes visible until the final write completes. */
public final class PlaybackDrainTest {
    public static void main(String[] args) throws Exception {
        PlaybackDrain drain = new PlaybackDrain(24);
        check(drain.reserve() && drain.reserve(), "accept captures before stop");
        drain.close();
        check(drain.pending() == 2 && !drain.finished(), "stop retains pending writes and service");
        check(!drain.reserve(), "stop rejects new captures");
        drain.complete();
        check(drain.pending() == 1 && !drain.finished(), "first delayed write does not finish stop");
        drain.complete();
        check(drain.pending() == 0 && drain.finished(), "final delayed write allows teardown");
        PlaybackDrain full = new PlaybackDrain(1);
        check(full.reserve() && !full.reserve(), "pending memory bounded");
        full.complete();
        check(!full.finished() && full.reserve(), "running service can accept next capture");
        PlaybackDrain delayed = new PlaybackDrain(24);
        java.util.concurrent.CountDownLatch writeAllowed = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch written = new java.util.concurrent.CountDownLatch(1);
        check(delayed.reserve(), "reserve synchronously before save worker starts");
        Thread writer = new Thread(() -> {
            try { writeAllowed.await(); }
            catch (InterruptedException error) { throw new AssertionError(error); }
            delayed.complete();
            written.countDown();
        });
        writer.start();
        delayed.close();
        check(delayed.pending() == 1 && !delayed.finished(), "stop cannot hide a delayed save");
        writeAllowed.countDown();
        check(written.await(2, java.util.concurrent.TimeUnit.SECONDS), "save worker completes");
        check(delayed.pending() == 0 && delayed.finished(), "drained stop becomes visible across threads");
        writer.join();
        System.out.println("PlaybackDrainTest: all checks passed");
    }
    private static void check(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }
}
