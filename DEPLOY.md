# デプロイ手順 — Koi-Koi Trainer 一式

学習デーモンを **Windows (4060) PC で Docker** 起動し、M5Stack TAB5 から制御するセットアップ。

## 構成

```
[ M5Stack TAB5 ]  ──────────────────┐
                                    │ HTTP (LAN)
                                    ▼
   [ Windows 11 + 4060, 32GB RAM ]
   ┌─────────────────────────────────┐
   │ Docker Desktop + WSL2           │
   │  ├─ container 1   port 8990     │
   │  ├─ container 2   port 8991     │  ← 並列学習可
   │  ├─ container 3   port 8992     │
   │  └─ container 4   port 8993     │
   │  GPU --gpus all で 4060 共有     │
   └─────────────────────────────────┘

[ Mac M4 ]   ← M5Burner で .bin 焼く役だけ。daemon は不要
```

各デバイスで **1 アクション** だけ。コードは書きません。

---

## 1. Windows 4060 PC のセットアップ

**管理者** PowerShell で 1 行：

```powershell
irm https://raw.githubusercontent.com/tiger-Jam/LoveMachine-hnfd/main/install/install-windows.ps1 | iex
```

裏側で：
- WSL2 + Ubuntu 22.04 install (初回は Windows 再起動 1 回必要)
- Docker Desktop check (無ければ DL ページ案内)
- NVIDIA driver で GPU パススルー確認
- GHCR から prebuilt image pull (~6GB、初回のみ)
- コンテナ起動 (`--gpus all`、port 8990)
- Windows ファイアウォールに穴 (LAN 内のみ)
- ログイン時自動起動 (タスクスケジューラ)

**並列で複数コンテナ起動したい場合**：

```powershell
$env:KOIKOI_INSTANCES = 4   # 4 つ起動 (port 8990, 8991, 8992, 8993)
irm https://raw.githubusercontent.com/tiger-Jam/LoveMachine-hnfd/main/install/install-windows.ps1 | iex
```

メモリ消費の目安：
- 1 コンテナ ≈ 3-4 GB
- 4 並列 ≈ 12-16 GB (32GB RAM なら余裕)
- VRAM (4060=8GB) は学習側が小さいネット使うので 4 並列も可

確認：
```powershell
curl http://127.0.0.1:8990/health
# → {"ok": true, "host": "container-id"}
```

LAN IP は `ipconfig` で確認。

---

## 2. M5Stack TAB5 のセットアップ

1. **Mac (or 任意の PC) で M5Burner をインストール**
   https://docs.m5stack.com/en/uiflow/m5burner_v3/intro
   公式 GUI、ノーコード。

2. GitHub Releases から最新 `koikoi-trainer-firmware.bin` をダウンロード
   https://github.com/tiger-Jam/LoveMachine-hnfd/releases

3. TAB5 を USB-C で繋ぎ、M5Burner で：
   - 上タブ「**Custom firmware**」
   - 下ろした `.bin` ファイルを選択
   - デバイス選択 (TAB5 が COM ポートで見える)
   - 「Burn」クリック

4. 書き込み完了後 TAB5 が再起動 → 画面に WiFi 設定指示

5. iPhone or Mac で WiFi `KoikoiTrainer-Setup` に参加 → ブラウザで `192.168.4.1` 開く

6. フォーム入力：
   - 自宅 WiFi の SSID + パスワード
   - **M4 daemon**: 4060 PC の IP `192.168.x.x:8990` ← (M4 という表示だが Windows 機の 1 個目のコンテナ)
   - **4060 daemon**: 4060 PC の IP `192.168.x.x:8991` ← (2 個目のコンテナ。1 コンテナ運用なら空欄)
   - token: 通常空欄

7. Save → TAB5 が再起動 → ダッシュボード表示

> NOTE: firmware の host slot 名は v0.1 で固定 (M4 / 4060)。両方を Windows コンテナに向ける運用で OK。次バージョンで slot 名カスタマイズ予定。

---

## 3. 操作

TAB5 画面：

```
┌──────────────────────────────────────┐
│ KOI-KOI TRAINER          WiFi: home  │
├──────────────────────────────────────┤
│  M4         RUNNING   [START][STOP]  │
│  ep 152340  loss 0.234 [PAUSE][RES]  │
│  GPU 65°C   util 70%   [    LOGS   ] │
├──────────────────────────────────────┤
│  4060       IDLE     [START][STOP]   │
│  last loss 0.612      [PAUSE][RES]   │
│  GPU 65°C   util 0%   [    LOGS   ]  │
└──────────────────────────────────────┘
```

各コンテナ独立で start/stop 可能。LOGS で最新ログを画面表示。

---

## 4. トラブルシュート

### Windows コンテナが落ちる
```powershell
docker ps -a              # 状態確認
docker logs koikoi-trainer
docker restart koikoi-trainer
```

### GPU が見えない
```powershell
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```
ここで GPU 表示されないなら：
1. NVIDIA driver 最新化 (https://www.nvidia.com/Download/index.aspx)
2. Docker Desktop Settings > Resources > WSL Integration を ON
3. 再起動

### TAB5 が WiFi 繋がらない
タッチを長押ししながら起動 → WiFi 設定リセット → captive portal 再表示

### TAB5 設定をやり直したい
M5Burner の「Erase Flash」→ もう一度 .bin 焼く

---

## 5. 認証 (オプション)

LAN 外からアクセスするなら token 認証推奨：

```powershell
docker rm -f koikoi-trainer
docker run -d --name koikoi-trainer --gpus all -p 8990:8990 `
   -v koikoi-runs:/app/runs `
   -e KOIKOI_DAEMON_TOKEN=YOUR_SECRET `
   --restart unless-stopped `
   ghcr.io/tiger-jam/koikoi-trainer:latest
```

TAB5 captive portal の token フィールドに `YOUR_SECRET` を入力。

---

## 6. ハイパラ違いで並列学習

複数コンテナ立ち上げる + 起動時に違う config を渡す例：

```powershell
# NFSP (config A: hidden=128)
docker run -d --name koikoi-a --gpus all -p 8990:8990 `
   -v koikoi-a:/app/runs `
   --restart unless-stopped `
   ghcr.io/tiger-jam/koikoi-trainer:latest

# Deep CFR (config B)
docker run -d --name koikoi-b --gpus all -p 8991:8990 `
   -v koikoi-b:/app/runs `
   --restart unless-stopped `
   ghcr.io/tiger-jam/koikoi-trainer:latest
```

その後 TAB5 から各コンテナに対して：
- 8990 で START → NFSP 設定で起動
- 8991 で START → Deep CFR 設定で起動

(現状 M5Stack UI からは config 指定できないので、curl or ブラウザから一度 POST 必要)

---

## 7. 設計参考

- [`DISCUSSION/CPP_PORT_DESIGN.md`](DISCUSSION/CPP_PORT_DESIGN.md) — C++ ポート設計
- [`DISCUSSION/NASH_RESEARCH.md`](DISCUSSION/NASH_RESEARCH.md) — Nash 均衡 AI 研究まとめ
- `daemon/train_daemon.py` — REST API 仕様 (FastAPI swagger は `/docs` で見れる)
- `daemon/run_train.py` — 学習エントリ (NFSP / Deep CFR / smoke)
- `firmware/src/main.cpp` — M5Stack firmware エントリ
