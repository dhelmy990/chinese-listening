package com.ning.playbackfixture;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Bundle;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;

/** Test-only other-app source for device audio capture; never bundled into Chinese listening. */
public final class PlaybackFixtureActivity extends Activity {
    private AudioTrack track;
    private TextView status;
    private byte[] samples;
    private boolean allowed = true;
    private boolean requested;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 80, 32, 32);
        root.setBackgroundColor(Color.rgb(18, 28, 42));
        TextView title = new TextView(this);
        title.setText("Mandarin playback fixture");
        title.setTextSize(25); title.setTextColor(Color.WHITE);
        root.addView(title);
        status = new TextView(this);
        status.setTextColor(Color.WHITE); status.setTextSize(18);
        status.setPadding(0, 32, 0, 32);
        root.addView(status);
        Button allow = new Button(this); allow.setText("Play — capture allowed");
        allow.setOnClickListener(view -> { allowed = true; requested = true; play(); });
        root.addView(allow);
        Button block = new Button(this); block.setText("Play — capture blocked");
        block.setOnClickListener(view -> { allowed = false; requested = true; play(); });
        root.addView(block);
        Button stop = new Button(this); stop.setText("Stop playback");
        stop.setOnClickListener(view -> { requested = false; stopTrack(); status.setText("Stopped"); });
        root.addView(stop);
        setContentView(root);
        try (InputStream input = getAssets().open("mandarin.pcm"); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            for (int count; (count = input.read(buffer)) != -1;) output.write(buffer, 0, count);
            samples = output.toByteArray();
            if (samples.length == 0 || samples.length % 2 != 0) throw new IllegalStateException("Invalid fixture PCM");
            status.setText("Ready · 16 kHz mono Mandarin loops while this Activity is visible");
            applyIntent(getIntent());
        } catch (Exception error) { status.setText("Fixture error: " + error.getMessage()); }
    }
    private void applyIntent(Intent intent) {
        allowed = intent.getBooleanExtra("allowCapture", true);
        requested = intent.getBooleanExtra("autoplay", false);
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        applyIntent(intent);
        if (requested) play();
        else { stopTrack(); status.setText("Stopped"); }
    }
    @Override protected void onResume() {
        super.onResume();
        if (requested) play();
    }
    private void play() {
        stopTrack();
        if (samples == null) return;
        try {
            AudioAttributes attributes = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .setAllowedCapturePolicy(allowed ? AudioAttributes.ALLOW_CAPTURE_BY_ALL : AudioAttributes.ALLOW_CAPTURE_BY_NONE)
                .build();
            track = new AudioTrack.Builder().setAudioAttributes(attributes)
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(16000)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setTransferMode(AudioTrack.MODE_STATIC).setBufferSizeInBytes(samples.length).build();
            if (track.write(samples, 0, samples.length) != samples.length) throw new IllegalStateException("Incomplete fixture write");
            if (track.setLoopPoints(0, samples.length / 2, -1) != AudioTrack.SUCCESS) throw new IllegalStateException("Cannot loop fixture");
            track.play();
            status.setText("Playing Mandarin · capture " + (allowed ? "ALLOWED" : "BLOCKED")
                + "\n5.55-second loop · 16 kHz mono · USAGE_MEDIA");
        } catch (RuntimeException error) { stopTrack(); status.setText("Playback error: " + error.getMessage()); }
    }
    private void stopTrack() {
        if (track == null) return;
        try { track.stop(); } catch (IllegalStateException ignored) { }
        track.release(); track = null;
    }
    @Override protected void onStop() { stopTrack(); super.onStop(); }
    @Override protected void onDestroy() { stopTrack(); super.onDestroy(); }
}
