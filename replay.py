#!/usr/bin/env python3
"""花札こいこい - 棋譜再生バリデータ

保存されている v2 棋譜を engine で再生し、
seed / 初期配札 / 各決定点の可視状態 / 非可視状態 / 合法手 / 最終役 / スコア が
完全一致するかを検証する。

使い方:
    python3 replay.py                     # ./kifu/ 配下の全ファイルを検査
    python3 replay.py kifu/kifu_xxx.json  # 特定ファイルだけ検査
    python3 replay.py --verbose           # 決定点ごとの詳細ログ
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core import check_yaku
from engine import ACTION_KOIKOI, ACTION_SHOWDOWN, KoikoiEngine


@dataclass
class Mismatch:
    path: str
    message: str


def _ids(cards_info_list: list) -> list[int]:
    return [c["id"] for c in cards_info_list]


def _eq_list(a: Iterable, b: Iterable, label: str, *, ordered: bool = True) -> None:
    la, lb = list(a), list(b)
    if ordered:
        if la != lb:
            raise AssertionError(f"{label} mismatch: saved={la} actual={lb}")
    else:
        if sorted(la) != sorted(lb):
            raise AssertionError(f"{label} mismatch: saved={sorted(la)} actual={sorted(lb)}")


def _action_to_int(action: dict) -> int:
    kind = action["kind"]
    if kind == "koikoi":
        return ACTION_KOIKOI
    if kind == "showdown":
        return ACTION_SHOWDOWN
    return action["id"]


def validate_round(round_entry: dict, rules: dict, *, verbose: bool = False) -> None:
    rnum = round_entry["round"]
    oya = round_entry["oya"]
    seed = round_entry["seed"]

    engine = KoikoiEngine(rules=rules)
    info = engine.reset(oya=oya, seed=seed)

    # An early special deal should not happen here, because GameSession
    # retries on "redeal" before saving. teshi/kuttsuki, however, can.
    saved_special = round_entry.get("special")
    actual_special = info.get("special")
    if actual_special == "redeal":
        raise AssertionError(f"round {rnum} replay produced a redeal (seed/RNG logic changed?)")
    if saved_special != actual_special:
        raise AssertionError(
            f"round {rnum} special mismatch: saved={saved_special} actual={actual_special}"
        )

    deal = round_entry["initial_deal"]
    _eq_list(_ids(deal["player_hand"]),   [c.id for c in engine.players_hand[0]], f"r{rnum} deal.player_hand")
    _eq_list(_ids(deal["opponent_hand"]), [c.id for c in engine.players_hand[1]], f"r{rnum} deal.opponent_hand")
    _eq_list(_ids(deal["field"]),         [c.id for c in engine.field],            f"r{rnum} deal.field")
    _eq_list(_ids(deal["deck_order"]),    [c.id for c in engine.deck],             f"r{rnum} deal.deck_order")

    # Special deal means the round is decided at reset; there should be no decisions.
    if engine.done:
        decisions = round_entry.get("decisions") or []
        if decisions:
            raise AssertionError(f"round {rnum} was decided at deal but has {len(decisions)} decisions")
        if round_entry["end_reason"] != "special":
            raise AssertionError(f"round {rnum} special deal but end_reason={round_entry['end_reason']}")
        if engine.winner != round_entry["winner"]:
            raise AssertionError(f"round {rnum} special winner mismatch")
        if engine.win_score != round_entry["score"]:
            raise AssertionError(f"round {rnum} special score mismatch")
        return

    for dec in round_entry["decisions"]:
        actor = dec["player"]
        expected_phase = dec["phase"]
        if engine.phase.name != expected_phase:
            raise AssertionError(
                f"r{rnum} dec#{dec['index']} phase: saved={expected_phase} actual={engine.phase.name}"
            )
        if engine.current_player != actor:
            raise AssertionError(
                f"r{rnum} dec#{dec['index']} actor: saved={actor} actual={engine.current_player}"
            )

        v = dec["visible"]
        opp = 1 - actor
        _eq_list(_ids(v["self_hand"]),          [c.id for c in engine.players_hand[actor]],     f"r{rnum} d{dec['index']} visible.self_hand")
        _eq_list(_ids(v["field"]),              [c.id for c in engine.field],                   f"r{rnum} d{dec['index']} visible.field")
        _eq_list(_ids(v["self_captured"]),      [c.id for c in engine.players_captured[actor]], f"r{rnum} d{dec['index']} visible.self_captured")
        _eq_list(_ids(v["opponent_captured"]),  [c.id for c in engine.players_captured[opp]],   f"r{rnum} d{dec['index']} visible.opponent_captured")
        if v["opponent_hand_count"] != len(engine.players_hand[opp]):
            raise AssertionError(f"r{rnum} d{dec['index']} opponent_hand_count mismatch")
        if v["deck_remaining"] != len(engine.deck):
            raise AssertionError(f"r{rnum} d{dec['index']} deck_remaining mismatch")
        if bool(v["self_koikoi"]) != bool(engine.players_koikoi[actor]):
            raise AssertionError(f"r{rnum} d{dec['index']} self_koikoi mismatch")
        if bool(v["opponent_koikoi"]) != bool(engine.players_koikoi[opp]):
            raise AssertionError(f"r{rnum} d{dec['index']} opponent_koikoi mismatch")
        pending_saved = (v["pending_card"] or {}).get("id") if v["pending_card"] else None
        pending_actual = engine._pending_played.id if engine._pending_played is not None else None
        if pending_saved != pending_actual:
            raise AssertionError(f"r{rnum} d{dec['index']} pending_card mismatch")

        # Hidden (ground truth)
        h = dec["hidden"]
        _eq_list(_ids(h["opponent_hand"]), [c.id for c in engine.players_hand[opp]],
                 f"r{rnum} d{dec['index']} hidden.opponent_hand")

        # Legal actions
        _eq_list(dec["legal_actions"], engine.get_legal_actions(),
                 f"r{rnum} d{dec['index']} legal_actions", ordered=False)

        # Saved yaku snapshot sanity
        saved_self_yaku = [tuple(y) for y in v["self_yaku"]]
        actual_self_yaku = [(n, p) for n, p in check_yaku(engine.players_captured[actor], rules)]
        if saved_self_yaku != actual_self_yaku:
            raise AssertionError(f"r{rnum} d{dec['index']} self_yaku mismatch")

        # Apply action
        act = _action_to_int(dec["action"])
        if act not in engine.get_legal_actions():
            raise AssertionError(f"r{rnum} d{dec['index']} illegal action {act}")
        engine.step(act)

        if verbose:
            print(f"  r{rnum} d{dec['index']} P{actor} {dec['phase']:11s} -> {dec['action']}")

    if round_entry.get("finished_at") is None:
        # Round is still in progress — only per-decision checks apply.
        return

    if not engine.done:
        raise AssertionError(f"r{rnum} replay ended with engine not done")

    if engine.winner != round_entry["winner"]:
        raise AssertionError(f"r{rnum} winner mismatch: saved={round_entry['winner']} actual={engine.winner}")
    if engine.win_score != round_entry["score"]:
        raise AssertionError(f"r{rnum} score mismatch: saved={round_entry['score']} actual={engine.win_score}")

    saved_p0 = [tuple(y) for y in round_entry["yaku_at_end"]["player"]]
    saved_p1 = [tuple(y) for y in round_entry["yaku_at_end"]["opponent"]]
    actual_p0 = [(n, p) for n, p in check_yaku(engine.players_captured[0], rules)]
    actual_p1 = [(n, p) for n, p in check_yaku(engine.players_captured[1], rules)]
    if saved_p0 != actual_p0:
        raise AssertionError(f"r{rnum} final player yaku mismatch: saved={saved_p0} actual={actual_p0}")
    if saved_p1 != actual_p1:
        raise AssertionError(f"r{rnum} final opponent yaku mismatch: saved={saved_p1} actual={actual_p1}")


SKIP = object()


def validate_file(path: Path, *, verbose: bool = False):
    with open(path, encoding="utf-8") as f:
        kifu = json.load(f)

    if kifu.get("version") != 2:
        return SKIP

    rules = kifu["rules"]
    # Kifu recorded before the exhaust-rule split can't replay under the
    # current engine — the "exhaust" key no longer drives anything.
    if "exhaust" in rules and "multi_koikoi" not in rules and "ryuukyoku" not in rules:
        return SKIP
    total = [0, 0]
    for round_entry in kifu["rounds"]:
        validate_round(round_entry, rules, verbose=verbose)
        if round_entry["winner"] is not None:
            total[round_entry["winner"]] += round_entry["score"]

    if kifu.get("status") == "completed":
        if total != kifu["scores"]:
            raise AssertionError(f"session scores mismatch: computed={total} saved={kifu['scores']}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate v2 kifu files by replaying them.")
    ap.add_argument("paths", nargs="*", help="kifu file(s); default: all ./kifu/kifu_*.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.paths:
        files = [Path(p) for p in args.paths]
    else:
        files = sorted(Path(__file__).parent.joinpath("kifu").glob("kifu_*.json"))

    if not files:
        print("no kifu files found")
        return 0

    ok, bad, skipped = 0, 0, 0
    for path in files:
        try:
            result = validate_file(path, verbose=args.verbose)
            if result is SKIP:
                print(f"– {path.name} (legacy / non-v2, skipped)")
                skipped += 1
            else:
                print(f"✓ {path.name}")
                ok += 1
        except AssertionError as e:
            print(f"✗ {path.name}: {e}")
            bad += 1
        except Exception as e:  # noqa: BLE001
            print(f"✗ {path.name}: {type(e).__name__}: {e}")
            bad += 1

    print(f"\n{ok} ok, {bad} fail, {skipped} skipped")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
