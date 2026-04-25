// ui.cpp — Koi-Koi ダッシュボード描画 + タッチハンドリング
//
// 1280x720 の画面想定 (M5Stack TAB5)。横置き。
// 上下 2 段に分けて [M4][4060] を表示。各段にステータス + 操作ボタン。

#include "ui.h"

#include <M5Unified.h>
#include "api_client.h"

// レイアウト定数
static constexpr int W = 1280;
static constexpr int H = 720;
static constexpr int TILE_H = (H - 60) / 2;   // 上下 2 タイル + 下部 margin
static constexpr int HEADER_H = 60;

// ボタン領域 (タイル内 相対座標)
struct Btn {
    int x, y, w, h;
    const char* label;
    ButtonAction action;
};

static const Btn kBtns[] = {
    { 720,  20, 110, 70, "START",  BTN_START},
    { 840,  20, 110, 70, "STOP",   BTN_STOP},
    { 960,  20, 110, 70, "PAUSE",  BTN_PAUSE},
    {1080,  20, 110, 70, "RESUME", BTN_RESUME},
    { 720, 100, 470, 50, "LOGS",   BTN_LOGS},
};
static constexpr int N_BTNS = sizeof(kBtns) / sizeof(kBtns[0]);

static ButtonHandler g_handler = nullptr;
static const HostStatus* g_last_statuses = nullptr;
static const char* const* g_last_hostnames = nullptr;

void ui_init() {
    M5.Display.setRotation(1);
    M5.Display.fillScreen(TFT_BLACK);
}

void ui_set_button_handler(ButtonHandler h) { g_handler = h; }

static void draw_header() {
    M5.Display.fillRect(0, 0, W, HEADER_H, 0x0841);  // 濃紺
    M5.Display.setTextColor(TFT_GOLD, 0x0841);
    M5.Display.setTextSize(3);
    M5.Display.setCursor(20, 18);
    M5.Display.print("KOI-KOI TRAINER");

    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_LIGHTGREY, 0x0841);
    M5.Display.setCursor(W - 200, 22);
    M5.Display.printf("WiFi: %s", WiFi.SSID().c_str());
    M5.Display.setCursor(W - 200, 38);
    M5.Display.print(WiFi.localIP().toString());
}

static const char* phase_label(const HostStatus& s) {
    if (!s.reachable) return "UNREACHABLE";
    if (!s.running)   return "IDLE";
    if (s.paused)     return "PAUSED";
    return "RUNNING";
}

static uint16_t phase_color(const HostStatus& s) {
    if (!s.reachable) return 0xC020;  // 暗赤
    if (!s.running)   return 0x4208;  // 灰
    if (s.paused)     return 0xFD20;  // 橙
    return 0x07E0;                    // 緑
}

static void draw_tile(int idx, int top_y, const HostStatus& s, const char* name) {
    M5.Display.fillRect(0, top_y, W, TILE_H, TFT_BLACK);
    M5.Display.drawRect(8, top_y + 8, W - 16, TILE_H - 12, TFT_DARKGREY);

    // ホスト名 + フェーズ
    M5.Display.setTextSize(4);
    M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
    M5.Display.setCursor(30, top_y + 25);
    M5.Display.print(name);

    M5.Display.setTextSize(2);
    M5.Display.setTextColor(phase_color(s), TFT_BLACK);
    M5.Display.setCursor(30, top_y + 70);
    M5.Display.print(phase_label(s));

    // メトリクス
    M5.Display.setTextSize(2);
    M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    int mx = 30, my = top_y + 110;
    M5.Display.setCursor(mx, my);
    if (s.reachable && (s.running || s.episode > 0)) {
        M5.Display.printf("ep   %ld", s.episode);
        M5.Display.setCursor(mx, my + 30);
        M5.Display.printf("loss %.4f", s.loss_rl);
        M5.Display.setCursor(mx, my + 60);
        M5.Display.printf("eps/s %.1f", s.eps_per_sec);
        M5.Display.setCursor(mx, my + 90);
        long h = s.elapsed_sec / 3600, m = (s.elapsed_sec % 3600) / 60;
        M5.Display.printf("elapsed %ldh%ldm", h, m);
    } else {
        M5.Display.setTextColor(TFT_DARKGREY, TFT_BLACK);
        M5.Display.print("(no run data)");
    }

    // GPU / CPU
    int gx = 380, gy = top_y + 110;
    M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    M5.Display.setCursor(gx, gy);
    if (s.reachable) {
        if (s.gpu_temp >= 0) {
            uint16_t c = (s.gpu_temp >= 80) ? TFT_RED :
                         (s.gpu_temp >= 70) ? TFT_ORANGE : TFT_LIGHTGREY;
            M5.Display.setTextColor(c, TFT_BLACK);
            M5.Display.printf("GPU %d C", s.gpu_temp);
            M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
            M5.Display.setCursor(gx, gy + 30);
            M5.Display.printf("util %d%%", s.gpu_util);
            M5.Display.setCursor(gx, gy + 60);
            M5.Display.printf("vram %dMB", s.gpu_mem_mb);
        } else {
            M5.Display.print("GPU n/a (CPU/MPS)");
        }
        M5.Display.setCursor(gx, gy + 90);
        M5.Display.printf("cpu %.0f%%", s.cpu_load);
    }

    // 最新ログ 1 行
    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_DARKGREEN, TFT_BLACK);
    M5.Display.setCursor(30, top_y + TILE_H - 30);
    String log = s.last_log;
    if (log.length() > 110) log = log.substring(0, 110) + "...";
    M5.Display.print(log);

    // ボタン群
    M5.Display.setTextSize(2);
    for (int i = 0; i < N_BTNS; ++i) {
        const Btn& b = kBtns[i];
        int x = b.x, y = top_y + b.y;
        uint16_t bg = TFT_DARKGREY;
        if (b.action == BTN_START)  bg = 0x05E0;
        if (b.action == BTN_STOP)   bg = 0xC020;
        if (b.action == BTN_PAUSE)  bg = 0xFD20;
        if (b.action == BTN_RESUME) bg = 0x05BF;
        if (b.action == BTN_LOGS)   bg = 0x4208;
        M5.Display.fillRoundRect(x, y, b.w, b.h, 8, bg);
        M5.Display.setTextColor(TFT_WHITE, bg);
        int tw = strlen(b.label) * 12;  // 雑に中央寄せ
        M5.Display.setCursor(x + (b.w - tw) / 2, y + (b.h - 16) / 2);
        M5.Display.print(b.label);
    }
}

void ui_render(const HostStatus statuses[2], const char* hostnames[2]) {
    g_last_statuses = statuses;
    g_last_hostnames = hostnames;
    draw_header();
    int top0 = HEADER_H;
    int top1 = HEADER_H + TILE_H + 4;
    draw_tile(0, top0, statuses[0], hostnames[0]);
    draw_tile(1, top1, statuses[1], hostnames[1]);
}

void ui_handle_touch() {
    auto t = M5.Touch.getDetail();
    if (!t.wasPressed()) return;

    int tx = t.x, ty = t.y;
    int top0 = HEADER_H;
    int top1 = HEADER_H + TILE_H + 4;

    // どちらの host か
    int host_idx = -1;
    int rel_y = -1;
    if (ty >= top0 && ty < top0 + TILE_H) { host_idx = 0; rel_y = ty - top0; }
    else if (ty >= top1 && ty < top1 + TILE_H) { host_idx = 1; rel_y = ty - top1; }
    if (host_idx < 0) return;

    for (int i = 0; i < N_BTNS; ++i) {
        const Btn& b = kBtns[i];
        if (tx >= b.x && tx < b.x + b.w && rel_y >= b.y && rel_y < b.y + b.h) {
            if (g_handler) g_handler(host_idx, b.action);
            return;
        }
    }
}

void ui_show_toast(const String& msg, uint16_t color) {
    int tw = msg.length() * 24;
    int tx = (W - tw) / 2;
    int ty = H / 2 - 40;
    M5.Display.fillRoundRect(tx - 30, ty - 20, tw + 60, 80, 12, TFT_BLACK);
    M5.Display.drawRoundRect(tx - 30, ty - 20, tw + 60, 80, 12, color);
    M5.Display.setTextSize(4);
    M5.Display.setTextColor(color, TFT_BLACK);
    M5.Display.setCursor(tx, ty);
    M5.Display.print(msg);
    delay(800);
    if (g_last_statuses && g_last_hostnames) {
        ui_render(g_last_statuses, g_last_hostnames);
    }
}

void ui_show_logs(const String& title, const String& host, const String& token) {
    M5.Display.fillScreen(TFT_BLACK);
    M5.Display.setTextSize(3);
    M5.Display.setTextColor(TFT_GOLD, TFT_BLACK);
    M5.Display.setCursor(20, 20);
    M5.Display.printf("Logs: %s", title.c_str());

    constexpr int MAX_LINES = 30;
    String lines[MAX_LINES];
    int n = 0;
    api_get_logs(host, token, MAX_LINES, lines, MAX_LINES, n);

    M5.Display.setTextSize(1);
    M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    int y = 70;
    for (int i = 0; i < n; ++i) {
        String l = lines[i];
        if (l.length() > 200) l = l.substring(0, 200) + "...";
        M5.Display.setCursor(20, y);
        M5.Display.print(l);
        y += 15;
        if (y > H - 60) break;
    }

    // 戻るボタン
    M5.Display.fillRoundRect(W - 180, H - 60, 160, 40, 8, TFT_DARKGREY);
    M5.Display.setTextSize(2);
    M5.Display.setTextColor(TFT_WHITE, TFT_DARKGREY);
    M5.Display.setCursor(W - 145, H - 50);
    M5.Display.print("BACK");

    // 戻るタッチ待ち
    while (true) {
        M5.update();
        auto t = M5.Touch.getDetail();
        if (t.wasPressed()) {
            if (t.x >= W - 180 && t.x <= W - 20 && t.y >= H - 60 && t.y <= H - 20) {
                break;
            }
        }
        delay(20);
    }

    if (g_last_statuses && g_last_hostnames) {
        ui_render(g_last_statuses, g_last_hostnames);
    }
}
