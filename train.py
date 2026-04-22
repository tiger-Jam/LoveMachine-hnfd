#!/usr/bin/env python3
"""花札こいこい - Self-Play強化学習トレーニング v2

改善点:
  - 拡張観測空間 (250 → 340次元: 役進捗・月別分析・カード種別統計)
  - 大型ネットワーク (256x256 → 512x512)
  - LSTM対応 (--lstm フラグ, MaskableRecurrentPPOが必要)
  - 長時間学習向けハイパーパラメータ (学習率スケジュール等)

使い方:
    # 5000万ステップ (デフォルト)
    python train.py

    # LSTM有効 (MaskableRecurrentPPOが必要)
    python train.py --lstm

    # ステップ数指定
    python train.py --total-steps 10000000

    # 学習済みモデルで評価のみ
    python train.py --eval-only --model models/best_model.zip
"""

import argparse
import time
from pathlib import Path

import numpy as np

from engine import NUM_ACTIONS, KoikoiEngine, rule_based_policy
from env import KoikoiEnv


class SelfPlayManager:
    """DummyVecEnv内の全環境の対戦相手を一括更新する"""

    def __init__(self):
        self._policy_fn = None

    def set_opponent(self, policy_fn):
        self._policy_fn = policy_fn

    def __call__(self, engine: KoikoiEngine, player_idx: int) -> int:
        if self._policy_fn is None:
            return rule_based_policy(engine, player_idx)
        return self._policy_fn(engine, player_idx)


def make_self_play_opponent(model_path: str, use_lstm: bool = False):
    """保存済みモデルから対戦相手方策を生成"""
    if use_lstm:
        from lstm_maskable import MaskableRecurrentPPO
        opponent_model = MaskableRecurrentPPO.load(model_path)
    else:
        from sb3_contrib import MaskablePPO
        opponent_model = MaskablePPO.load(model_path)

    def policy(engine: KoikoiEngine, player_idx: int) -> int:
        obs = engine.get_observation(player_idx)
        mask = engine.get_action_mask()
        action, _ = opponent_model.predict(obs, action_masks=mask, deterministic=False)
        return int(action)

    return policy


def evaluate(model, n_games: int = 1000, opponent: str = "rule",
             use_lstm: bool = False) -> dict:
    """モデルを評価してwin rate等を返す"""
    env = KoikoiEnv(opponent_policy=opponent)
    wins = losses = draws = 0
    total_reward = 0.0

    for _ in range(n_games):
        obs, info = env.reset()
        done = False
        episode_reward = 0.0
        lstm_state = None
        episode_start = np.array([True])

        while not done:
            mask = env.action_masks()
            if use_lstm:
                action, lstm_state = model.predict(
                    obs, state=lstm_state, episode_start=episode_start,
                    action_masks=mask, deterministic=True,
                )
                episode_start = np.array([False])
            else:
                action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            done = terminated or truncated

        total_reward += episode_reward
        if info["winner"] == 0:
            wins += 1
        elif info["winner"] == 1:
            losses += 1
        else:
            draws += 1

    return {
        "win_rate": wins / n_games,
        "loss_rate": losses / n_games,
        "draw_rate": draws / n_games,
        "avg_reward": total_reward / n_games,
        "n_games": n_games,
    }


def _setup_model(args, env, use_lstm):
    """モデルを初期化またはロードする"""
    def linear_schedule(initial_value: float):
        def func(progress_remaining: float) -> float:
            return progress_remaining * initial_value
        return func

    policy_kwargs = dict(net_arch=[512, 512])

    if use_lstm:
        from lstm_maskable import MaskableRecurrentPPO
        policy_kwargs["lstm_hidden_size"] = 256
        policy_kwargs["n_lstm_layers"] = 1
        ModelClass = MaskableRecurrentPPO
        policy_name = "MlpLstmPolicy"
    else:
        from sb3_contrib import MaskablePPO
        ModelClass = MaskablePPO
        policy_name = "MlpPolicy"

    if args.resume:
        print(f"Resuming from {args.resume}")
        model = ModelClass.load(args.resume, env=env)
    else:
        model = ModelClass(
            policy_name,
            env,
            learning_rate=linear_schedule(3e-4),
            n_steps=2048,
            batch_size=512,
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            verbose=1,
            policy_kwargs=policy_kwargs,
        )

    return model


def train(args):
    from sb3_contrib.common.wrappers import ActionMasker
    from stable_baselines3.common.vec_env import DummyVecEnv

    use_lstm = args.lstm
    if use_lstm:
        try:
            from lstm_maskable import MaskableRecurrentPPO  # noqa: F401
            print("LSTM mode: MaskableRecurrentPPO (custom)")
        except Exception as e:
            print(f"WARNING: LSTM mode unavailable: {e}")
            print("  Falling back to MaskablePPO (512x512).\n")
            use_lstm = False

    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    n_envs = args.n_envs
    managers: list[SelfPlayManager] = []

    def make_env():
        mgr = SelfPlayManager()
        managers.append(mgr)

        def _init():
            env = KoikoiEnv(opponent_policy=mgr)
            return ActionMasker(env, lambda e: e.action_masks())

        return _init

    env = DummyVecEnv([make_env() for _ in range(n_envs)])
    model = _setup_model(args, env, use_lstm)

    update_interval = args.update_interval
    eval_interval = args.eval_interval
    total_steps = args.total_steps
    steps_done = 0
    best_win_rate = 0.0

    t_start = time.time()
    algo = "MaskableRecurrentPPO (LSTM)" if use_lstm else "MaskablePPO"
    print(f"Algorithm: {algo}")
    print(f"Network: 512x512" + (" + LSTM(256)" if use_lstm else ""))
    print(f"Observation: 340 dims (enhanced)")
    print(f"Training for {total_steps:,} steps ({n_envs} parallel envs)")
    print(f"Self-play update every {update_interval:,} steps")
    print(f"Evaluation every {eval_interval:,} steps")
    print()

    while steps_done < total_steps:
        chunk = min(update_interval, total_steps - steps_done)
        model.learn(total_timesteps=chunk, reset_num_timesteps=False)
        steps_done += chunk

        checkpoint_path = str(model_dir / "latest")
        model.save(checkpoint_path)

        if steps_done >= update_interval:
            opponent_fn = make_self_play_opponent(checkpoint_path, use_lstm=use_lstm)
            for mgr in managers:
                mgr.set_opponent(opponent_fn)

            elapsed = time.time() - t_start
            fps = steps_done / elapsed
            eta = (total_steps - steps_done) / fps
            print(f"[{steps_done:,}] Self-play updated  "
                  f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining, {fps:.0f} steps/s)")

        if steps_done % eval_interval < update_interval:
            print(f"\n[{steps_done:,}] Evaluating...")

            vs_random = evaluate(model, n_games=500, opponent="random",
                                 use_lstm=use_lstm)
            vs_rule = evaluate(model, n_games=500, opponent="rule",
                               use_lstm=use_lstm)

            print(f"  vs Random: win={vs_random['win_rate']:.1%}  "
                  f"loss={vs_random['loss_rate']:.1%}  "
                  f"avg_reward={vs_random['avg_reward']:.3f}")
            print(f"  vs Rule:   win={vs_rule['win_rate']:.1%}  "
                  f"loss={vs_rule['loss_rate']:.1%}  "
                  f"avg_reward={vs_rule['avg_reward']:.3f}")

            if vs_rule["win_rate"] > best_win_rate:
                best_win_rate = vs_rule["win_rate"]
                model.save(str(model_dir / "best_model"))
                print(f"  New best model! (win_rate={best_win_rate:.1%})")

            print()

    total_time = time.time() - t_start
    model.save(str(model_dir / "final_model"))

    print(f"\n[FINAL] Evaluating (1000 games each)...")
    vs_random = evaluate(model, n_games=1000, opponent="random", use_lstm=use_lstm)
    vs_rule = evaluate(model, n_games=1000, opponent="rule", use_lstm=use_lstm)
    print(f"  vs Random: win={vs_random['win_rate']:.1%}")
    print(f"  vs Rule:   win={vs_rule['win_rate']:.1%}")
    print(f"  Best model win rate: {best_win_rate:.1%}")
    print(f"\nTraining complete in {total_time:.0f}s ({total_time/3600:.1f}h). "
          f"Models saved to {model_dir}/")


def eval_only(args):
    use_lstm = args.lstm

    if use_lstm:
        from lstm_maskable import MaskableRecurrentPPO
        model = MaskableRecurrentPPO.load(args.model)
    else:
        from sb3_contrib import MaskablePPO
        model = MaskablePPO.load(args.model)

    print(f"Loaded model: {args.model}")

    for opponent in ["random", "rule"]:
        result = evaluate(model, n_games=2000, opponent=opponent, use_lstm=use_lstm)
        print(f"\nvs {opponent} ({result['n_games']} games):")
        print(f"  Win rate:    {result['win_rate']:.1%}")
        print(f"  Loss rate:   {result['loss_rate']:.1%}")
        print(f"  Draw rate:   {result['draw_rate']:.1%}")
        print(f"  Avg reward:  {result['avg_reward']:.4f}")


def main():
    parser = argparse.ArgumentParser(description="花札こいこい 強化学習トレーニング v2")
    parser.add_argument("--total-steps", type=int, default=50_000_000)
    parser.add_argument("--update-interval", type=int, default=200_000,
                        help="Self-play opponent update interval")
    parser.add_argument("--eval-interval", type=int, default=500_000,
                        help="Evaluation interval")
    parser.add_argument("--model-dir", type=str, default="models_v2",
                        help="Directory to save models")
    parser.add_argument("--n-envs", type=int, default=8,
                        help="Number of parallel environments")
    parser.add_argument("--lstm", action="store_true",
                        help="Use LSTM policy (requires MaskableRecurrentPPO)")
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to model to resume training from")
    parser.add_argument("--eval-only", action="store_true",
                        help="Evaluate a trained model only")
    parser.add_argument("--model", type=str, default=None,
                        help="Model path for --eval-only")
    args = parser.parse_args()

    if args.eval_only:
        if not args.model:
            parser.error("--eval-only requires --model")
        eval_only(args)
    else:
        train(args)


if __name__ == "__main__":
    main()
