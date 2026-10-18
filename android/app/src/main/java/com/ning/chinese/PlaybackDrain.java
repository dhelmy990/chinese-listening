package com.ning.chinese;

/** Reservations remain visible after stop so storage can drain before service teardown. */
public final class PlaybackDrain {
    private final int limit;
    private int pending;
    private boolean closed;

    public PlaybackDrain(int limit) { this.limit = limit; }
    public synchronized boolean reserve() {
        if (closed || pending >= limit) return false;
        pending++;
        return true;
    }
    public synchronized void complete() {
        if (pending <= 0) throw new IllegalStateException("No pending audio save");
        pending--;
    }
    public synchronized void close() { closed = true; }
    public synchronized int pending() { return pending; }
    public synchronized boolean finished() { return closed && pending == 0; }
}
