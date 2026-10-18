package com.ning.chinese;

/** Keeps only the most recent PCM samples; snapshots never share the writer's buffer. */
public final class PcmRing {
    private final short[] samples;
    private int next;
    private int size;

    public PcmRing(int capacity) {
        if (capacity <= 0) throw new IllegalArgumentException("Invalid ring capacity");
        samples = new short[capacity];
    }
    public synchronized void append(short[] input, int count) {
        if (count < 0 || count > input.length) throw new IllegalArgumentException("Invalid sample count");
        for (int i = Math.max(0, count - samples.length); i < count; i++) {
            samples[next] = input[i];
            next = (next + 1) % samples.length;
        }
        size = Math.min(samples.length, size + count);
    }
    public synchronized short[] snapshot(int count) {
        count = Math.min(size, Math.max(0, count));
        short[] result = new short[count];
        int start = (next - count + samples.length) % samples.length;
        for (int i = 0; i < count; i++) result[i] = samples[(start + i) % samples.length];
        return result;
    }
}
