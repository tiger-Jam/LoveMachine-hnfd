#!/usr/bin/env python3
"""engine.py vs cpp_port/koikoi/engine_dump のクロス検証。

戦略:
  1. 乱数で 48 枚順列 + oya + ルールを生成
  2. Python 側 KoikoiEngine.reset_with_deck で初期化 (新規追加メソッド)
  3. C++ engine_dump サブプロセスに同じ deck/oya/rules を送り、RESET
  4. 両者の state が完全一致するか比較
  5. legal action からランダムに1つ選び、両者に同じ action を適用 step
  6. step 毎に state, events, observation を比較
  7. ゲーム終了まで繰り返し
  8. 多数ゲーム (default 200) 走らせて全一致を確認

使い方:
    python3 cpp_port/validate_engine.py [--games N] [--seed S] [--verbose]
"""

import argparse
import random
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# validate は「純 Python 実装 vs C++ 実装」を比較する。
# engine.py が C++ shim になっているため、engine_py から直接 import する。
from engine_py import KoikoiEngine, Phase, ACTION_KOIKOI, ACTION_SHOWDOWN
from core import make_deck

CPP_BIN = REPO / "cpp_port" / "koikoi" / "engine_dump"


# ============ Python 側に外部 deck 注入できる reset を用意 ============

def py_reset_with_deck(engine: KoikoiEngine, oya: int, deck_order: list[int]) -> dict:
    """engine.py::reset を拡張: 内部 _master_deck から deck_order の順で札を並べた
    状態にする。RNG.shuffle(cards) の結果を外部から指定するのと等価。"""
    from collections import Counter
    cards = [engine._master_deck[i] for i in deck_order]
    engine.players_hand = [cards[0:8], cards[8:16]]
    engine.players_captured = [[], []]
    engine.players_koikoi = [False, False]
    engine.players_prev_yaku = [0, 0]
    engine.first_koikoi_player = None
    engine.last_koikoi_player = None
    engine.field = cards[16:24]
    engine.deck = cards[24:]
    engine.current_player = oya
    engine.oya_index = oya
    engine.phase = Phase.HAND_PLAY
    engine.done = False
    engine.winner = None
    engine.win_score = 0
    engine.ryuukyoku = False
    engine.ryuukyoku_oya_swap = False
    engine._pending_played = None
    engine._pending_matches = []

    special = engine._check_special_deal()
    info = {}
    if special:
        info["special"] = special
    return info


# ============ C++ engine_dump サブプロセスラッパ ============

class CppDriver:
    def __init__(self):
        self.proc = subprocess.Popen(
            [str(CPP_BIN)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1,
        )

    def close(self):
        self.send("QUIT")
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.wait(timeout=5)

    def send(self, line: str):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def recv(self) -> str:
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("C++ process closed unexpectedly")
        return line.rstrip("\n")

    def reset(self, deck: list[int], oya: int, rules: dict) -> dict:
        self.send("DECK " + " ".join(str(x) for x in deck))
        assert self.recv() == "OK"
        self.send(f"OYA {oya}")
        assert self.recv() == "OK"
        rule_line = (
            f"RULES "
            f"{int(rules['koikoi_double'])} "
            f"{int(rules['seven_plus_double'])} "
            f"{int(rules['hanami'])} {int(rules['tsukimi'])} "
            f"{rules['multi_koikoi']} {rules['ryuukyoku']}"
        )
        self.send(rule_line)
        assert self.recv() == "OK"
        self.send("RESET")
        return self._read_state()

    def step(self, action: int):
        self.send(f"ACTION {action}")
        state = self._read_state()
        evs = self._read_events()
        return state, evs

    def obs(self, player: int) -> list[float]:
        self.send(f"OBS {player}")
        line = self.recv()
        assert line.startswith("OBS"), f"unexpected: {line!r}"
        return [float(x) for x in line.split()[1:]]

    def legal(self) -> list[int]:
        self.send("LEGAL")
        line = self.recv()
        assert line.startswith("LEGAL")
        rest = line[5:].strip()
        if not rest:
            return []
        return [int(x) for x in rest.split(",")]

    def _read_state(self) -> dict:
        line = self.recv()
        assert line.startswith("STATE "), f"unexpected: {line!r}"
        kv = {}
        for tok in line[6:].split():
            k, _, v = tok.partition("=")
            kv[k] = v
        def csv(s):
            return [int(x) for x in s.split(",")] if s else []
        return {
            "phase":      kv["phase"],
            "current":    int(kv["cur"]),
            "oya":        int(kv["oya"]),
            "done":       int(kv["done"]),
            "winner":     int(kv["winner"]),
            "score":      int(kv["score"]),
            "ryuu":       int(kv["ryuu"]),
            "ryuu_swap":  int(kv["ryuu_swap"]),
            "h0":         csv(kv["h0"]),
            "h1":         csv(kv["h1"]),
            "c0":         csv(kv["c0"]),
            "c1":         csv(kv["c1"]),
            "field":      csv(kv["field"]),
            "deck":       csv(kv["deck"]),
            "kk0":        int(kv["kk0"]),
            "kk1":        int(kv["kk1"]),
            "prev0":      int(kv["prev0"]),
            "prev1":      int(kv["prev1"]),
            "first_kk":   int(kv["first_kk"]),
            "last_kk":    int(kv["last_kk"]),
            "pending":    int(kv["pending"]),
            "pmatches":   csv(kv["pmatches"]),
            "special":    kv.get("special", "none"),
        }

    def _read_events(self):
        line = self.recv()
        assert line.startswith("EVENTS "), f"unexpected: {line!r}"
        n = int(line.split()[1])
        evs = []
        for _ in range(n):
            ev = self.recv()
            assert ev.startswith("EV "), f"unexpected: {ev!r}"
            evs.append(ev[3:])
        return evs


# ============ Python 側の state 同形式抽出 ============

def py_state(engine: KoikoiEngine, special_info=None) -> dict:
    phase_map = {
        Phase.HAND_PLAY:  "HAND_PLAY",
        Phase.HAND_MATCH: "HAND_MATCH",
        Phase.DRAW_MATCH: "DRAW_MATCH",
        Phase.KOIKOI:     "KOIKOI",
        Phase.DONE:       "DONE",
    }
    sp = "none"
    if special_info:
        s = special_info.get("special")
        if s == "redeal":
            sp = "redeal"
        elif s and s.startswith("teshi:"):
            sp = s
        elif s and s.startswith("kuttsuki:"):
            sp = s
    return {
        "phase":      phase_map[engine.phase],
        "current":    engine.current_player,
        "oya":        engine.oya_index,
        "done":       int(engine.done),
        "winner":     -1 if engine.winner is None else engine.winner,
        "score":      engine.win_score,
        "ryuu":       int(engine.ryuukyoku),
        "ryuu_swap":  int(engine.ryuukyoku_oya_swap),
        "h0":         [c.id for c in engine.players_hand[0]],
        "h1":         [c.id for c in engine.players_hand[1]],
        "c0":         [c.id for c in engine.players_captured[0]],
        "c1":         [c.id for c in engine.players_captured[1]],
        "field":      [c.id for c in engine.field],
        "deck":       [c.id for c in engine.deck],
        "kk0":        int(engine.players_koikoi[0]),
        "kk1":        int(engine.players_koikoi[1]),
        "prev0":      engine.players_prev_yaku[0],
        "prev1":      engine.players_prev_yaku[1],
        "first_kk":   -1 if engine.first_koikoi_player is None else engine.first_koikoi_player,
        "last_kk":    -1 if engine.last_koikoi_player is None else engine.last_koikoi_player,
        "pending":    -1 if engine._pending_played is None else engine._pending_played.id,
        "pmatches":   [c.id for c in engine._pending_matches],
        "special":    sp,
    }


def py_event_str(ev: tuple) -> str:
    """engine.py の event tuple を engine_dump と同じ文字列に正規化"""
    name = ev[0]
    if name == "hand_no_match":      return f"hand_no_match {ev[1]}"
    if name == "hand_match":         return f"hand_match {ev[1]} {ev[2]}"
    if name == "hand_match_all":     return f"hand_match_all {ev[1]} {','.join(str(x) for x in ev[2])}"
    if name == "hand_choose":        return f"hand_choose {ev[1]} {','.join(str(x) for x in ev[2])}"
    if name == "draw":               return f"draw {ev[1]}"
    if name == "draw_match":         return f"draw_match {ev[1]} {ev[2]}"
    if name == "draw_match_all":     return f"draw_match_all {ev[1]} {','.join(str(x) for x in ev[2])}"
    if name == "draw_choose":        return f"draw_choose {ev[1]} {','.join(str(x) for x in ev[2])}"
    if name == "yaku_formed":
        # ev = ("yaku_formed", player, [(yname, p), ...], total_pts)
        ystr = ",".join(f"{n}:{p}" for n, p in ev[2])
        return f"yaku_formed {ev[1]} {ev[3]} {ystr}"
    if name == "showdown":           return f"showdown {ev[1]} {ev[2]}"
    if name == "koikoi":             return f"koikoi {ev[1]}"
    if name == "bonus_7plus":        return "bonus_7plus"
    if name == "bonus_opponent_koikoi": return "bonus_opponent_koikoi"
    if name == "round_end":          return f"round_end {ev[1]} {ev[2]}"
    if name == "exhausted":          return "exhausted"
    raise ValueError(f"unknown event: {ev!r}")


# ============ メインループ ============

def first_diff(a: dict, b: dict) -> str:
    for k in a:
        if a[k] != b[k]:
            return f"{k}: py={a[k]!r} cpp={b[k]!r}"
    return ""


def run_one_game(rng: random.Random, cpp: CppDriver, verbose=False) -> tuple[bool, str]:
    deck_order = list(range(48))
    rng.shuffle(deck_order)
    oya = rng.randrange(2)
    rules = {
        "koikoi_double": rng.choice([True, False]),
        "seven_plus_double": rng.choice([True, False]),
        "hanami": rng.choice([True, False]),
        "tsukimi": rng.choice([True, False]),
        "multi_koikoi": rng.choice(["oyaken", "last_koikoi", "first_koikoi"]),
        "ryuukyoku": rng.choice(["oyaken", "no_change", "change"]),
    }

    py = KoikoiEngine(rules)
    py_info = py_reset_with_deck(py, oya, deck_order)

    cpp_state = cpp.reset(deck_order, oya, rules)
    pys = py_state(py, py_info)
    if pys != cpp_state:
        return False, f"RESET diverge: {first_diff(pys, cpp_state)}"

    # 観測も初期で確認
    for p in (0, 1):
        py_obs = py.get_observation(p).tolist()
        cpp_obs = cpp.obs(p)
        for i, (a, b) in enumerate(zip(py_obs, cpp_obs)):
            if abs(a - b) > 1e-5:
                return False, f"RESET obs[{p}][{i}] diverge: py={a} cpp={b}"

    step = 0
    while not py.done:
        legal = py.get_legal_actions()
        if not legal:
            return False, f"step {step}: legal empty but not done (py state: {pys})"
        cpp_legal = cpp.legal()
        if list(legal) != list(cpp_legal):
            return False, f"step {step}: legal diverge py={legal} cpp={cpp_legal}"
        action = rng.choice(legal)

        py_info = py.step(action)
        py_evs = [py_event_str(e) for e in py_info["events"]]
        cpp_state, cpp_evs = cpp.step(action)
        pys = py_state(py)
        if pys != cpp_state:
            return False, f"step {step} action={action}: state diverge: {first_diff(pys, cpp_state)}"
        if py_evs != cpp_evs:
            return False, f"step {step} action={action}: events diverge\n  py={py_evs}\n  cpp={cpp_evs}"

        # 観測も時々確認 (毎ステップは重い)
        if step % 5 == 0 and not py.done:
            for p in (0, 1):
                py_obs = py.get_observation(p).tolist()
                cpp_obs = cpp.obs(p)
                for i, (a, b) in enumerate(zip(py_obs, cpp_obs)):
                    if abs(a - b) > 1e-5:
                        return False, f"step {step} obs[{p}][{i}] diverge: py={a} cpp={b}"
        step += 1
        if step > 500:
            return False, f"step limit exceeded"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not CPP_BIN.exists():
        print(f"ERROR: {CPP_BIN} not found. Run `make` in cpp_port/ first.", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(args.seed)
    cpp = CppDriver()
    try:
        n_pass = 0
        for g in range(args.games):
            ok, msg = run_one_game(rng, cpp, verbose=args.verbose)
            if ok:
                n_pass += 1
                if args.verbose:
                    print(f"[{g+1}/{args.games}] PASS")
            else:
                print(f"[{g+1}/{args.games}] FAIL: {msg}")
                cpp.close()
                sys.exit(1)
        print(f"PASS — {n_pass}/{args.games} games fully identical (state + events + obs)")
    finally:
        cpp.close()


if __name__ == "__main__":
    main()
