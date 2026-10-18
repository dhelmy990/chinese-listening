package com.ning.chinese;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
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

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        app = (ListeningApplication) getApplication();
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
        setup.setText("Set up offline models");
        setup.setOnClickListener(view -> app.start());
        root.addView(setup);
        app.observer = this::render;
        if (app.hasModels() && !app.failed) app.start();
        render();
    }

    private void render() {
        if (isFinishing() || isDestroyed()) return;
        if (app.url != null) { if (!showingApp) showApp(); return; }
        progress.setText(app.message);
        setup.setEnabled(!app.running);
        setup.setText(app.failed ? "Retry setup" : "Set up offline models");
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
        web.setWebViewClient(new WebViewClient() {
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
        if (code == 1 && microphoneRequest != null) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED)
                microphoneRequest.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            else microphoneRequest.deny();
            microphoneRequest = null;
        }
    }

    @Override protected void onPause() {
        // A microphone permission dialog may pause us without leaving the app.
        if (microphoneRequest == null) updateForeground(false);
        super.onPause();
    }

    @Override protected void onStop() {
        updateForeground(false);
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
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
