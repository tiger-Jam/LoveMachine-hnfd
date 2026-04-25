// main.cpp — Koi-Koi Trainer ダッシュボード (M5Stack TAB5)
//
// 起動フロー:
//   1. M5 init + LCD/touch init
//   2. NVS から WiFi creds + ホスト IP を読む
//   3. WiFi 接続 → 失敗 or 未設定なら setup mode
//   4. 5 秒おきに M4 / 4060 daemon の /train/status を poll
//   5. UI 描画 + タッチで Start/Stop/Pause/Resume/Logs 操作
//
// 初回設定 (USB シリアル経由):
//   115200 baud で接続し、以下のコマンドを送信 (Enter で確定):
//     SET WIFI <ssid> <password>
//     SET M4 <ip[:port]>
//     SET PC <ip[:port]>
//     SET TOKEN <token>          (空にしたいときは "SET TOKEN")
//     SHOW                       現在の設定表示
//     SAVE                       NVS に保存して再起動
//     RESET                      設定全消去して再起動
//
// タッチ長押ししながら起動 → setup mode (WiFi 接続スキップ、Serial 待ち)。

#include <Arduino.h>
#include <M5Unified.h>
#include <WiFi.h>
#include <Preferences.h>
#include <ArduinoJson.h>

#include "ui.h"
#include "api_client.h"

struct Config {
    String wifi_ssid;
    String wifi_pass;
    String m4_ip;
    String pc4060_ip;
    String m4_name;       // 表示用 slot 名 (デフォ "M4")
    String pc4060_name;   // 表示用 slot 名 (デフォ "4060")
    String token;
    int poll_interval_s = 5;
};

Config g_cfg;
HostStatus g_status[2];
String g_hostnames_buf[2];                  // c_str() を保持する実体
const char* g_hostnames[2] = {"M4", "4060"};
unsigned long g_last_poll = 0;

void refresh_hostnames() {
    g_hostnames_buf[0] = g_cfg.m4_name.length() ? g_cfg.m4_name : String("M4");
    g_hostnames_buf[1] = g_cfg.pc4060_name.length() ? g_cfg.pc4060_name : String("4060");
    g_hostnames[0] = g_hostnames_buf[0].c_str();
    g_hostnames[1] = g_hostnames_buf[1].c_str();
}

void load_config() {
    Preferences prefs;
    prefs.begin("koikoi", true);
    g_cfg.wifi_ssid = prefs.getString("wifi_ssid", "");
    g_cfg.wifi_pass = prefs.getString("wifi_pass", "");
    g_cfg.m4_ip = prefs.getString("m4_ip", "");
    g_cfg.pc4060_ip = prefs.getString("pc4060_ip", "");
    g_cfg.m4_name = prefs.getString("m4_name", "");
    g_cfg.pc4060_name = prefs.getString("pc4060_name", "");
    g_cfg.token = prefs.getString("token", "");
    g_cfg.poll_interval_s = prefs.getInt("poll_s", 5);
    prefs.end();
    refresh_hostnames();
}

void save_config() {
    Preferences prefs;
    prefs.begin("koikoi", false);
    prefs.putString("wifi_ssid", g_cfg.wifi_ssid);
    prefs.putString("wifi_pass", g_cfg.wifi_pass);
    prefs.putString("m4_ip", g_cfg.m4_ip);
    prefs.putString("pc4060_ip", g_cfg.pc4060_ip);
    prefs.putString("m4_name", g_cfg.m4_name);
    prefs.putString("pc4060_name", g_cfg.pc4060_name);
    prefs.putString("token", g_cfg.token);
    prefs.putInt("poll_s", g_cfg.poll_interval_s);
    prefs.end();
    refresh_hostnames();
}

void clear_config() {
    Preferences prefs;
    prefs.begin("koikoi", false);
    prefs.clear();
    prefs.end();
}

// ---- Serial 設定モード ----
void run_serial_setup_mode(unsigned long timeout_ms = 0) {
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setTextSize(2);
    M5.Display.setTextColor(TFT_GOLD, TFT_BLACK);
    M5.Display.setCursor(20, 20);
    M5.Display.println("SETUP MODE");
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    M5.Display.setCursor(20, 60);
    M5.Display.println("Connect via USB serial @ 115200");
    M5.Display.setCursor(20, 80);
    M5.Display.println("Commands:");
    M5.Display.setCursor(20, 100);
    M5.Display.println("  SET WIFI <ssid> <password>");
    M5.Display.setCursor(20, 115);
    M5.Display.println("  SET M4 <ip[:port]>");
    M5.Display.setCursor(20, 130);
    M5.Display.println("  SET PC <ip[:port]>");
    M5.Display.setCursor(20, 145);
    M5.Display.println("  SET TOKEN [token]");
    M5.Display.setCursor(20, 160);
    M5.Display.println("  SHOW   SAVE   RESET");

    Serial.println();
    Serial.println("==== Koi-Koi Trainer setup mode ====");
    Serial.println("Send commands. SAVE to commit + reboot.");

    unsigned long t0 = millis();
    String line;
    while (true) {
        if (timeout_ms > 0 && millis() - t0 > timeout_ms) return;
        while (Serial.available()) {
            char c = Serial.read();
            if (c == '\r') continue;
            if (c == '\n') {
                line.trim();
                if (line.length() == 0) { Serial.print("> "); continue; }
                Serial.println();

                if (line == "SHOW") {
                    Serial.printf("WIFI: %s\n", g_cfg.wifi_ssid.c_str());
                    Serial.printf("M4:   %s   (name: %s)\n",
                                  g_cfg.m4_ip.c_str(), g_hostnames[0]);
                    Serial.printf("PC:   %s   (name: %s)\n",
                                  g_cfg.pc4060_ip.c_str(), g_hostnames[1]);
                    Serial.printf("TOKEN: %s\n", g_cfg.token.length() ? "(set)" : "(none)");
                } else if (line == "SAVE") {
                    save_config();
                    Serial.println("saved. rebooting...");
                    delay(500);
                    ESP.restart();
                } else if (line == "RESET") {
                    clear_config();
                    Serial.println("cleared. rebooting...");
                    delay(500);
                    ESP.restart();
                } else if (line.startsWith("SET WIFI ")) {
                    String rest = line.substring(9);
                    int sp = rest.indexOf(' ');
                    if (sp > 0) {
                        g_cfg.wifi_ssid = rest.substring(0, sp);
                        g_cfg.wifi_pass = rest.substring(sp + 1);
                        Serial.println("WIFI set");
                    } else {
                        Serial.println("usage: SET WIFI <ssid> <pass>");
                    }
                } else if (line.startsWith("SET M4 ")) {
                    g_cfg.m4_ip = line.substring(7);
                    Serial.println("M4 IP set");
                } else if (line.startsWith("SET PC ")) {
                    g_cfg.pc4060_ip = line.substring(7);
                    Serial.println("PC IP set");
                } else if (line.startsWith("SET M4_NAME")) {
                    g_cfg.m4_name = (line.length() > 12) ? line.substring(12) : "";
                    refresh_hostnames();
                    Serial.println("M4 name set");
                } else if (line.startsWith("SET PC_NAME")) {
                    g_cfg.pc4060_name = (line.length() > 12) ? line.substring(12) : "";
                    refresh_hostnames();
                    Serial.println("PC name set");
                } else if (line.startsWith("SET TOKEN")) {
                    g_cfg.token = (line.length() > 10) ? line.substring(10) : "";
                    Serial.println("TOKEN set");
                } else {
                    Serial.println("unknown command");
                }
                Serial.print("> ");
                line = "";
            } else {
                line += c;
            }
        }
        delay(10);
    }
}

bool connect_wifi(unsigned long timeout_ms = 30000) {
    if (g_cfg.wifi_ssid.length() == 0) return false;

    M5.Display.setTextSize(2);
    M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    M5.Display.setCursor(20, M5.Display.height() / 2);
    M5.Display.printf("Connecting to %s...", g_cfg.wifi_ssid.c_str());

    WiFi.mode(WIFI_STA);
    WiFi.begin(g_cfg.wifi_ssid.c_str(), g_cfg.wifi_pass.c_str());

    unsigned long t0 = millis();
    while (millis() - t0 < timeout_ms) {
        if (WiFi.status() == WL_CONNECTED) {
            return true;
        }
        delay(200);
        M5.Display.print(".");
    }
    return false;
}

// ---- ボタンタップ -----------------------------------------
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
    g_last_poll = 0;
}

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
    M5.Display.setRotation(3);          // 1 だと上下逆だったので 180° 回転
    M5.Display.setBrightness(200);     // バックライト ON (0=消灯, 255=最大)
    M5.Display.fillScreen(TFT_BLACK);

    Serial.begin(115200);
    delay(200);
    Serial.println("\n[koikoi-dash] boot");

    load_config();

    // タッチ長押し起動 → setup mode (永遠に Serial 待ち)
    M5.update();
    bool force_setup = M5.Touch.getDetail().isPressed();
    if (force_setup || g_cfg.wifi_ssid.length() == 0) {
        Serial.println("[koikoi-dash] entering setup mode");
        run_serial_setup_mode();  // SAVE/RESET で再起動するまで戻らない
    }

    // WiFi 接続
    if (!connect_wifi()) {
        M5.Display.fillScreen(TFT_BLACK);
        M5.Display.setTextSize(2);
        M5.Display.setTextColor(TFT_RED, TFT_BLACK);
        M5.Display.setCursor(20, 40);
        M5.Display.println("WiFi connect FAILED");
        M5.Display.setTextSize(1);
        M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
        M5.Display.setCursor(20, 80);
        M5.Display.println("Hold touch and reboot to enter setup mode.");
        M5.Display.setCursor(20, 100);
        M5.Display.println("Or send commands via USB serial.");
        run_serial_setup_mode();  // 戻らない
    }

    Serial.printf("[koikoi-dash] WiFi OK, IP=%s\n", WiFi.localIP().toString().c_str());

    ui_init();
    ui_set_button_handler(on_button_pressed);

    poll_all();
    ui_render(g_status, g_hostnames);
}

// 動作中でも Serial で SET / SHOW / SAVE / RESET / SETUP を受け付ける。
// SETUP コマンドは setup mode に強制移行 (再起動後に setup loop に入る)。
static String g_serial_buf;
void handle_runtime_serial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\r') continue;
        if (c == '\n') {
            String line = g_serial_buf;
            g_serial_buf = "";
            line.trim();
            if (line.length() == 0) { Serial.print("> "); continue; }
            Serial.println();

            if (line == "SHOW") {
                Serial.printf("WIFI: %s\n", g_cfg.wifi_ssid.c_str());
                Serial.printf("M4:   %s\n", g_cfg.m4_ip.c_str());
                Serial.printf("PC:   %s\n", g_cfg.pc4060_ip.c_str());
                Serial.printf("TOKEN: %s\n", g_cfg.token.length() ? "(set)" : "(none)");
            } else if (line == "SAVE") {
                save_config();
                Serial.println("saved. rebooting...");
                delay(500);
                ESP.restart();
            } else if (line == "RESET") {
                clear_config();
                Serial.println("cleared. rebooting...");
                delay(500);
                ESP.restart();
            } else if (line == "SETUP") {
                clear_config();
                Serial.println("force setup mode on next boot. rebooting...");
                delay(500);
                ESP.restart();
            } else if (line.startsWith("SET WIFI ")) {
                String rest = line.substring(9);
                int sp = rest.indexOf(' ');
                if (sp > 0) {
                    g_cfg.wifi_ssid = rest.substring(0, sp);
                    g_cfg.wifi_pass = rest.substring(sp + 1);
                    Serial.println("WIFI set (call SAVE to persist)");
                }
            } else if (line.startsWith("SET M4 ")) {
                g_cfg.m4_ip = line.substring(7);
                Serial.println("M4 IP set (call SAVE)");
            } else if (line.startsWith("SET PC ")) {
                g_cfg.pc4060_ip = line.substring(7);
                Serial.println("PC IP set (call SAVE)");
            } else if (line.startsWith("SET M4_NAME")) {
                g_cfg.m4_name = (line.length() > 12) ? line.substring(12) : "";
                refresh_hostnames();
                Serial.println("M4 name set (call SAVE)");
            } else if (line.startsWith("SET PC_NAME")) {
                g_cfg.pc4060_name = (line.length() > 12) ? line.substring(12) : "";
                refresh_hostnames();
                Serial.println("PC name set (call SAVE)");
            } else if (line.startsWith("SET TOKEN")) {
                g_cfg.token = (line.length() > 10) ? line.substring(10) : "";
                Serial.println("TOKEN set (call SAVE)");
            } else {
                Serial.println("unknown command");
            }
            Serial.print("> ");
        } else {
            g_serial_buf += c;
        }
    }
}

void loop() {
    M5.update();
    ui_handle_touch();
    handle_runtime_serial();

    unsigned long now = millis();
    if (now - g_last_poll >= (unsigned long)g_cfg.poll_interval_s * 1000) {
        g_last_poll = now;
        poll_all();
        ui_render(g_status, g_hostnames);
    }
    delay(20);
}
