#!/usr/bin/env python3
"""Python (engine.py) と C++ (engine_dump 経由) のスループット比較。

C++ 側はサブプロセス + 行プロトコル経由で測るので、I/O オーバーヘッドが
含まれる。本来の C++ ネイティブの速度ではないが、Python から呼ぶときの
実用速度が分かる。
"""
import random
import subprocess
import time
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine import KoikoiEngine
from cpp_port.validate_engine import py_reset_with_deck, CppDriver


def bench_python(n_games: int) -> float:
    rng = random.Random(99)
    py = KoikoiEngine()
    t0 = time.perf_counter()
    for _ in range(n_games):
        deck_order = list(range(48))
        rng.shuffle(deck_order)
        py_reset_with_deck(py, rng.randrange(2), deck_order)
        while not py.done:
            legal = py.get_legal_actions()
            if not legal:
                break
            py.step(rng.choice(legal))
    return time.perf_counter() - t0


def bench_cpp(n_games: int) -> float:
    rng = random.Random(99)
    cpp = CppDriver()
    t0 = time.perf_counter()
    for _ in range(n_games):
        deck_order = list(range(48))
        rng.shuffle(deck_order)
        rules = {
            "koikoi_double": True, "seven_plus_double": False,
            "hanami": True, "tsukimi": True,
            "multi_koikoi": "last_koikoi", "ryuukyoku": "no_change",
        }
        state = cpp.reset(deck_order, rng.randrange(2), rules)
        while not state["done"]:
            legal = cpp.legal()
            if not legal:
                break
            action = rng.choice(legal)
            state, _ = cpp.step(action)
    elapsed = time.perf_counter() - t0
    cpp.close()
    return elapsed


def main():
    n = 500
    print(f"Benchmarking {n} random games each...")
    py_sec = bench_python(n)
    print(f"  Python : {py_sec:6.2f}s ({n/py_sec:7.1f} games/sec)")
    cpp_sec = bench_cpp(n)
    print(f"  C++ IPC: {cpp_sec:6.2f}s ({n/cpp_sec:7.1f} games/sec)")
    print(f"  Speedup: {py_sec/cpp_sec:.2f}x")
    print()
    print("Note: C++ via subprocess+stdio adds ~30µs/step overhead (I/O dominated).")
    print("Native C++ (in-process via pybind11) will be much faster.")


if __name__ == "__main__":
    main()
