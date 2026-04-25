"""花札こいこい — engine.py の C++ 実装ラッパ

`engine.py` と同一 API を提供する。内部は pybind11 経由で C++ KoikoiEngine
を呼ぶ。`from koikoi_cpp import KoikoiEngine, Phase, ...` で `engine.py` の
代わりとして機能する。

Card オブジェクトのインターフェース (id / name / month / card_type /
tanzaku_type) は core.py のものをそのまま使う。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np

# C++ 拡張モジュールのパスを sys.path に追加
_NATIVE_DIR = Path(__file__).resolve().parent / "cpp_port" / "koikoi"
if str(_NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(_NATIVE_DIR))

import _koikoi_native as _native  # type: ignore

from core import (  # noqa: F401  re-export so callers can `from engine import Card`
    AKATAN,
    AOTAN,
    CARD_TYPE_RANK,
    HIKARI,
    KASU,
    TANE,
    TANZAKU,
    Card,
    check_yaku,
    make_deck,
    total_yaku_points,
)

# ============================================================
# 定数
# ============================================================

NUM_CARDS = _native.NUM_CARDS
ACTION_KOIKOI = _native.ACTION_KOIKOI
ACTION_SHOWDOWN = _native.ACTION_SHOWDOWN
NUM_ACTIONS = _native.NUM_ACTIONS
OBS_SIZE = _native.OBS_SIZE


class Phase:
    """engine.py::Phase 互換 (Enum 風だが C++ enum を再エクスポート)"""
    HAND_PLAY = _native.Phase.HAND_PLAY
    HAND_MATCH = _native.Phase.HAND_MATCH
    DRAW_MATCH = _native.Phase.DRAW_MATCH
    KOIKOI = _native.Phase.KOIKOI
    DONE = _native.Phase.DONE

    @classmethod
    def from_native(cls, p):
        return p  # 既に native 値そのもの

    # engine.py で `engine.phase.name` が使われる場合への保険
    # engine.py の Phase は Python enum で .name プロパティを持つ。
    # C++ 側の enum_ も .name を提供するので大丈夫。


DEFAULT_RULES = {
    "koikoi_double": True,
    "seven_plus_double": False,
    "hanami": True,
    "tsukimi": True,
    "multi_koikoi": "last_koikoi",
    "ryuukyoku": "no_change",
}


# ============================================================
# Card 取得 (engine.py::card_by_id 互換)
# ============================================================

_DECK = make_deck()


# ============================================================
# KoikoiEngine wrapper (engine.py 互換)
# ============================================================

class KoikoiEngine:
    """C++ 実装を呼び出すが、外側 API は engine.py::KoikoiEngine と同一。

    `players_hand` 等は **list[list[Card]]** として返す (engine.py と同じ)。
    内部的には毎回 C++ から id list を取得して Card に変換するので、
    属性アクセス毎にコピーが発生するが、Python 側で書き換えても C++ 内部
    状態には反映されないことに注意 (元の engine.py でも書き換えは想定外)。
    """

    def __init__(self, rules=None):
        merged = {**DEFAULT_RULES, **(rules or {})}
        self._impl = _native.KoikoiEngine(merged)
        self.rules = merged
        self._master_deck = _DECK

    # ------------------ engine.py の公開メソッド ------------------

    def card_by_id(self, card_id: int) -> Card:
        return _DECK[card_id]

    def reset(self, oya: int = 0, seed: Optional[int] = None) -> dict:
        return self._impl.reset(oya, seed)

    def get_legal_actions(self) -> list[int]:
        return self._impl.get_legal_actions()

    def step(self, action: int) -> dict:
        return self._impl.step(int(action))

    def get_observation(self, player_idx: int) -> np.ndarray:
        return self._impl.get_observation(player_idx)

    def get_action_mask(self) -> np.ndarray:
        return self._impl.get_action_mask()

    # ------------------ 属性 (engine.py の公開属性互換) ------------------
    # 各 property は C++ から fresh データを取得する。

    @property
    def phase(self):
        return self._impl.phase

    @property
    def current_player(self) -> int:
        return self._impl.current_player

    @property
    def oya_index(self) -> int:
        return self._impl.oya_index

    @property
    def done(self) -> bool:
        return self._impl.done

    @property
    def winner(self):
        return self._impl.winner

    @property
    def win_score(self) -> int:
        return self._impl.win_score

    @property
    def ryuukyoku(self) -> bool:
        return self._impl.ryuukyoku

    @property
    def ryuukyoku_oya_swap(self) -> bool:
        return self._impl.ryuukyoku_oya_swap

    @property
    def first_koikoi_player(self):
        return self._impl.first_koikoi_player

    @property
    def last_koikoi_player(self):
        return self._impl.last_koikoi_player

    @property
    def players_hand(self) -> list[list[Card]]:
        return [[_DECK[i] for i in self._impl.hand_ids(p)] for p in range(2)]

    @property
    def players_captured(self) -> list[list[Card]]:
        return [[_DECK[i] for i in self._impl.captured_ids(p)] for p in range(2)]

    @property
    def players_koikoi(self) -> list[bool]:
        return [self._impl.player_koikoi(0), self._impl.player_koikoi(1)]

    @property
    def players_prev_yaku(self) -> list[int]:
        return [self._impl.players_prev_yaku(0), self._impl.players_prev_yaku(1)]

    @property
    def field(self) -> list[Card]:
        return [_DECK[i] for i in self._impl.field_ids()]

    @property
    def deck(self) -> list[Card]:
        return [_DECK[i] for i in self._impl.deck_ids()]

    @property
    def _pending_played(self):
        pid = self._impl.pending_played_id()
        if pid is None:
            return None
        return _DECK[pid]

    @property
    def _pending_matches(self) -> list[Card]:
        return [_DECK[i] for i in self._impl.pending_match_ids()]


# ============================================================
# rule_based_policy (engine.py のものをそのまま流用)
# ============================================================

def rule_based_policy(engine: "KoikoiEngine", player_idx: int) -> int:
    """元のCPUと同等のルールベース方策 (engine.py からそのまま移植)"""
    phase = engine.phase

    if phase == Phase.HAND_PLAY:
        hand = engine.players_hand[player_idx]
        matchable: list[tuple[Card, int]] = []
        for c in hand:
            matches = [f for f in engine.field if f.month == c.month]
            if matches:
                best = max(matches, key=lambda m: CARD_TYPE_RANK.get(m.card_type, 0))
                score = CARD_TYPE_RANK.get(c.card_type, 0) + CARD_TYPE_RANK.get(best.card_type, 0)
                matchable.append((c, score))

        if matchable:
            matchable.sort(key=lambda x: x[1], reverse=True)
            return matchable[0][0].id
        worst = min(hand, key=lambda c: CARD_TYPE_RANK.get(c.card_type, 0))
        return worst.id

    if phase in (Phase.HAND_MATCH, Phase.DRAW_MATCH):
        matches = engine._pending_matches
        best = max(matches, key=lambda c: CARD_TYPE_RANK.get(c.card_type, 0))
        return best.id

    if phase == Phase.KOIKOI:
        pts = total_yaku_points(check_yaku(engine.players_captured[player_idx], engine.rules))
        return ACTION_SHOWDOWN if pts >= 7 else ACTION_KOIKOI

    return engine.get_legal_actions()[0]
