package com.ning.chinese;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.widget.EditText;
import android.text.InputType;
import android.content.pm.PackageManager;
import android.content.Intent;
import android.media.projection.MediaProjectionManager;
import android.media.projection.MediaProjectionConfig;
import android.os.Build;
import android.provider.Settings;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceResponse;
import org.json.JSONArray;
import org.json.JSONObject;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private ListeningApplication app;
    private WebView web;
    private TextView progress;
    private Button setup;
    private LinearLayout root;
    private PermissionRequest microphoneRequest;
    private boolean showingApp;
    private boolean foreground = true;
    private long captureFlow;
    private boolean captureOverlay;
    private double captureFactor = 2;
    private static final int AUDIO_PERMISSION = 10, OVERLAY_PERMISSION = 11, PROJECTION_PERMISSION = 12, NOTIFICATION_PERMISSION = 13;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        app = (ListeningApplication) getApplication();
        if (state != null) {
            captureFlow = state.getLong("captureFlow", 0);
            captureOverlay = state.getBoolean("captureOverlay", false);
            captureFactor = state.getDouble("captureFactor", 2);
        }
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(16, 23, 21));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(root);
        TextView title = new TextView(this);
        title.setText("Chinese listening");
        title.setTextSize(27);
        title.setTextColor(Color.rgb(226, 237, 229));
        title.setPadding(24, 32, 24, 16);
        root.addView(title);
        progress = new TextView(this);
        progress.setTextColor(Color.rgb(156, 175, 159));
        progress.setPadding(24, 16, 24, 24);
        root.addView(progress);
        setup = new Button(this);
        setup.setText("Connect to PC server");
        setup.setOnClickListener(view -> configureServer());
        root.addView(setup);
        app.observer = this::render;
        SharedPreferences saved = getSharedPreferences("pc-server", MODE_PRIVATE);
        String address = saved.getString("url", "");
        String token = saved.getString("token", "");
        if (app.url == null && !app.failed && !address.isEmpty() && !token.isEmpty()) app.start(address, token);
        render();
    }

    private void render() {
        if (isFinishing() || isDestroyed()) return;
        if (app.url != null) { if (!showingApp) showApp(); return; }
        progress.setText(app.message);
        setup.setEnabled(!app.running);
        setup.setText(app.failed ? "Check PC connection" : "Connect to PC server");
    }

    private void configureServer() {
        SharedPreferences saved = getSharedPreferences("pc-server", MODE_PRIVATE);
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(28, 12, 28, 12);
        TextView help = new TextView(this);
        help.setText("Run ./home-server --host 0.0.0.0 on your PC. Use its LAN address and access token. Both devices must be on the same trusted network. Audio is sent to the PC; history stays on this phone.");
        form.addView(help);
        EditText address = new EditText(this);
        address.setHint("http://192.168.1.20:8766");
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setSingleLine(true);
        address.setText(saved.getString("url", ""));
        form.addView(address);
        EditText key = new EditText(this);
        key.setHint("Server access token");
        key.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        key.setSingleLine(true);
        key.setText(saved.getString("token", ""));
        form.addView(key);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Connect to PC server")
            .setView(form).setNegativeButton("Cancel", null).setPositiveButton("Connect", null).create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String url = address.getText().toString().trim();
            String token = key.getText().toString().trim();
            Uri uri = Uri.parse(url);
            if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                || !(uri.getPath() == null || uri.getPath().isEmpty() || "/".equals(uri.getPath()))) {
                address.setError("Enter the PC address only, including http:// and port 8766."); return;
            }
            if (token.isEmpty() || token.matches(".*\\s.*")) { key.setError("Enter the server access token."); return; }
            saved.edit().putString("url", url).putString("token", token).apply();
            dialog.dismiss();
            app.start(url, token);
        }));
        dialog.show();
    }

    private boolean local(Uri uri) {
        return "http".equals(uri.getScheme()) && "127.0.0.1".equals(uri.getHost()) && uri.getPort() == 8765;
    }

    @SuppressWarnings("SetJavaScriptEnabled")
    private void showApp() {
        showingApp = true;
        root.removeAllViews();
        web = new WebView(this);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web.setBackgroundColor(Color.rgb(16, 23, 21));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new AndroidAudio(), "AndroidAudio");
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (local(request.getUrl())) return null;
                return new WebResourceResponse("text/plain", "UTF-8", 403, "Local app only",
                    java.util.Collections.emptyMap(), new java.io.ByteArrayInputStream(new byte[0]));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !local(request.getUrl());
            }
            @Override public void onPageFinished(WebView view, String url) {
                updateForeground(foreground);
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) {
                if (!local(request.getOrigin()) || request.getResources().length != 1
                    || !PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(request.getResources()[0])) {
                    request.deny(); return;
                }
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                } else {
                    if (microphoneRequest != null) microphoneRequest.deny();
                    microphoneRequest = request;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
                }
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) {
                if (microphoneRequest == request) microphoneRequest = null;
            }
        });
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(web, false);
        cookies.setCookie(app.url, "ning_session=" + app.token + "; Path=/; HttpOnly; SameSite=Strict", success -> web.loadUrl(app.url));
        root.addView(web, new LinearLayout.LayoutParams(-1, -1));
    }

    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == AUDIO_PERMISSION || code == NOTIFICATION_PERMISSION) {
            if (!currentCaptureFlow()) { captureFlow = 0; return; }
            if (code == AUDIO_PERMISSION && (results.length == 0 || results[0] != PackageManager.PERMISSION_GRANTED)) {
                failCapture("Audio permission was denied. Device audio capture needs audio permission.");
            } else if (code == AUDIO_PERMISSION) requestOverlay();
            else requestProjection();
            return;
        }
        if (code == 1 && microphoneRequest != null) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED)
                microphoneRequest.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            else microphoneRequest.deny();
            microphoneRequest = null;
        }
    }

    /** Only installed on this Activity's restricted local-app WebView. */
    private final class AndroidAudio {
        @JavascriptInterface public void chooseConnection() {
            runOnUiThread(() -> {
                if (app.audioRunning || app.audioRequesting || app.running) return;
                app.url = null;
                app.failed = true;
                app.message = "Update the PC address or access token. Your vocabulary stays on this phone.";
                recreate();
            });
        }

        @JavascriptInterface public String state() {
            JSONObject state = new JSONObject();
            try {
                state.put("supported", Build.VERSION.SDK_INT >= 29);
                state.put("running", app.audioRunning);
                state.put("requesting", app.audioRequesting);
                PlaybackCaptureService service = app.audioService;
                state.put("pendingSaves", service == null ? 0 : service.pendingSaves());
                JSONArray clips = new JSONArray();
                try {
                    for (PlaybackStore.Clip clip : app.playbackStore().list()) {
                        JSONObject item = new JSONObject();
                        item.put("id", clip.id); item.put("seconds", clip.seconds); item.put("createdAt", clip.createdAt);
                        clips.put(item);
                    }
                } catch (Exception error) { app.audioError = "Cannot read saved audio: " + error.getMessage(); }
                state.put("error", app.audioError == null ? JSONObject.NULL : app.audioError);
                state.put("clips", clips);
            } catch (Exception error) { throw new IllegalStateException(error); }
            return state.toString();
        }
        @JavascriptInterface public void requestStart(boolean overlay, double factor) {
            if (Build.VERSION.SDK_INT < 29) { app.audioError = "Device audio requires Android 10 or later."; return; }
            long generation = app.beginAudioRequest();
            if (generation < 0) return;
            double safeFactor = Double.isFinite(factor) && factor >= 0.1 ? factor : 2;
            runOnUiThread(() -> {
                if (generation != app.audioGeneration) return;
                if (captureFlow != 0 || microphoneRequest != null) {
                    app.failAudio(generation, "Finish the current permission prompt, then try device audio again.");
                    return;
                }
                captureFlow = generation; captureOverlay = overlay; captureFactor = safeFactor;
                try {
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION);
                    else requestOverlay();
                } catch (RuntimeException error) { failCapture("Cannot request audio permission: " + error.getMessage()); }
            });
        }
        @JavascriptInterface public void stop() {
            app.cancelAudio();
            runOnUiThread(() -> {
                PlaybackCaptureService service = app.audioService;
                if (service != null) service.requestStop();
                else stopService(new Intent(MainActivity.this, PlaybackCaptureService.class));
            });
        }
        @JavascriptInterface public void capture(double seconds) {
            // Reserve and snapshot before returning so an immediate stop cannot miss this capture.
            PlaybackCaptureService service = app.audioService;
            if (service != null) service.capture(seconds);
            else app.audioError = "Start device audio before capturing a clip.";
        }
        @JavascriptInterface public String readClip(String id) {
            try { return Base64.encodeToString(app.playbackStore().read(id), Base64.NO_WRAP); }
            catch (Exception error) { app.audioError = error.getMessage(); return ""; }
        }
        @JavascriptInterface public void ackClips(String ids) {
            try {
                JSONArray values = new JSONArray(ids);
                if (values.length() > PlaybackStore.MAX_CLIPS) throw new IllegalArgumentException("Too many clip IDs");
                // Validate every value before deleting any clip.
                for (int i = 0; i < values.length(); i++) {
                    Object id = values.get(i);
                    if (!(id instanceof String) || !((String) id).matches("[0-9]{13}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"))
                        throw new IllegalArgumentException("Invalid clip ID");
                }
                for (int i = 0; i < values.length(); i++) app.playbackStore().ack(values.getString(i));
            } catch (Exception error) { app.audioError = "Cannot acknowledge clips: " + error.getMessage(); }
        }
    }
    private boolean currentCaptureFlow() { return captureFlow != 0 && captureFlow == app.audioGeneration && app.audioRequesting; }
    private void failCapture(String error) {
        app.failAudio(captureFlow, error);
        captureFlow = 0;
    }
    private void requestOverlay() {
        if (!currentCaptureFlow()) { captureFlow = 0; return; }
        try {
            if (captureOverlay && !Settings.canDrawOverlays(this)) {
                startActivityForResult(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName())), OVERLAY_PERMISSION);
            } else requestNotifications();
        } catch (RuntimeException error) { failCapture("Cannot open floating-button permission: " + error.getMessage()); }
    }
    private void requestNotifications() {
        if (!currentCaptureFlow()) { captureFlow = 0; return; }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION);
        else requestProjection();
    }
    private void requestProjection() {
        if (!currentCaptureFlow()) { captureFlow = 0; return; }
        try {
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            Intent consent = Build.VERSION.SDK_INT >= 34
                ? manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
                : manager.createScreenCaptureIntent();
            startActivityForResult(consent, PROJECTION_PERMISSION);
        } catch (RuntimeException error) { failCapture("Cannot request device audio sharing: " + error.getMessage()); }
    }
    @Override protected void onActivityResult(int code, int result, Intent data) {
        super.onActivityResult(code, result, data);
        if (code != OVERLAY_PERMISSION && code != PROJECTION_PERMISSION) return;
        if (Build.VERSION.SDK_INT < 29) { failCapture("Device audio requires Android 10 or later."); return; }
        if (!currentCaptureFlow()) { captureFlow = 0; return; }
        if (code == OVERLAY_PERMISSION) {
            if (!Settings.canDrawOverlays(this)) failCapture("Floating-button permission was denied. Enable it or turn off the floating button and try again.");
            else requestNotifications();
        } else if (result != RESULT_OK || data == null) failCapture("Device audio sharing was canceled.");
        else {
            long generation = captureFlow;
            captureFlow = 0;
            try {
                Intent service = new Intent(this, PlaybackCaptureService.class)
                    .putExtra("grant", data).putExtra("result", result).putExtra("generation", generation)
                    .putExtra("overlay", captureOverlay).putExtra("factor", captureFactor);
                startForegroundService(service);
            } catch (RuntimeException error) { app.failAudio(generation, "Cannot start device audio: " + error.getMessage()); }
        }
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        state.putLong("captureFlow", captureFlow);
        state.putBoolean("captureOverlay", captureOverlay);
        state.putDouble("captureFactor", captureFactor);
        super.onSaveInstanceState(state);
    }

    @Override protected void onPause() {
        // A microphone permission dialog may pause us without leaving the app.
        if (microphoneRequest == null && !currentCaptureFlow()) updateForeground(false);
        super.onPause();
    }

    @Override protected void onStop() {
        if (!currentCaptureFlow()) updateForeground(false);
        super.onStop();
    }

    @Override protected void onResume() {
        super.onResume();
        updateForeground(true);
    }

    private void updateForeground(boolean visible) {
        foreground = visible;
        if (web != null) web.evaluateJavascript(
            "if (typeof setAndroidForeground === 'function') setAndroidForeground(" + visible + ");", null);
    }

    @Override public void onBackPressed() {
        if (web != null) {
            web.evaluateJavascript("(() => { const d = document.querySelector('dialog[open]'); if (d) { d.close(); return true; } return false; })()",
                result -> {
                    if (!"true".equals(result)) {
                        if (web.canGoBack()) web.goBack();
                        else moveTaskToBack(true);
                    }
                });
        } else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        app.observer = null;
        if (microphoneRequest != null) microphoneRequest.deny();
        if (isFinishing() && currentCaptureFlow()) failCapture("Device audio setup was interrupted. Try again.");
        if (web != null) { web.removeJavascriptInterface("AndroidAudio"); web.destroy(); }
        super.onDestroy();
    }
}
