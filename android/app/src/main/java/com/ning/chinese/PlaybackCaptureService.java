package com.ning.chinese;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioPlaybackCaptureConfiguration;
import android.media.AudioRecord;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Captures eligible app playback only. No microphone source or video display is created. */
@android.annotation.TargetApi(29)
public final class PlaybackCaptureService extends Service {
    public static final String STOP = "com.ning.chinese.STOP_PLAYBACK";
    private static final String CHANNEL = "device_audio";
    private static final int NOTIFICATION = 21;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService saves = Executors.newSingleThreadExecutor();
    private final PlaybackDrain drain = new PlaybackDrain(PlaybackStore.MAX_CLIPS);
    private final PcmRing ring = new PcmRing(PlaybackStore.SAMPLE_RATE * PlaybackStore.MAX_SECONDS);
    private ListeningApplication app;
    private MediaProjection projection;
    private AudioRecord recorder;
    private Thread reader;
    private volatile boolean reading;
    private volatile boolean closing;
    private long generation;
    private double factor = 2;
    private WindowManager windows;
    private LinearLayout overlay;
    private TextView status;
    private Button hold;
    private long heldAt;
    private boolean holding;
    private double releasedSeconds = 1;
    private final MediaProjection.Callback revoked = new MediaProjection.Callback() {
        @Override public void onStop() {
            if (!closing) {
                app.failAudio(generation, "Device audio sharing stopped. Start device audio again to continue.");
                finishCapture();
            }
        }
    };

    @Override public void onCreate() {
        super.onCreate();
        app = (ListeningApplication) getApplication();
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || STOP.equals(intent.getAction())) {
            app.cancelAudio();
            finishCapture();
            return START_NOT_STICKY;
        }
        if (reading) return START_NOT_STICKY;
        generation = intent.getLongExtra("generation", -1);
        if (Build.VERSION.SDK_INT < 29 || generation != app.audioGeneration || !app.audioRequesting) {
            stopSelf();
            return START_NOT_STICKY;
        }
        factor = intent.getDoubleExtra("factor", 2);
        try {
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Device audio capture", NotificationManager.IMPORTANCE_LOW));
            startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
            Intent grant = intent.getParcelableExtra("grant");
            projection = getSystemService(MediaProjectionManager.class).getMediaProjection(
                intent.getIntExtra("result", 0), grant);
            if (projection == null) throw new IllegalStateException("Audio sharing permission expired");
            projection.registerCallback(revoked, main);
            AudioPlaybackCaptureConfiguration config = new AudioPlaybackCaptureConfiguration.Builder(projection)
                .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                .addMatchingUsage(AudioAttributes.USAGE_GAME)
                .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
                .excludeUid(android.os.Process.myUid()).build();
            int minimum = AudioRecord.getMinBufferSize(PlaybackStore.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException("16 kHz playback capture is unavailable on this device");
            if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED)
                throw new SecurityException("Audio permission was revoked. Allow audio access and try again.");
            recorder = new AudioRecord.Builder().setAudioPlaybackCaptureConfig(config)
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(PlaybackStore.SAMPLE_RATE)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build())
                .setBufferSizeInBytes(Math.max(minimum * 2, 8192)).build();
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("Cannot initialize device audio");
            recorder.startRecording();
            if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException("Cannot start device audio");
            synchronized (app) {
                if (generation != app.audioGeneration) { finishCapture(); return START_NOT_STICKY; }
                reading = true;
                app.audioService = this;
                app.audioRunning = true;
                app.audioRequesting = false;
                app.audioError = null;
            }
            AudioRecord active = recorder;
            reader = new Thread(() -> readAudio(active), "playback-audio");
            reader.start();
            if (intent.getBooleanExtra("overlay", false) && Settings.canDrawOverlays(this)) showOverlay();
        } catch (RuntimeException error) {
            app.failAudio(generation, "Cannot start device audio: " + error.getMessage());
            finishCapture();
        }
        return START_NOT_STICKY;
    }
    private Notification notification() {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, PlaybackCaptureService.class).setAction(STOP),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.app_icon)
            .setContentTitle("Device audio is ready")
            .setContentText("Hold the floating button to save recent audio. Tap to open the app.")
            .setContentIntent(open).setOngoing(true)
            .addAction(new Notification.Action.Builder(null, "Open app", open).build())
            .addAction(new Notification.Action.Builder(null, "Stop", stop).build()).build();
    }
    private void readAudio(AudioRecord active) {
        short[] buffer = new short[2048];
        try {
            while (reading) {
                int count = active.read(buffer, 0, buffer.length, AudioRecord.READ_BLOCKING);
                if (count > 0) ring.append(buffer, count);
                else if (count < 0 && reading) throw new IllegalStateException("Device audio read failed (" + count + ")");
            }
        } catch (RuntimeException error) {
            if (reading) main.post(() -> {
                app.failAudio(generation, "Device audio stopped: " + error.getMessage());
                finishCapture();
            });
        }
    }
    public int pendingSaves() { return drain.pending(); }
    public void requestStop() { finishCapture(); }

    public synchronized void capture(double seconds) {
        if (!Double.isFinite(seconds) || seconds <= 0) { app.audioError = "Invalid capture duration."; return; }
        synchronized (app) {
            if (!reading || closing || generation != app.audioGeneration) {
                app.audioError = "Start device audio before capturing a clip."; return;
            }
            if (!drain.reserve()) {
                app.audioError = "Audio saves are busy. Open the app before capturing more.";
                main.post(() -> setStatus(app.audioError)); return;
            }
        }
        short[] snapshot = ring.snapshot((int) (Math.min(15, seconds) * PlaybackStore.SAMPLE_RATE));
        main.post(() -> setStatus("Saving clip…"));
        saves.execute(() -> {
            try {
                PlaybackStore.Clip clip = app.playbackStore().save(snapshot);
                if (app.audioService == this && !closing && generation == app.audioGeneration) app.audioError = null;
                main.post(() -> setStatus(String.format(Locale.US, "Saved %.1fs · Open app to review", clip.seconds)));
            } catch (Exception error) {
                // Explicit stop changes generation; failures of accepted saves must still be visible.
                if (app.audioService == this) app.audioError = error.getMessage();
                main.post(() -> setStatus(error.getMessage()));
            } finally {
                drain.complete();
                main.post(this::finishWhenDrained);
            }
        });
    }
    private double duration() { return Math.min(15, 1 + (SystemClock.elapsedRealtime() - heldAt) / 1000.0 * factor); }
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (!holding || hold == null) return;
            hold.setText(String.format(Locale.US, "Release · %.1fs", duration()));
            main.postDelayed(this, 80);
        }
    };
    private void setStatus(String text) { if (status != null) status.setText(text); }
    private void showOverlay() {
        windows = getSystemService(WindowManager.class);
        overlay = new LinearLayout(this);
        overlay.setOrientation(LinearLayout.VERTICAL);
        overlay.setPadding(dp(8), dp(4), dp(8), dp(6));
        overlay.setBackgroundColor(Color.rgb(25, 41, 34));
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(dp(232), -2,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.START;
        params.x = dp(12); params.y = dp(100);
        TextView drag = new TextView(this);
        drag.setText("⠿  Move audio button"); drag.setTextColor(Color.WHITE);
        drag.setPadding(dp(8), dp(12), dp(8), dp(12));
        drag.setContentDescription("Drag to move audio controls");
        drag.setOnTouchListener(new View.OnTouchListener() {
            float x, y; int left, top;
            @Override public boolean onTouch(View view, MotionEvent event) {
                if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
                    x = event.getRawX(); y = event.getRawY(); left = params.x; top = params.y;
                } else if (event.getActionMasked() == MotionEvent.ACTION_MOVE) {
                    params.x = Math.max(0, Math.min(getResources().getDisplayMetrics().widthPixels - overlay.getWidth(), left + (int) (event.getRawX() - x)));
                    params.y = Math.max(0, Math.min(getResources().getDisplayMetrics().heightPixels - overlay.getHeight(), top + (int) (event.getRawY() - y)));
                    windows.updateViewLayout(overlay, params);
                }
                return true;
            }
        });
        overlay.addView(drag);
        hold = new Button(this);
        hold.setText("Hold to capture");
        hold.setContentDescription("Hold to capture recent device audio; slide outside to cancel");
        hold.setOnClickListener(view -> { capture(releasedSeconds); releasedSeconds = 1; });
        hold.setOnTouchListener((view, event) -> {
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    heldAt = SystemClock.elapsedRealtime(); holding = true;
                    setStatus("Slide outside to cancel · max 15s"); tick.run(); return true;
                case MotionEvent.ACTION_MOVE:
                    if (event.getX() < 0 || event.getY() < 0 || event.getX() > view.getWidth() || event.getY() > view.getHeight()) cancelHold();
                    return true;
                case MotionEvent.ACTION_UP:
                    if (holding) { releasedSeconds = duration(); cancelHold(); view.performClick(); }
                    return true;
                case MotionEvent.ACTION_POINTER_DOWN:
                case MotionEvent.ACTION_CANCEL: cancelHold(); return true;
                default: return true;
            }
        });
        overlay.addView(hold);
        status = new TextView(this);
        status.setTextColor(Color.WHITE); status.setTextSize(12);
        status.setPadding(dp(8), dp(4), dp(8), dp(4));
        status.setText("Captures the last 1–15 seconds");
        overlay.addView(status);
        LinearLayout actions = new LinearLayout(this);
        Button open = new Button(this); open.setText("Open app");
        open.setOnClickListener(view -> startActivity(new Intent(this, MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)));
        Button stop = new Button(this); stop.setText("Stop");
        stop.setOnClickListener(view -> { app.cancelAudio(); finishCapture(); });
        actions.addView(open, new LinearLayout.LayoutParams(0, -2, 1));
        actions.addView(stop, new LinearLayout.LayoutParams(0, -2, 1));
        overlay.addView(actions);
        try { windows.addView(overlay, params); }
        catch (RuntimeException error) {
            overlay = null;
            app.audioError = "Floating button unavailable. Return to the app to capture audio.";
        }
    }
    private int dp(int value) { return (int) (value * getResources().getDisplayMetrics().density + 0.5f); }
    private void cancelHold() {
        holding = false; main.removeCallbacks(tick);
        if (hold != null) hold.setText("Hold to capture");
        setStatus("Capture canceled · hold to try again");
    }
    private void finishCapture() { release(); finishWhenDrained(); }
    private void finishWhenDrained() {
        if (!drain.finished()) return;
        synchronized (app) { if (app.audioService == this) app.audioService = null; }
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }
    private synchronized void release() {
        if (closing) return;
        closing = true;
        drain.close();
        reading = false;
        cancelHold();
        if (recorder != null) {
            try { recorder.stop(); } catch (RuntimeException ignored) { }
            // stop unblocks read; join before release avoids using a released native recorder.
            if (reader != null) try { reader.join(1000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            try { recorder.release(); } catch (RuntimeException ignored) { }
            recorder = null;
        }
        if (projection != null) {
            try { projection.unregisterCallback(revoked); } catch (RuntimeException ignored) { }
            try { projection.stop(); } catch (RuntimeException ignored) { }
            projection = null;
        }
        if (overlay != null) {
            try { windows.removeView(overlay); } catch (RuntimeException ignored) { }
            overlay = null;
        }
        status = null; hold = null;
        synchronized (app) {
            if (app.audioGeneration == generation) { app.audioRunning = false; app.audioRequesting = false; }
        }
        saves.shutdown();
    }
    @Override public void onDestroy() {
        release();
        synchronized (app) { if (app.audioService == this && drain.finished()) app.audioService = null; }
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
