"""train_daemon.py — 学習プロセスを M5Stack / 任意 HTTP クライアントから
start/stop/status できる FastAPI デーモン。

両プラットフォーム共通:
  - LAN 内のみ listen (デフォルト 0.0.0.0:8990)
  - 簡易 token 認証 (環境変数 KOIKOI_DAEMON_TOKEN、未設定なら無認証)
  - 学習プロセスは subprocess で launch、PID + 起動時刻を state ファイルに記録
  - SIGTERM で安全停止 (training 側で checkpoint 保存)
  - SIGSTOP / SIGCONT で pause / resume
  - 最新 checkpoint メタデータをポーリングして status に反映

使い方:
    pip install fastapi uvicorn psutil
    python3 train_daemon.py
"""
from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import uvicorn


# ============================================================
# 設定
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get("KOIKOI_RUNS_DIR", ROOT / "runs"))
RUNS_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = RUNS_DIR / "current_run.json"
LOG_FILE = RUNS_DIR / "current.log"
CHECKPOINT_META = RUNS_DIR / "checkpoint_meta.json"

TRAIN_CMD = os.environ.get(
    "KOIKOI_TRAIN_CMD",
    f"{sys.executable} {ROOT / 'daemon' / 'run_train.py'}",
)

AUTH_TOKEN = os.environ.get("KOIKOI_DAEMON_TOKEN", "")
LISTEN_PORT = int(os.environ.get("KOIKOI_DAEMON_PORT", "8990"))
LISTEN_HOST = os.environ.get("KOIKOI_DAEMON_HOST", "0.0.0.0")


# ============================================================
# 状態 I/O
# ============================================================

def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _proc_alive(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, ProcessLookupError):
        return False


def _proc_paused(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        return p.status() == psutil.STATUS_STOPPED
    except (psutil.NoSuchProcess, ProcessLookupError):
        return False


# ============================================================
# 学習プロセス制御
# ============================================================

def start_training(config: str = "default", extra_args: Optional[list[str]] = None) -> dict:
    state = _load_state()
    if state.get("pid") and _proc_alive(state["pid"]):
        raise HTTPException(409, f"Already running (pid={state['pid']})")

    LOG_FILE.write_text("")  # truncate
    cmd = shlex.split(TRAIN_CMD) + ["--config", config]
    if extra_args:
        cmd.extend(extra_args)

    # tee 経由で書き込ませると、CUDA 初期化中の子 silent crash を回避できる。
    # /bin/sh -c で wrap して "python ... 2>&1 | tee LOG" を 1 プロセスとして起動。
    shell_cmd = " ".join(shlex.quote(x) for x in cmd) + f" 2>&1 | tee {shlex.quote(str(LOG_FILE))}"
    proc = subprocess.Popen(
        ["/bin/sh", "-c", shell_cmd],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    state = {
        "pid": proc.pid,
        "config": config,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cmd": cmd,
    }
    _save_state(state)
    return state


def stop_training(timeout_sec: float = 30.0) -> dict:
    state = _load_state()
    pid = state.get("pid")
    if not pid or not _proc_alive(pid):
        return {"stopped": False, "reason": "not_running"}

    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass

    deadline = time.time() + timeout_sec
    while time.time() < deadline and _proc_alive(pid):
        time.sleep(0.5)

    if _proc_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        return {"stopped": True, "force_killed": True}

    state["stopped_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    return {"stopped": True, "force_killed": False}


def pause_training() -> dict:
    state = _load_state()
    pid = state.get("pid")
    if not pid or not _proc_alive(pid):
        raise HTTPException(404, "not_running")
    if _proc_paused(pid):
        return {"paused": True, "already": True}
    os.killpg(os.getpgid(pid), signal.SIGSTOP)
    return {"paused": True}


def resume_training() -> dict:
    state = _load_state()
    pid = state.get("pid")
    if not pid or not _proc_alive(pid):
        raise HTTPException(404, "not_running")
    if not _proc_paused(pid):
        return {"resumed": True, "already": True}
    os.killpg(os.getpgid(pid), signal.SIGCONT)
    return {"resumed": True}


# ============================================================
# Status / monitoring
# ============================================================

def _gpu_info() -> dict:
    """nvidia-smi が使える場合に GPU 情報を取る。Mac は MPS なので空 dict。"""
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        return {}
    try:
        out = subprocess.check_output(
            [nvsmi, "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            text=True, timeout=2,
        ).strip().splitlines()
        if not out:
            return {}
        # 1 GPU だけ想定 (複数あれば配列にする)
        parts = [p.strip() for p in out[0].split(",")]
        return {
            "temp_c": int(parts[0]),
            "util_pct": int(parts[1]),
            "mem_used_mb": int(parts[2]),
            "mem_total_mb": int(parts[3]),
        }
    except Exception:
        return {}


def _last_log_lines(n: int = 30) -> list[str]:
    if not LOG_FILE.exists():
        return []
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= n + 2:
                read_size = min(block, size)
                size -= read_size
                f.seek(size)
                data = f.read(read_size) + data
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return lines[-n:]
    except Exception as e:
        return [f"<log read error: {e}>"]


def _checkpoint_meta() -> dict:
    if not CHECKPOINT_META.exists():
        return {}
    try:
        return json.loads(CHECKPOINT_META.read_text())
    except Exception:
        return {}


def get_status() -> dict:
    state = _load_state()
    pid = state.get("pid")
    running = bool(pid and _proc_alive(pid))
    paused = bool(pid and running and _proc_paused(pid))

    started = state.get("started_at")
    elapsed_sec = None
    if started:
        try:
            t0 = datetime.fromisoformat(started)
            elapsed_sec = (datetime.now(timezone.utc) - t0).total_seconds()
        except ValueError:
            elapsed_sec = None

    cpu_pct = None
    mem_mb = None
    if running and pid:
        try:
            p = psutil.Process(pid)
            cpu_pct = p.cpu_percent(interval=None)
            mem_mb = p.memory_info().rss / (1024 * 1024)
        except psutil.NoSuchProcess:
            pass

    ckpt = _checkpoint_meta()
    log_tail = _last_log_lines(5)

    return {
        "host": socket.gethostname(),
        "platform": platform.system(),
        "running": running,
        "paused": paused,
        "pid": pid if running else None,
        "config": state.get("config"),
        "started_at": started,
        "elapsed_sec": elapsed_sec,
        "cpu_pct": cpu_pct,
        "mem_mb": mem_mb,
        "system_cpu_pct": psutil.cpu_percent(interval=None),
        "system_mem_pct": psutil.virtual_memory().percent,
        "gpu": _gpu_info(),
        "checkpoint": ckpt,
        "last_log": log_tail[-1] if log_tail else None,
    }


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(title="Koi-Koi Trainer Daemon", version="0.1.0")


def _check_token(authorization: Optional[str]) -> None:
    if not AUTH_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing_token")
    if authorization.removeprefix("Bearer ").strip() != AUTH_TOKEN:
        raise HTTPException(401, "invalid_token")


class StartReq(BaseModel):
    config: str = "default"
    extra_args: Optional[list[str]] = None


@app.get("/health")
def health():
    return {"ok": True, "host": socket.gethostname()}


@app.get("/train/status")
def api_status(authorization: Optional[str] = Header(None)):
    _check_token(authorization)
    return get_status()


@app.post("/train/start")
def api_start(req: StartReq, authorization: Optional[str] = Header(None)):
    _check_token(authorization)
    return start_training(req.config, req.extra_args)


@app.post("/train/stop")
def api_stop(authorization: Optional[str] = Header(None)):
    _check_token(authorization)
    return stop_training()


@app.post("/train/pause")
def api_pause(authorization: Optional[str] = Header(None)):
    _check_token(authorization)
    return pause_training()


@app.post("/train/resume")
def api_resume(authorization: Optional[str] = Header(None)):
    _check_token(authorization)
    return resume_training()


@app.get("/train/logs")
def api_logs(n: int = 100, authorization: Optional[str] = Header(None)):
    _check_token(authorization)
    return {"lines": _last_log_lines(n)}


@app.get("/system/info")
def api_sysinfo(authorization: Optional[str] = Header(None)):
    _check_token(authorization)
    return {
        "host": socket.gethostname(),
        "platform": platform.system(),
        "python": sys.version,
        "cpu_count": psutil.cpu_count(),
        "mem_total_gb": round(psutil.virtual_memory().total / 2**30, 2),
        "uptime_sec": time.time() - psutil.boot_time(),
        "gpu": _gpu_info(),
    }


def main():
    print(f"[daemon] listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"[daemon] runs dir: {RUNS_DIR}")
    print(f"[daemon] auth: {'enabled' if AUTH_TOKEN else 'DISABLED (no token set)'}")
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level="info")


if __name__ == "__main__":
    main()
