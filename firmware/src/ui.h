// ui.h — Koi-Koi ダッシュボード UI
#pragma once

#include <Arduino.h>
#include "api_client.h"

enum ButtonAction {
    BTN_START,
    BTN_STOP,
    BTN_PAUSE,
    BTN_RESUME,
    BTN_LOGS,
};

typedef void (*ButtonHandler)(int host_idx, ButtonAction action);

void ui_init();
void ui_set_button_handler(ButtonHandler h);
void ui_render(const HostStatus statuses[2], const char* const hostnames[2]);
void ui_handle_touch();
void ui_show_toast(const String& msg, uint16_t color);
void ui_show_logs(const String& title, const String& host, const String& token);
