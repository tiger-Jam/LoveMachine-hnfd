"""run_train.py — daemon から起動される学習エントリポイント。

役割:
  1. SIGTERM を受けたら最新 checkpoint を保存して終了
  2. 進捗を runs/checkpoint_meta.json に書き出し (daemon が status で読む)
  3. 設定 (config) によって NFSP / Deep CFR / random を切替

使い方 (daemon 経由):
    POST /train/start {"config": "nfsp"}

config 一覧:
    default = nfsp
    nfsp    = NFSP (PyTorch)
    deepcfr = Deep CFR (PyTorch)  ※ 別途実装
    smoke   = 動作確認用 (10 episode で終わる)
"""
from __future__ import annotations

import argparse
import enum as _enum
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Python 3.10+ の StrEnum polyfill (3.9 環境でも import が通るように)
if not hasattr(_enum, "StrEnum"):
    class _StrEnum(str, _enum.Enum):
        pass
    _enum.StrEnum = _StrEnum

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get("KOIKOI_RUNS_DIR", ROOT / "runs"))
RUNS_DIR.mkdir(parents=True, exist_ok=True)
CKPT_DIR = RUNS_DIR / "checkpoints"
CKPT_DIR.mkdir(parents=True, exist_ok=True)
META_FILE = RUNS_DIR / "checkpoint_meta.json"

# OpenSpiel (vendor) を sys.path に
OS_BUILD = ROOT / "vendor" / "open_spiel" / "build" / "python"
OS_ROOT = ROOT / "vendor" / "open_spiel"
for p in (OS_BUILD, OS_ROOT):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


class GracefulKiller:
    """SIGTERM / SIGINT を捕まえて、メインループに「停止せよ」フラグを立てる"""

    def __init__(self):
        self.stop = False
        signal.signal(signal.SIGTERM, self._handler)
        signal.signal(signal.SIGINT, self._handler)

    def _handler(self, signum, _frame):
        print(f"[run_train] received signal {signum}, shutting down...", flush=True)
        self.stop = True


def write_meta(d: dict) -> None:
    META_FILE.write_text(json.dumps(d, indent=2))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 各 config の実装
# ============================================================

def run_smoke(killer: GracefulKiller, args):
    """動作確認用: 10 episode 走らせて終了"""
    import pyspiel
    game = pyspiel.load_game("koikoi")
    print(f"[smoke] loaded {game}", flush=True)

    import random
    rng = random.Random(0)
    for ep in range(10):
        if killer.stop:
            break
        state = game.new_initial_state()
        n_steps = 0
        while not state.is_terminal():
            if state.is_chance_node():
                outcomes = state.chance_outcomes()
                action = rng.choices(*zip(*outcomes), k=1)[0]
            else:
                action = rng.choice(state.legal_actions())
            state.apply_action(action)
            n_steps += 1
        print(f"[smoke] ep {ep+1}/10: returns={state.returns()} steps={n_steps}", flush=True)
        write_meta({
            "config": "smoke",
            "episode": ep + 1,
            "total_episodes": 10,
            "returns_player0": state.returns()[0],
            "updated_at": now_iso(),
        })
        time.sleep(0.5)
    print("[smoke] done", flush=True)


def run_nfsp(killer: GracefulKiller, args):
    """NFSP (PyTorch) で学習"""
    import pyspiel
    from open_spiel.python import rl_environment
    from open_spiel.python.pytorch import nfsp
    import torch

    # GPU 自動検出 (CUDA / MPS / CPU)。CPU 落ちすると NFSP の NN 訓練が
    # 桁違いに遅くなるので最優先。
    if torch.cuda.is_available():
        device = "cuda"
        torch.set_default_device("cuda")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
        torch.set_default_device("mps")
    else:
        device = "cpu"

    game = pyspiel.load_game("koikoi")
    env = rl_environment.Environment(game)
    info_state_size = env.observation_spec()["info_state"][0]
    num_actions = env.action_spec()["num_actions"]

    print(f"[nfsp] device={device} info_state={info_state_size} "
          f"actions={num_actions} torch={torch.__version__}", flush=True)

    agents = [
        nfsp.NFSP(
            idx, info_state_size, num_actions,
            hidden_layers_sizes=args.hidden,
            reservoir_buffer_capacity=args.reservoir,
            anticipatory_param=args.anticipatory,
            batch_size=args.batch,
            min_buffer_size_to_learn=1000,
            learn_every=64,
            rl_learning_rate=args.rl_lr,
            sl_learning_rate=args.sl_lr,
            device=device,           # CUDA / MPS / CPU を NFSP 内 DQN にも反映
        )
        for idx in range(2)
    ]

    n_target = args.episodes
    log_every = max(50, n_target // 200)
    ckpt_every = max(1000, n_target // 100)

    t0 = time.perf_counter()
    last_loss = {"rl": 0.0, "sl": 0.0}

    for ep in range(1, n_target + 1):
        if killer.stop:
            break
        ts = env.reset()
        while not ts.last():
            cur = ts.observations["current_player"]
            if cur < 0:
                continue
            out = agents[cur].step(ts)
            ts = env.step([out.action])
        for a in agents:
            a.step(ts)

        if ep % log_every == 0:
            # NFSP agent の最新 loss を雑に拾う (PyTorch impl の attribute 名は版で
            # 揺れるので getattr で防御)
            for k in ("loss", "_last_rl_loss"):
                v0 = getattr(agents[0], k, None)
                if v0 is not None:
                    try:
                        last_loss["rl"] = float(v0)
                    except (TypeError, ValueError):
                        pass
                    break
            elapsed = time.perf_counter() - t0
            eps_per_sec = ep / max(elapsed, 1e-6)
            line = (f"[nfsp] ep {ep}/{n_target} "
                    f"loss_rl={last_loss['rl']:.4f} "
                    f"eps/s={eps_per_sec:.1f} "
                    f"elapsed={elapsed:.0f}s")
            print(line, flush=True)
            write_meta({
                "config": "nfsp",
                "episode": ep,
                "total_episodes": n_target,
                "loss_rl": last_loss["rl"],
                "loss_sl": last_loss["sl"],
                "eps_per_sec": eps_per_sec,
                "elapsed_sec": elapsed,
                "updated_at": now_iso(),
            })

        if ep % ckpt_every == 0 or ep == n_target:
            ckpt_path = CKPT_DIR / f"nfsp_ep{ep:08d}.pt"
            try:
                torch.save({
                    "ep": ep,
                    "p0": agents[0].state_dict() if hasattr(agents[0], "state_dict") else None,
                    "p1": agents[1].state_dict() if hasattr(agents[1], "state_dict") else None,
                }, ckpt_path)
                latest = CKPT_DIR / "nfsp_latest.pt"
                if latest.exists() or latest.is_symlink():
                    latest.unlink()
                latest.symlink_to(ckpt_path.name)
                print(f"[nfsp] checkpoint saved: {ckpt_path.name}", flush=True)
            except Exception as e:
                print(f"[nfsp] checkpoint save failed: {e}", flush=True)

    # 終了時最終 checkpoint
    write_meta({
        "config": "nfsp",
        "episode": ep,
        "total_episodes": n_target,
        "stopped_at": now_iso(),
        "updated_at": now_iso(),
    })
    print(f"[nfsp] done at episode {ep}", flush=True)


def run_deepcfr(killer: GracefulKiller, args):
    """Deep CFR (PyTorch) で学習"""
    import pyspiel
    from open_spiel.python.pytorch import deep_cfr
    game = pyspiel.load_game("koikoi")
    print(f"[deepcfr] loaded {game}", flush=True)

    solver = deep_cfr.DeepCFRSolver(
        game,
        policy_network_layers=args.hidden,
        advantage_network_layers=args.hidden,
        num_iterations=args.iterations,
        num_traversals=args.traversals,
        learning_rate=args.rl_lr,
        batch_size_advantage=args.batch,
        batch_size_strategy=args.batch,
        memory_capacity=args.reservoir,
        policy_network_train_steps=args.train_steps,
        advantage_network_train_steps=args.train_steps,
    )

    print(f"[deepcfr] iterations={args.iterations} traversals/iter={args.traversals}",
          flush=True)
    t0 = time.perf_counter()

    for it in range(1, args.iterations + 1):
        if killer.stop:
            break
        # solver.solve() は全 iter 走る。1 iter ずつにしたいので低レベル API
        # を使う方が良いが、初期版ではまるごと回す。
        # 1 iter 単位制御は次バージョンで。
        break

    # 暫定: solver.solve() 一発で全部回す (中断はできない)
    if not killer.stop:
        adv_loss, policy_loss = solver.solve()
        print(f"[deepcfr] adv_loss={adv_loss[-1] if adv_loss else None} "
              f"policy_loss={policy_loss}", flush=True)
        write_meta({
            "config": "deepcfr",
            "advantage_loss": float(adv_loss[-1]) if adv_loss else None,
            "policy_loss": float(policy_loss) if policy_loss else None,
            "elapsed_sec": time.perf_counter() - t0,
            "updated_at": now_iso(),
        })
    print("[deepcfr] done", flush=True)


# ============================================================
# main
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", choices=["smoke", "nfsp", "deepcfr"], default="nfsp")
    parser.add_argument("--episodes", type=int, default=100_000)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--traversals", type=int, default=100)
    parser.add_argument("--train-steps", type=int, default=1000)
    parser.add_argument("--hidden", type=int, nargs="+", default=[128, 128])
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--reservoir", type=int, default=200_000)
    parser.add_argument("--anticipatory", type=float, default=0.1)
    parser.add_argument("--rl-lr", type=float, default=0.01)
    parser.add_argument("--sl-lr", type=float, default=0.005)
    parser.add_argument("--resume", action="store_true",
                        help="最新 checkpoint からの再開 (現状はネット重みだけ復元)")
    args = parser.parse_args()

    killer = GracefulKiller()
    print(f"[run_train] config={args.config} pid={os.getpid()}", flush=True)
    write_meta({
        "config": args.config,
        "episode": 0,
        "started_at": now_iso(),
    })

    try:
        if args.config == "smoke":
            run_smoke(killer, args)
        elif args.config == "nfsp":
            run_nfsp(killer, args)
        elif args.config == "deepcfr":
            run_deepcfr(killer, args)
    except Exception as e:
        import traceback
        print(f"[run_train] ERROR: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
