// api_client.cpp — train_daemon HTTP API ラッパ
#include "api_client.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

static String build_url(const String& host, const String& path) {
    String u;
    if (host.startsWith("http://") || host.startsWith("https://")) {
        u = host;
    } else {
        u = "http://" + host;
    }
    if (!u.endsWith("/")) u += "";
    u += path;
    return u;
}

bool api_get_status(const String& host, const String& token, HostStatus& out) {
    out.reachable = false;
    if (WiFi.status() != WL_CONNECTED) return false;
    if (host.length() == 0) return false;

    HTTPClient http;
    String url = build_url(host, "/train/status");
    http.setConnectTimeout(2000);
    http.setTimeout(3000);
    if (!http.begin(url)) return false;
    if (token.length() > 0) {
        http.addHeader("Authorization", "Bearer " + token);
    }

    int code = http.GET();
    if (code != 200) {
        http.end();
        return false;
    }

    String body = http.getString();
    http.end();

    DynamicJsonDocument doc(8192);
    DeserializationError err = deserializeJson(doc, body);
    if (err) return false;

    out.reachable = true;
    out.running = doc["running"] | false;
    out.paused = doc["paused"] | false;
    out.cpu_load = doc["system_cpu_pct"] | 0.0f;
    out.last_log = doc["last_log"] | "";
    out.config = doc["config"] | "";

    JsonObject ckpt = doc["checkpoint"];
    if (!ckpt.isNull()) {
        out.episode = ckpt["episode"] | 0;
        out.total_episodes = ckpt["total_episodes"] | 0;
        out.loss_rl = ckpt["loss_rl"] | 0.0f;
        out.eps_per_sec = ckpt["eps_per_sec"] | 0.0f;
        out.elapsed_sec = ckpt["elapsed_sec"] | 0;
    } else {
        out.episode = 0;
        out.total_episodes = 0;
        out.loss_rl = 0.0f;
        out.eps_per_sec = 0.0f;
        out.elapsed_sec = 0;
    }

    JsonObject gpu = doc["gpu"];
    if (!gpu.isNull() && gpu.size() > 0) {
        out.gpu_temp = gpu["temp_c"] | -1;
        out.gpu_util = gpu["util_pct"] | -1;
        out.gpu_mem_mb = gpu["mem_used_mb"] | 0;
    } else {
        out.gpu_temp = -1;
        out.gpu_util = -1;
        out.gpu_mem_mb = 0;
    }

    return true;
}

bool api_post(const String& host, const String& path, const String& token,
              const String& body, String& resp_out) {
    if (WiFi.status() != WL_CONNECTED) return false;
    if (host.length() == 0) return false;

    HTTPClient http;
    String url = build_url(host, path);
    http.setConnectTimeout(2000);
    http.setTimeout(10000);
    if (!http.begin(url)) return false;
    http.addHeader("Content-Type", "application/json");
    if (token.length() > 0) {
        http.addHeader("Authorization", "Bearer " + token);
    }

    int code = http.POST(body);
    resp_out = http.getString();
    http.end();
    return (code >= 200 && code < 300);
}

bool api_get_logs(const String& host, const String& token, int n,
                  String lines_out[], int max_lines, int& out_count) {
    out_count = 0;
    if (WiFi.status() != WL_CONNECTED) return false;
    if (host.length() == 0) return false;

    HTTPClient http;
    String url = build_url(host, "/train/logs?n=" + String(n));
    http.setConnectTimeout(2000);
    http.setTimeout(5000);
    if (!http.begin(url)) return false;
    if (token.length() > 0) {
        http.addHeader("Authorization", "Bearer " + token);
    }
    int code = http.GET();
    if (code != 200) {
        http.end();
        return false;
    }
    String body = http.getString();
    http.end();

    DynamicJsonDocument doc(16384);
    if (deserializeJson(doc, body)) return false;

    JsonArray arr = doc["lines"];
    int i = 0;
    for (JsonVariant v : arr) {
        if (i >= max_lines) break;
        lines_out[i++] = v.as<String>();
    }
    out_count = i;
    return true;
}
