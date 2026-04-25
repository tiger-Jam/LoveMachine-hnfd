// api_client.h — train_daemon の HTTP API ラッパ
#pragma once

#include <Arduino.h>

struct HostStatus {
    bool reachable = false;
    bool running = false;
    bool paused = false;
    long episode = 0;
    long total_episodes = 0;
    float loss_rl = 0.0f;
    float eps_per_sec = 0.0f;
    long elapsed_sec = 0;
    int gpu_temp = -1;
    int gpu_util = -1;
    int gpu_mem_mb = 0;
    float cpu_load = 0.0f;
    String last_log;
    String config;
};

bool api_get_status(const String& host, const String& token, HostStatus& out);
bool api_post(const String& host, const String& path, const String& token,
              const String& body, String& resp_out);
bool api_get_logs(const String& host, const String& token, int n,
                  String lines_out[], int max_lines, int& out_count);
