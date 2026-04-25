#!/usr/bin/env python3
"""koikoi OpenSpiel ゲームの動作確認 + NFSP smoke test.

前提:
  - vendor/open_spiel/ をソースビルド済み (build/python/pyspiel*.so 存在)
  - PYTHONPATH に build ディレクトリが入ってる、または手動で sys.path 追加

使い方:
    PYTHONPATH=vendor/open_spiel/build/python:vendor/open_spiel \\
        python3 cpp_port/nfsp_smoke.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OS_BUILD = REPO / "vendor" / "open_spiel" / "build" / "python"
OS_ROOT  = REPO / "vendor" / "open_spiel"
for p in (OS_BUILD, OS_ROOT):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pyspiel
print(f"pyspiel from: {pyspiel.__file__}")

# === ゲームロード確認 ===
game = pyspiel.load_game("koikoi")
print(f"loaded: {game}")
print(f"  num_players       = {game.num_players()}")
print(f"  num_distinct_actions = {game.num_distinct_actions()}")
print(f"  max_game_length   = {game.max_game_length()}")
print(f"  obs_tensor_shape  = {game.observation_tensor_shape()}")

# === RandomSimTest 相当 ===
import random
rng = random.Random(0)
n_games = 20
for g in range(n_games):
    state = game.new_initial_state()
    while not state.is_terminal():
        if state.is_chance_node():
            outcomes = state.chance_outcomes()
            actions, probs = zip(*outcomes)
            action = rng.choices(actions, weights=probs, k=1)[0]
        else:
            legal = state.legal_actions()
            action = rng.choice(legal)
        state.apply_action(action)
    if g < 3 or g >= n_games - 2:
        print(f"  game {g+1}: returns={state.returns()}")
print(f"RandomSimTest PASS ({n_games} games)")
# === MCCFR smoke (純 Python、依存軽い) ===
print()
print("=== ExternalSamplingMCCFR smoke test ===")
import time
from open_spiel.python.algorithms import external_sampling_mccfr as ext_mccfr

solver = ext_mccfr.ExternalSamplingSolver(
    game, ext_mccfr.AverageType.SIMPLE)

n_iters = 3
t0 = time.perf_counter()
for it in range(n_iters):
    solver.iteration()
    print(f"  iter {it+1}/{n_iters}: info_states={len(solver._infostates)} "
          f"({time.perf_counter()-t0:.1f}s)")
print(f"MCCFR smoke PASS ({n_iters} iters)")

# === PyTorch NFSP smoke ===
print()
print("=== PyTorch NFSP smoke test ===")
try:
    from open_spiel.python import rl_environment
    from open_spiel.python.pytorch import nfsp as pt_nfsp
    import torch
    print(f"  torch={torch.__version__}")

    env = rl_environment.Environment(game)
    info_state_size = env.observation_spec()["info_state"][0]
    num_actions = env.action_spec()["num_actions"]

    agents = [
        pt_nfsp.NFSP(idx, info_state_size, num_actions,
                     hidden_layers_sizes=[64, 64],
                     reservoir_buffer_capacity=10000,
                     anticipatory_param=0.1,
                     batch_size=32,
                     min_buffer_size_to_learn=100,
                     learn_every=64)
        for idx in range(2)
    ]

    n_ep = 30
    t0 = time.perf_counter()
    for ep in range(n_ep):
        ts = env.reset()
        while not ts.last():
            cur = ts.observations["current_player"]
            if cur < 0:  # chance ノードは env が処理
                continue
            out = agents[cur].step(ts)
            ts = env.step([out.action])
        for a in agents:
            a.step(ts)
        if (ep + 1) % 10 == 0:
            print(f"  episode {ep+1}/{n_ep}")
    print(f"NFSP smoke PASS ({n_ep} eps in {time.perf_counter()-t0:.1f}s)")
except Exception as e:
    print(f"NFSP failed: {type(e).__name__}: {e}")
