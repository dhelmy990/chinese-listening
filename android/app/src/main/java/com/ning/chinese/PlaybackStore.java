package com.ning.chinese;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.UUID;

/** Atomic private spool for process-restart recovery; no power-loss durability guarantee. */
public final class PlaybackStore {
    public static final int SAMPLE_RATE = 16000;
    public static final int MAX_SECONDS = 15;
    public static final int MAX_CLIPS = 24;
    private final File directory;

    public static final class Clip {
        public final String id;
        public final double seconds;
        public final String createdAt;
        private Clip(File file) {
            id = file.getName().substring(0, file.getName().length() - 4);
            seconds = file.length() / (2.0 * SAMPLE_RATE);
            SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
            format.setTimeZone(TimeZone.getTimeZone("UTC"));
            createdAt = format.format(new Date(Long.parseLong(id.substring(0, 13))));
        }
    }
    public PlaybackStore(File directory) throws IOException {
        this.directory = directory;
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Cannot create audio storage");
        File[] files = directory.listFiles();
        if (files == null) throw new IOException("Cannot read audio storage");
        for (File file : files) if (file.getName().endsWith(".part")) file.delete();
    }
    private static boolean validId(String id) {
        return id != null && id.matches("[0-9]{13}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    }
    private File file(String id) {
        if (!validId(id)) throw new IllegalArgumentException("Invalid clip ID");
        return new File(directory, id + ".pcm");
    }
    public synchronized List<Clip> list() throws IOException {
        File[] files = directory.listFiles();
        if (files == null) throw new IOException("Cannot read audio storage");
        List<Clip> clips = new ArrayList<>();
        for (File file : files) {
            String name = file.getName();
            if (name.endsWith(".pcm") && validId(name.substring(0, name.length() - 4))
                && file.isFile() && file.length() > 0 && file.length() <= SAMPLE_RATE * MAX_SECONDS * 2
                && file.length() % 2 == 0) clips.add(new Clip(file));
        }
        clips.sort(Comparator.comparing(clip -> clip.id));
        return clips;
    }
    public synchronized Clip save(short[] samples) throws IOException {
        if (samples.length > SAMPLE_RATE * MAX_SECONDS) throw new IllegalArgumentException("Clip exceeds 15 seconds");
        boolean signal = false;
        for (short value : samples) if (Math.abs((int) value) > 8) { signal = true; break; }
        if (!signal) throw new IOException("No device audio captured. Play audio and try again; the source may block capture.");
        if (list().size() >= MAX_CLIPS) throw new IOException("24 clips are waiting. Open the app to save them before capturing more.");
        String id = System.currentTimeMillis() + "-" + UUID.randomUUID();
        File pending = new File(directory, id + ".part");
        File committed = file(id);
        byte[] bytes = new byte[samples.length * 2];
        for (int i = 0; i < samples.length; i++) {
            bytes[i * 2] = (byte) samples[i];
            bytes[i * 2 + 1] = (byte) (samples[i] >>> 8);
        }
        try {
            try (FileOutputStream output = new FileOutputStream(pending)) {
                output.write(bytes);
                output.getFD().sync();
            }
            if (!pending.renameTo(committed)) throw new IOException("Cannot save captured audio");
            return new Clip(committed);
        } finally { pending.delete(); }
    }
    public synchronized byte[] read(String id) throws IOException {
        File source = file(id);
        long length = source.length();
        if (!source.isFile() || length <= 0 || length > SAMPLE_RATE * MAX_SECONDS * 2 || length % 2 != 0)
            throw new IOException("Saved clip is missing or invalid");
        byte[] bytes = new byte[(int) length];
        try (FileInputStream input = new FileInputStream(source)) {
            int offset = 0;
            while (offset < bytes.length) {
                int count = input.read(bytes, offset, bytes.length - offset);
                if (count < 0) throw new IOException("Incomplete saved clip");
                offset += count;
            }
        }
        return bytes;
    }
    public synchronized void ack(String id) throws IOException {
        File source = file(id);
        if (source.exists() && !source.delete()) throw new IOException("Cannot acknowledge saved clip");
    }
}
