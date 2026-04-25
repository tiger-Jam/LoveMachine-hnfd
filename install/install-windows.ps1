# install-windows.ps1 — Windows 11 で Koi-Koi trainer を完全自動セットアップ
#
# 既定: 1 コンテナ (port 8990) を起動
# オプション: 複数コンテナ並列起動 (ハイパラ違い等)
#
# 使い方 (管理者 PowerShell):
#   irm https://raw.githubusercontent.com/tiger-Jam/LoveMachine-hnfd/main/install/install-windows.ps1 | iex
#
# 複数コンテナを起動したい場合:
#   $env:KOIKOI_INSTANCES = 4   # 4 コンテナ起動 (port 8990, 8991, 8992, 8993)
#   irm <url> | iex

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

function Log($msg) { Write-Host "[install-win] $msg" -ForegroundColor Cyan }
function Err($msg) { Write-Host "[install-win] $msg" -ForegroundColor Red }

$IMAGE = "ghcr.io/tiger-jam/koikoi-trainer:latest"
$N_INSTANCES = if ($env:KOIKOI_INSTANCES) { [int]$env:KOIKOI_INSTANCES } else { 1 }
$BASE_PORT = 8990

# ---- 0. Windows version check -------------------------------
$os = Get-CimInstance Win32_OperatingSystem
if ([Version]$os.Version -lt [Version]"10.0.19041") {
    Err "Windows 10 build 19041 (2004) or later required. yours: $($os.Version)"
    exit 1
}

# ---- 1. WSL2 + Ubuntu ---------------------------------------
$wslList = wsl --list --quiet 2>$null
if ($LASTEXITCODE -ne 0 -or -not ($wslList -match "Ubuntu")) {
    Log "Installing WSL2 + Ubuntu 22.04 (will require reboot)..."
    wsl --install -d Ubuntu-22.04
    Log "WSL2 install kicked off. Reboot Windows, then re-run this script."
    Read-Host "Press Enter to exit"
    exit 0
} else {
    Log "WSL2 + Ubuntu already installed."
}
wsl --set-default-version 2 | Out-Null

# ---- 2. Docker Desktop --------------------------------------
$dockerExe = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerExe) {
    Err "Docker Desktop not found. Opening download page..."
    Start-Process "https://www.docker.com/products/docker-desktop/"
    Err "Install Docker Desktop, enable WSL2 integration in Settings, then re-run."
    Read-Host "Press Enter to exit"
    exit 1
}
Log "Docker found: $($dockerExe.Source)"

docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Err "Docker daemon is not running. Start Docker Desktop, then re-run."
    exit 1
}

# ---- 3. NVIDIA GPU passthrough -----------------------------
$nvsmi = docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi 2>&1
if ($LASTEXITCODE -ne 0) {
    Err "GPU passthrough failed. Steps to fix:"
    Err "  1) Install latest NVIDIA driver for Windows (with WSL support):"
    Err "     https://www.nvidia.com/Download/index.aspx"
    Err "  2) In Docker Desktop Settings > Resources > WSL Integration > Enable"
    Err "  3) Re-run this script"
    Read-Host "Press Enter to exit"
    exit 1
}
Log "OK GPU visible inside container"

# ---- 4. pull image ------------------------------------------
Log "pulling image $IMAGE (~6GB on first run)..."
docker pull $IMAGE

# ---- 5. start N containers -----------------------------------
Log "Spawning $N_INSTANCES container(s)..."
$names = @()
for ($i = 0; $i -lt $N_INSTANCES; $i++) {
    $port = $BASE_PORT + $i
    $name = if ($N_INSTANCES -eq 1) { "koikoi-trainer" } else { "koikoi-trainer-$i" }
    $vol  = if ($N_INSTANCES -eq 1) { "koikoi-runs" } else { "koikoi-runs-$i" }

    # Existing container を消す
    $existing = docker ps -a --filter "name=^${name}$" --format "{{.Names}}"
    if ($existing -eq $name) {
        Log "  removing existing $name..."
        docker rm -f $name | Out-Null
    }

    Log "  starting $name on port $port..."
    docker run -d --name $name --gpus all `
        -p "${port}:8990" `
        -v "${vol}:/app/runs" `
        --restart unless-stopped `
        $IMAGE | Out-Null
    $names += $name
}

# Wait for all
Log "waiting for daemons to come up..."
foreach ($i in 0..($N_INSTANCES - 1)) {
    $port = $BASE_PORT + $i
    $ok = $false
    for ($j = 0; $j -lt 30; $j++) {
        try {
            $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $ok = $true; break }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $ok) {
        Err "  port $port did not respond. check: docker logs $($names[$i])"
    } else {
        Log "  OK http://127.0.0.1:$port"
    }
}

# ---- 6. Firewall (LAN-only) ---------------------------------
$ruleName = "Koi-Koi Trainer Daemon (LAN)"
$rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
$ports = @($BASE_PORT..($BASE_PORT + $N_INSTANCES - 1))
if (-not $rule) {
    Log "adding firewall rule (LAN only) for ports $($ports -join ',')..."
    New-NetFirewallRule -DisplayName $ruleName `
        -Direction Inbound -Protocol TCP -LocalPort $ports `
        -Action Allow -Profile Private | Out-Null
} else {
    # Update ports
    Set-NetFirewallRule -DisplayName $ruleName -LocalPort $ports
}

# ---- 7. AutoStart on login ----------------------------------
$taskName = "KoikoiTrainerStart"
$startCmd = "docker start " + ($names -join " ")
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $startCmd"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $taskName -Force `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null

# ---- 8. summary ----------------------------------------------
$lanIp = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual `
    | Where-Object { $_.IPAddress -notmatch "^169\." -and $_.IPAddress -notmatch "^127\." } `
    | Select-Object -First 1 -ExpandProperty IPAddress)

Log "================================================="
Log "OK Koi-Koi trainer ready ($N_INSTANCES instances)"
foreach ($i in 0..($N_INSTANCES - 1)) {
    $port = $BASE_PORT + $i
    Log "  - http://${lanIp}:${port}  (container: $($names[$i]))"
}
Log "  - logs:      docker logs -f $($names[0])"
Log "  - stop all:  docker stop $($names -join ' ')"
Log "  - autostart: scheduled task '$taskName'"
Log "================================================="
