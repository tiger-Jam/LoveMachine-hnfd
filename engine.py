"""花札こいこい - 強化学習用ゲームエンジン

I/Oを一切含まない純粋なステップベースAPI。
各決定ポイント（手札選択・マッチ選択・こいこい判断）で一時停止し、
外部からアクションを受け取って状態遷移する。

使い方:
    engine = KoikoiEngine()
    engine.reset(oya=0, seed=42)

    while not engine.done:
        legal = engine.get_legal_actions()
        action = policy(engine.get_observation(engine.current_player), legal)
        engine.step(action)

    print(f"Winner: {engine.winner}, Score: {engine.win_score}")
"""

import random
from collections import Counter
from enum import Enum, auto
from typing import Optional

import numpy as np

from core import (
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

NUM_CARDS = 48
ACTION_KOIKOI = 48
ACTION_SHOWDOWN = 49
NUM_ACTIONS = 50

OBS_SIZE = 340


class Phase(Enum):
    HAND_PLAY = auto()
    HAND_MATCH = auto()
    DRAW_MATCH = auto()
    KOIKOI = auto()
    DONE = auto()


DEFAULT_RULES = {
    "koikoi_double": True,
    "seven_plus_double": False,
    "hanami": True,
    "tsukimi": True,
    # 手札切れ時、両方がこいこい宣言済のときのローカルルール:
    #   "oyaken"       : 親が 6 点で勝ち
    #   "last_koikoi"  : 最後にこいこいした人が素点で勝ち
    #   "first_koikoi" : 最初にこいこいした人が素点で勝ち
    "multi_koikoi": "last_koikoi",
    # 手札切れ時、誰もこいこいしていない (役未成立) ときのローカルルール:
    #   "oyaken"    : 親が 6 点で勝ち
    #   "no_change" : 勝者なし・0 点、次局も親そのまま
    #   "change"    : 勝者なし・0 点、次局は親を交代
    "ryuukyoku": "no_change",
}


class KoikoiEngine:
    def __init__(self, rules=None):
        self.rules = {**DEFAULT_RULES, **(rules or {})}
        self._master_deck: list[Card] = make_deck()
        self.players_hand: list[list[Card]] = [[], []]
        self.players_captured: list[list[Card]] = [[], []]
        self.players_koikoi: list[bool] = [False, False]
        self.players_prev_yaku: list[int] = [0, 0]
        # Order in which koikoi was declared this round (for the
        # multi-koikoi local rule at exhaust).
        self.first_koikoi_player: Optional[int] = None
        self.last_koikoi_player: Optional[int] = None
        self.field: list[Card] = []
        self.deck: list[Card] = []
        self.current_player: int = 0
        self.oya_index: int = 0
        self.phase: Phase = Phase.HAND_PLAY
        self.done: bool = False
        self.winner: Optional[int] = None
        self.win_score: int = 0
        # Set when _end_round_exhausted resolved as 流局 (no yaku) — the
        # session uses this (plus the "ryuukyoku" rule) to decide who the
        # next round's 親 should be.
        self.ryuukyoku: bool = False
        self.ryuukyoku_oya_swap: bool = False
        self._pending_played: Optional[Card] = None
        self._pending_matches: list[Card] = []
        self._rng = random.Random()

    def card_by_id(self, card_id: int) -> Card:
        return self._master_deck[card_id]

    # ------------------------------------------------------------------
    # リセット
    # ------------------------------------------------------------------

    def reset(self, oya: int = 0, seed: Optional[int] = None) -> dict:
        """新しいラウンドを開始する。特殊配りがあればinfoに含まれる。"""
        if seed is not None:
            self._rng = random.Random(seed)

        cards = list(self._master_deck)
        self._rng.shuffle(cards)

        self.players_hand = [cards[0:8], cards[8:16]]
        self.players_captured = [[], []]
        self.players_koikoi = [False, False]
        self.players_prev_yaku = [0, 0]
        self.first_koikoi_player = None
        self.last_koikoi_player = None
        self.field = cards[16:24]
        self.deck = cards[24:]
        self.current_player = oya
        self.oya_index = oya
        self.phase = Phase.HAND_PLAY
        self.done = False
        self.winner = None
        self.win_score = 0
        self.ryuukyoku = False
        self.ryuukyoku_oya_swap = False
        self._pending_played = None
        self._pending_matches = []

        special = self._check_special_deal()
        info: dict = {}
        if special:
            info["special"] = special
        return info

    def _check_special_deal(self) -> Optional[str]:
        field_months = Counter(c.month for c in self.field)
        if any(v == 4 for v in field_months.values()):
            return "redeal"

        for pi in range(2):
            hand_months = Counter(c.month for c in self.players_hand[pi])
            if any(v == 4 for v in hand_months.values()):
                self.done = True
                self.phase = Phase.DONE
                self.winner = pi
                self.win_score = 6
                return f"teshi:{pi}"
            if all(v == 2 for v in hand_months.values()) and len(hand_months) == 4:
                self.done = True
                self.phase = Phase.DONE
                self.winner = pi
                self.win_score = 6
                return f"kuttsuki:{pi}"

        return None

    # ------------------------------------------------------------------
    # アクション
    # ------------------------------------------------------------------

    def get_legal_actions(self) -> list[int]:
        if self.phase == Phase.HAND_PLAY:
            return [c.id for c in self.players_hand[self.current_player]]
        elif self.phase in (Phase.HAND_MATCH, Phase.DRAW_MATCH):
            return [c.id for c in self._pending_matches]
        elif self.phase == Phase.KOIKOI:
            return [ACTION_KOIKOI, ACTION_SHOWDOWN]
        return []

    def step(self, action: int) -> dict:
        """アクションを実行する。次の決定ポイントまで自動進行する。"""
        assert not self.done, "Round is already over"
        legal = self.get_legal_actions()
        assert action in legal, f"Illegal action {action}, legal: {legal}"

        info: dict = {"events": []}

        if self.phase == Phase.HAND_PLAY:
            self._step_hand_play(action, info)
        elif self.phase == Phase.HAND_MATCH:
            self._step_match(action, info, from_draw=False)
        elif self.phase == Phase.DRAW_MATCH:
            self._step_match(action, info, from_draw=True)
        elif self.phase == Phase.KOIKOI:
            self._step_koikoi(action, info)

        return info

    def _step_hand_play(self, card_id: int, info: dict):
        hand = self.players_hand[self.current_player]
        card = self.card_by_id(card_id)
        hand.remove(card)

        matches = [c for c in self.field if c.month == card.month]

        if len(matches) == 0:
            self.field.append(card)
            info["events"].append(("hand_no_match", card_id))
            self._proceed_to_draw(info)
        elif len(matches) == 1:
            self.field.remove(matches[0])
            self.players_captured[self.current_player].extend([card, matches[0]])
            info["events"].append(("hand_match", card_id, matches[0].id))
            self._proceed_to_draw(info)
        elif len(matches) == 3:
            for m in matches:
                self.field.remove(m)
            self.players_captured[self.current_player].append(card)
            self.players_captured[self.current_player].extend(matches)
            info["events"].append(("hand_match_all", card_id, [m.id for m in matches]))
            self._proceed_to_draw(info)
        else:
            self._pending_played = card
            self._pending_matches = matches
            self.phase = Phase.HAND_MATCH
            info["events"].append(("hand_choose", card_id, [m.id for m in matches]))

    def _step_match(self, card_id: int, info: dict, from_draw: bool):
        chosen = self.card_by_id(card_id)
        played = self._pending_played
        self.field.remove(chosen)
        self.players_captured[self.current_player].extend([played, chosen])
        self._pending_played = None
        self._pending_matches = []

        if from_draw:
            self._check_yaku_and_advance(info)
        else:
            self._proceed_to_draw(info)

    def _proceed_to_draw(self, info: dict):
        if not self.deck:
            self._check_yaku_and_advance(info)
            return

        drawn = self.deck.pop(0)
        info["events"].append(("draw", drawn.id))

        matches = [c for c in self.field if c.month == drawn.month]

        if len(matches) == 0:
            self.field.append(drawn)
            self._check_yaku_and_advance(info)
        elif len(matches) == 1:
            self.field.remove(matches[0])
            self.players_captured[self.current_player].extend([drawn, matches[0]])
            info["events"].append(("draw_match", drawn.id, matches[0].id))
            self._check_yaku_and_advance(info)
        elif len(matches) == 3:
            for m in matches:
                self.field.remove(m)
            self.players_captured[self.current_player].append(drawn)
            self.players_captured[self.current_player].extend(matches)
            info["events"].append(("draw_match_all", drawn.id, [m.id for m in matches]))
            self._check_yaku_and_advance(info)
        else:
            self._pending_played = drawn
            self._pending_matches = matches
            self.phase = Phase.DRAW_MATCH
            info["events"].append(("draw_choose", drawn.id, [m.id for m in matches]))

    def _check_yaku_and_advance(self, info: dict):
        cp = self.current_player
        yaku = check_yaku(self.players_captured[cp], self.rules)
        pts = total_yaku_points(yaku)

        if pts > self.players_prev_yaku[cp] and pts > 0:
            info["events"].append(("yaku_formed", cp, yaku, pts))
            self.phase = Phase.KOIKOI
        else:
            self._next_turn(info)

    def _step_koikoi(self, action: int, info: dict):
        cp = self.current_player
        yaku = check_yaku(self.players_captured[cp], self.rules)
        pts = total_yaku_points(yaku)

        if action == ACTION_SHOWDOWN:
            info["events"].append(("showdown", cp, pts))
            self._end_round(cp, pts, info)
        else:
            info["events"].append(("koikoi", cp))
            self.players_koikoi[cp] = True
            self.players_prev_yaku[cp] = pts
            if self.first_koikoi_player is None:
                self.first_koikoi_player = cp
            self.last_koikoi_player = cp
            self._next_turn(info)

    def _next_turn(self, info: dict):
        if not self.players_hand[0] and not self.players_hand[1]:
            self._end_round_exhausted(info)
            return

        self.current_player = 1 - self.current_player
        self.phase = Phase.HAND_PLAY

    def _end_round(self, winner: int, pts: int, info: dict):
        loser = 1 - winner
        if self.rules["seven_plus_double"] and pts >= 7:
            pts *= 2
            info["events"].append(("bonus_7plus",))
        if self.rules["koikoi_double"] and self.players_koikoi[loser]:
            pts *= 2
            info["events"].append(("bonus_opponent_koikoi",))

        self.done = True
        self.phase = Phase.DONE
        self.winner = winner
        self.win_score = pts
        info["events"].append(("round_end", winner, pts))

    def _end_round_exhausted(self, info: dict):
        info["events"].append(("exhausted",))
        self.done = True
        self.phase = Phase.DONE

        p0k = self.players_koikoi[0]
        p1k = self.players_koikoi[1]
        n_koikoi = int(p0k) + int(p1k)

        if n_koikoi == 0:
            # 誰もこいこいしていない = 役未成立 → 流局 (local rule)
            self.ryuukyoku = True
            rule = self.rules.get("ryuukyoku", "oyaken")
            if rule == "change":
                self.winner = None
                self.win_score = 0
                self.ryuukyoku_oya_swap = True
            elif rule == "no_change":
                self.winner = None
                self.win_score = 0
            else:  # "oyaken"
                self.winner = self.oya_index
                self.win_score = 6
        elif n_koikoi == 1:
            # 片方のみこいこい → そのプレイヤーが素点で勝ち (倍加なし)
            winner = 0 if p0k else 1
            self.winner = winner
            self.win_score = total_yaku_points(
                check_yaku(self.players_captured[winner], self.rules)
            )
        else:
            # 両方こいこい → 複数こいこいローカルルール
            rule = self.rules.get("multi_koikoi", "oyaken")
            if rule == "last_koikoi" and self.last_koikoi_player is not None:
                w = self.last_koikoi_player
                self.winner = w
                self.win_score = total_yaku_points(
                    check_yaku(self.players_captured[w], self.rules)
                )
            elif rule == "first_koikoi" and self.first_koikoi_player is not None:
                w = self.first_koikoi_player
                self.winner = w
                self.win_score = total_yaku_points(
                    check_yaku(self.players_captured[w], self.rules)
                )
            else:  # "oyaken"
                self.winner = self.oya_index
                self.win_score = 6

    # ------------------------------------------------------------------
    # 観測
    # ------------------------------------------------------------------

    def _compute_yaku_progress(self, captured: list[Card]) -> np.ndarray:
        """取り札から各役への進捗度を計算 (11次元, 0.0~1.0)"""
        progress = np.zeros(11, dtype=np.float32)
        hikari = [c for c in captured if c.card_type == HIKARI]
        tane = [c for c in captured if c.card_type == TANE]
        tanzaku = [c for c in captured if c.card_type == TANZAKU]
        kasu = [c for c in captured if c.card_type == KASU]
        non_rain = len([c for c in hikari if c.name != "柳に小野道風"])
        progress[0] = len(hikari) / 5.0                          # 五光
        progress[1] = non_rain / 4.0                              # 四光
        progress[2] = min(non_rain / 3.0, 1.0)                   # 三光
        akatan = len([c for c in tanzaku if c.tanzaku_type == AKATAN])
        aotan = len([c for c in tanzaku if c.tanzaku_type == AOTAN])
        progress[3] = akatan / 3.0                                # 赤短
        progress[4] = aotan / 3.0                                 # 青短
        progress[5] = min(len(tanzaku) / 5.0, 1.0)               # たん
        names = {c.name for c in captured}
        progress[6] = sum([
            "萩に猪" in names, "紅葉に鹿" in names, "牡丹に蝶" in names
        ]) / 3.0                                                  # 猪鹿蝶
        progress[7] = min(len(tane) / 5.0, 1.0)                  # たね
        progress[8] = min(len(kasu) / 10.0, 1.0)                 # カス
        has_maku = "桜に幕" in names
        has_tsuki = "芒に月" in names
        has_sakazuki = "菊に盃" in names
        progress[9] = (has_maku + has_sakazuki) / 2.0             # 花見で一杯
        progress[10] = (has_tsuki + has_sakazuki) / 2.0           # 月見で一杯
        return progress

    def get_observation(self, player_idx: int) -> np.ndarray:
        """指定プレイヤー視点の観測ベクトル (shape: (OBS_SIZE,))

        レイアウト (合計340次元):
          [  0: 48] 自分の手札 (binary)
          [ 48: 96] 場札 (binary)
          [ 96:144] 自分の取り札 (binary)
          [144:192] 相手の取り札 (binary)
          [192:240] 未確認カード: 相手手札+山札 (binary)
          [240:244] フェーズ one-hot
          [244]     自分が親か
          [245]     自分がこいこい宣言済
          [246]     相手がこいこい宣言済
          [247]     自分の現在役点 / 15
          [248]     相手の現在役点 / 15
          [249]     山札残り / 24
          [250:298] 場に出したカード (HAND_MATCH/DRAW_MATCH用, one-hot)
          [298:309] 自分の役進捗 (11次元)
          [309:320] 相手の役進捗 (11次元)
          [320:332] 月別の未確認カード割合 (12次元)
          [332:336] 自分の取り札種別数 (光/種/短冊/カス, 正規化)
          [336:340] 相手の取り札種別数 (同上)
        """
        obs = np.zeros(OBS_SIZE, dtype=np.float32)
        opp = 1 - player_idx

        for c in self.players_hand[player_idx]:
            obs[c.id] = 1.0
        for c in self.field:
            obs[48 + c.id] = 1.0
        for c in self.players_captured[player_idx]:
            obs[96 + c.id] = 1.0
        for c in self.players_captured[opp]:
            obs[144 + c.id] = 1.0

        visible: set[int] = set()
        for c in self.players_hand[player_idx]:
            visible.add(c.id)
        for c in self.field:
            visible.add(c.id)
        for c in self.players_captured[player_idx]:
            visible.add(c.id)
        for c in self.players_captured[opp]:
            visible.add(c.id)
        for i in range(NUM_CARDS):
            if i not in visible:
                obs[192 + i] = 1.0

        phase_idx = {
            Phase.HAND_PLAY: 0,
            Phase.HAND_MATCH: 1,
            Phase.DRAW_MATCH: 2,
            Phase.KOIKOI: 3,
        }
        if self.phase in phase_idx:
            obs[240 + phase_idx[self.phase]] = 1.0

        obs[244] = 1.0 if player_idx == self.oya_index else 0.0
        obs[245] = 1.0 if self.players_koikoi[player_idx] else 0.0
        obs[246] = 1.0 if self.players_koikoi[opp] else 0.0

        my_pts = total_yaku_points(check_yaku(self.players_captured[player_idx], self.rules))
        opp_pts = total_yaku_points(check_yaku(self.players_captured[opp], self.rules))
        obs[247] = min(my_pts / 15.0, 1.0)
        obs[248] = min(opp_pts / 15.0, 1.0)
        obs[249] = len(self.deck) / 24.0

        if self._pending_played is not None:
            obs[250 + self._pending_played.id] = 1.0

        obs[298:309] = self._compute_yaku_progress(self.players_captured[player_idx])
        obs[309:320] = self._compute_yaku_progress(self.players_captured[opp])

        for month in range(1, 13):
            unseen = sum(1 for c in self._master_deck
                         if c.month == month and c.id not in visible)
            obs[320 + month - 1] = unseen / 4.0

        type_norms = {HIKARI: 5.0, TANE: 9.0, TANZAKU: 10.0, KASU: 24.0}
        for i, ct in enumerate([HIKARI, TANE, TANZAKU, KASU]):
            obs[332 + i] = sum(
                1 for c in self.players_captured[player_idx] if c.card_type == ct
            ) / type_norms[ct]
            obs[336 + i] = sum(
                1 for c in self.players_captured[opp] if c.card_type == ct
            ) / type_norms[ct]

        return obs

    def get_action_mask(self) -> np.ndarray:
        """現在の合法手マスク (shape: (NUM_ACTIONS,), dtype=bool)"""
        mask = np.zeros(NUM_ACTIONS, dtype=bool)
        for a in self.get_legal_actions():
            mask[a] = True
        return mask


def rule_based_policy(engine: "KoikoiEngine", player_idx: int) -> int:
    """元のCPUと同等のルールベース方策"""
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
        else:
            worst = min(hand, key=lambda c: CARD_TYPE_RANK.get(c.card_type, 0))
            return worst.id

    elif phase in (Phase.HAND_MATCH, Phase.DRAW_MATCH):
        matches = engine._pending_matches
        best = max(matches, key=lambda c: CARD_TYPE_RANK.get(c.card_type, 0))
        return best.id

    elif phase == Phase.KOIKOI:
        pts = total_yaku_points(check_yaku(engine.players_captured[player_idx], engine.rules))
        return ACTION_SHOWDOWN if pts >= 7 else ACTION_KOIKOI

    return engine.get_legal_actions()[0]
