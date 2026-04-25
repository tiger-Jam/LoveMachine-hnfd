// main.cpp — Koi-Koi Trainer ダッシュボード (M5Stack TAB5 用)
//
// 起動時の動き:
//   1. M5 init + LCD/touch init
//   2. NVS から WiFi creds + ホスト IP を読む
//   3. WiFi 接続 (失敗したら captive portal で再設定 → reboot)
//   4. 5 秒おきに M4 / 4060 daemon の /train/status を poll
//   5. UI 描画 + タッチで Start/Stop/Pause/Resume/Logs 操作
//
// ノーコード設定:
//   - 初回起動 / Wi-Fi 失敗時、TAB5 が AP "KoikoiTrainer-Setup" を立てる
//   - スマホで参加 → 192.168.4.1 にブラウザで接続
//   - そこから home WiFi + M4 IP + 4060 IP + (token) を入力

#include <Arduino.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <WiFiManager.h>

#include "ui.h"
#include "api_client.h"

// ---- 永続設定 ----------------------------------------------
struct Config {
    String m4_ip;        // 例: "192.168.1.42:8990"
    String pc4060_ip;    // 例: "192.168.1.43:8990"
    String token;        // KOIKOI_DAEMON_TOKEN (空なら無認証)
    int poll_interval_s = 5;
};

Config g_cfg;
HostStatus g_status[2];      // [0]=M4, [1]=4060
const char* g_hostnames[2] = {"M4", "4060"};
unsigned long g_last_poll = 0;

void load_config() {
    Preferences prefs;
    prefs.begin("koikoi", true);
    g_cfg.m4_ip = prefs.getString("m4_ip", "");
    g_cfg.pc4060_ip = prefs.getString("pc4060_ip", "");
    g_cfg.token = prefs.getString("token", "");
    g_cfg.poll_interval_s = prefs.getInt("poll_s", 5);
    prefs.end();
}

void save_config() {
    Preferences prefs;
    prefs.begin("koikoi", false);
    prefs.putString("m4_ip", g_cfg.m4_ip);
    prefs.putString("pc4060_ip", g_cfg.pc4060_ip);
    prefs.putString("token", g_cfg.token);
    prefs.putInt("poll_s", g_cfg.poll_interval_s);
    prefs.end();
}

// ---- WiFi captive portal で初回設定 -----------------------
void setup_wifi() {
    WiFiManager wm;

    // 追加項目: M4 / 4060 / token
    WiFiManagerParameter pm4("m4ip",
        "M4 daemon (IP[:port])", g_cfg.m4_ip.c_str(), 64);
    WiFiManagerParameter pp("pc4060ip",
        "4060 daemon (IP[:port])", g_cfg.pc4060_ip.c_str(), 64);
    WiFiManagerParameter pt("token",
        "auth token (optional)", g_cfg.token.c_str(), 128);
    wm.addParameter(&pm4);
    wm.addParameter(&pp);
    wm.addParameter(&pt);

    // タイムアウト 5 分。それまでに繋がなければそのまま reboot して再試行
    wm.setConfigPortalTimeout(300);

    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setTextSize(2);
    M5.Display.setCursor(20, 40);
    M5.Display.print("Koi-Koi Trainer Setup\n\n");
    M5.Display.print("Join WiFi: KoikoiTrainer-Setup\n");
    M5.Display.print("Open: 192.168.4.1\n");

    bool ok = wm.autoConnect("KoikoiTrainer-Setup");
    if (!ok) {
        M5.Display.println("\nSetup failed/timeout. Rebooting...");
        delay(3000);
        ESP.restart();
    }

    // パラメータ保存
    g_cfg.m4_ip = pm4.getValue();
    g_cfg.pc4060_ip = pp.getValue();
    g_cfg.token = pt.getValue();
    save_config();

    M5.Display.println("\nConnected! IP:");
    M5.Display.println(WiFi.localIP());
    delay(1500);
}

// ---- ボタンタップ処理 -------------------------------------
void on_button_pressed(int host_idx, ButtonAction action) {
    String host_url = (host_idx == 0) ? g_cfg.m4_ip : g_cfg.pc4060_ip;
    if (host_url.length() == 0) return;

    bool ok = false;
    String resp;
    switch (action) {
        case BTN_START:
            ok = api_post(host_url, "/train/start", g_cfg.token,
                          "{\"config\":\"nfsp\"}", resp); break;
        case BTN_STOP:
            ok = api_post(host_url, "/train/stop", g_cfg.token, "{}", resp); break;
        case BTN_PAUSE:
            ok = api_post(host_url, "/train/pause", g_cfg.token, "{}", resp); break;
        case BTN_RESUME:
            ok = api_post(host_url, "/train/resume", g_cfg.token, "{}", resp); break;
        case BTN_LOGS:
            ui_show_logs(g_hostnames[host_idx], host_url, g_cfg.token); break;
    }
    if (action != BTN_LOGS) {
        ui_show_toast(ok ? "OK" : "FAIL", ok ? TFT_GREEN : TFT_RED);
    }
    g_last_poll = 0;  // 即時再 poll
}

// ---- 周期 poll --------------------------------------------
void poll_all() {
    for (int i = 0; i < 2; ++i) {
        String host_url = (i == 0) ? g_cfg.m4_ip : g_cfg.pc4060_ip;
        if (host_url.length() == 0) {
            g_status[i].reachable = false;
            continue;
        }
        api_get_status(host_url, g_cfg.token, g_status[i]);
    }
}

// ============================================================
// Arduino lifecycle
// ============================================================

void setup() {
    auto cfg = M5.config();
    M5.begin(cfg);
    M5.Display.setRotation(1);
    M5.Display.fillScreen(TFT_BLACK);

    Serial.begin(115200);
    delay(100);
    Serial.println("\n[koikoi-dash] boot");

    load_config();

    // タッチで長押ししながら起動 → 設定強制リセット
    M5.update();
    if (M5.Touch.getDetail().isPressed()) {
        Serial.println("[koikoi-dash] forced WiFi reset");
        WiFiManager wm;
        wm.resetSettings();
    }

    setup_wifi();

    ui_init();
    ui_set_button_handler(on_button_pressed);

    poll_all();
    ui_render(g_status, g_hostnames);
}

void loop() {
    M5.update();
    ui_handle_touch();

    unsigned long now = millis();
    if (now - g_last_poll >= (unsigned long)g_cfg.poll_interval_s * 1000) {
        g_last_poll = now;
        poll_all();
        ui_render(g_status, g_hostnames);
    }
    delay(20);
}
