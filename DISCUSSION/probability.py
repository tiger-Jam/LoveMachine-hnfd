"""
確率計算エンジン

自分視点での役成立確率を計算する。
不明札 = 相手手札 + 山札 から「残り○ターンで必要札を引ける確率」を
超幾何分布ベースで算出する。
"""
from math import comb
from typing import Set, List, Dict, Tuple
from cards import (
    DECK, CARD_BY_ID, CardType,
    HIKARI_IDS, TANE_IDS, TANZAKU_IDS, KASU_IDS,
    AKA_TAN_IDS, AO_TAN_IDS, YANAGI_HIKARI_ID,
    INOSHIKACHO_IDS, HANAMI_IDS, TSUKIMI_IDS,
    score_yaku, YakuResult,
)
from dataclasses import dataclass, field


@dataclass
class GameState:
    """自分視点から見えるゲーム状態のスナップショット"""
    my_hand: Set[int] = field(default_factory=set)       # 自分の手札
    field_cards: Set[int] = field(default_factory=set)   # 場札
    my_captured: Set[int] = field(default_factory=set)   # 自分の取り札
    opp_captured: Set[int] = field(default_factory=set)  # 相手の取り札(見える)
    # 山札の残り枚数(中身は不明だが枚数はわかる)
    deck_size: int = 0
    # 相手の手札枚数(中身は不明)
    opp_hand_size: int = 0

    def unknown_cards(self) -> Set[int]:
        """自分から見て位置不明な札(相手手札 + 山札にある札)"""
        all_ids = set(range(48))
        known = self.my_hand | self.field_cards | self.my_captured | self.opp_captured
        return all_ids - known

    def validate(self) -> None:
        unknown = self.unknown_cards()
        expected_unknown = self.deck_size + self.opp_hand_size
        assert len(unknown) == expected_unknown, (
            f"未知札数の不整合: {len(unknown)} != {self.deck_size}+{self.opp_hand_size}"
        )


# ====== 役定義 (必要札集合) ======
# 自分の取り札に含まれていれば "取得済み" とカウントする必要札のセット

YAKU_DEFINITIONS: Dict[str, Dict] = {
    "五光":    {"required": HIKARI_IDS, "need_all": 5, "points": 15},
    "四光":    {"required": HIKARI_IDS - {YANAGI_HIKARI_ID}, "need_all": 4, "points": 10},
    "雨四光":  {"required": HIKARI_IDS, "need_all": 4, "points": 8, "must_include": {YANAGI_HIKARI_ID}},
    "三光":    {"required": HIKARI_IDS - {YANAGI_HIKARI_ID}, "need_all": 3, "points": 6},
    "猪鹿蝶":  {"required": INOSHIKACHO_IDS, "need_all": 3, "points": 5},
    "花見で一杯": {"required": HANAMI_IDS, "need_all": 2, "points": 5},
    "月見で一杯": {"required": TSUKIMI_IDS, "need_all": 2, "points": 5},
    "赤短":    {"required": AKA_TAN_IDS, "need_all": 3, "points": 6},
    "青短":    {"required": AO_TAN_IDS, "need_all": 3, "points": 6},
    "たね":    {"required": TANE_IDS, "need_all": 5, "points": 1, "variable": True},
    "たん":    {"required": TANZAKU_IDS, "need_all": 5, "points": 1, "variable": True},
    "カス":    {"required": KASU_IDS, "need_all": 10, "points": 1, "variable": True},
}


# ====== 取得可能性の評価 ======
# 「自分の取り札に入る」ためには以下のどれかが必要:
#   (a) その札が自分の手札にあり、場にマッチ(同月)がある / 場に出して回収
#   (b) その札が場にあり、自分の手札または山引きでマッチが来る
#   (c) その札が不明位置(相手手札 or 山札)にあり、自分が引く or 場に来て回収
#
# 厳密にやるには相手の妨害も考える必要があるが、まずは
# 「その札が自分の取り札に入る確率」を近似評価する。


def prob_capture_card(state: GameState, target_id: int, my_remaining_turns: int) -> float:
    """
    特定の札1枚が、最終的に自分の取り札に入る確率(近似)。

    簡略化:
    - 自分の手札にある札 → マッチする札(同月)があるか不明札中のどこかにあれば取れる
    - 場札にある札 → 同月札を自分の手札か引きで得られれば取れる
    - 不明札にある札 → 自分が引く or 場に来たとき自分が回収
    - 相手の取り札に既にあるなら取得不能(確率0)

    my_remaining_turns: 自分があと何ターン回るか(通常 len(my_hand))
    """
    if target_id in state.opp_captured:
        return 0.0
    if target_id in state.my_captured:
        return 1.0

    target = CARD_BY_ID[target_id]
    month = target.month

    # --- ケースA: 対象札が自分の手札にある ---
    if target_id in state.my_hand:
        return _prob_capture_from_own_hand(state, target_id, my_remaining_turns)

    # --- ケースB: 対象札が場にある ---
    if target_id in state.field_cards:
        return _prob_capture_from_field(state, target_id, my_remaining_turns)

    # --- ケースC: 対象札が不明 ---
    return _prob_capture_from_unknown(state, target_id, my_remaining_turns)


def _prob_capture_from_own_hand(state: GameState, target_id: int, turns: int) -> float:
    """自分手札の札を取れる確率 = 同月マッチが場にある or 山で来る"""
    target = CARD_BY_ID[target_id]
    # 同月で自分の手札以外の札
    same_month_ids = [c.id for c in DECK if c.month == target.month and c.id != target_id]
    # 既に場にマッチがあれば、このターン確実に取れる
    field_match = [cid for cid in same_month_ids if cid in state.field_cards]
    if field_match:
        return 1.0
    # マッチが相手取り札にある枚数
    opp_cap_match = sum(1 for cid in same_month_ids if cid in state.opp_captured)
    # マッチが自分の取り札にある枚数 (使用不可)
    my_cap_match = sum(1 for cid in same_month_ids if cid in state.my_captured)
    # マッチがunknown(相手手札 or 山)にある枚数
    unknown = state.unknown_cards()
    unknown_match = sum(1 for cid in same_month_ids if cid in unknown)

    if unknown_match == 0:
        # 全部使用済みの場合: 同月札が3枚とも既知で取れない場所にある → 場に出して流れるまで
        # 「月末処理」(取れなかった札は捨てられる)は設計に依存。ここでは0として近似
        return 0.0

    # 山札からのドローで引く確率を近似
    # 自分があとturns回山をめくる → マッチが山にある確率 × めくれる確率
    unknown_total = len(unknown)
    # 山に含まれている確率 = deck_size / unknown_total (各札が独立で近似)
    p_match_in_deck = state.deck_size / unknown_total if unknown_total else 0

    # 自分がめくるのはturns回、相手はturns-1 or turns回
    # 簡略化: 山の上から 2*turns (自分のめくり + 相手のめくり) 枚が見える
    # そのうち自分が引くのはturns枚。マッチがそこに入る確率を超幾何で近似。
    n_picks_self = turns
    total_draws = 2 * turns  # 両者の山めくり合計

    # 超幾何: 山deck_size枚からtotal_draws枚引いたとき、
    # 「マッチ札unknown_match枚のうち、1枚以上が自分のturns回の引きに含まれる」確率
    # → 複雑なので、もっと単純に: 各マッチ札が自分のめくりに当たる確率 × 枚数
    # 1枚のマッチ札が山にあり、自分がそれをめくる確率 ≈ (deck_size内にある) × (turns/deck_size)
    # = p_match_in_deck * (turns/deck_size) * deck_size = unknown_match/unknown_total * turns

    # より正確には「マッチのどれか1枚でも自分が回収できる」確率を超幾何で:
    # 山内マッチ数 k を知らないので、unknown全体からdeck_sizeを山と考える
    # 自分が引くturns枚の中にマッチが入る確率を近似: 1 - C(unknown-unknown_match, turns) / C(unknown, turns)
    if unknown_total < turns:
        p_self_draws_match = 0.0
    else:
        try:
            p_self_draws_match = 1.0 - comb(unknown_total - unknown_match, turns) / comb(unknown_total, turns)
        except ValueError:
            p_self_draws_match = 0.0

    # 追加: マッチ札が山にある状態で場に出ている間に、自分の手札で取ることも考えられるが
    # 近似として上記のみ考慮

    return p_self_draws_match


def _prob_capture_from_field(state: GameState, target_id: int, turns: int) -> float:
    """場札の取り札化確率 = 同月マッチが自分の手札にある or 山で自分が引く"""
    target = CARD_BY_ID[target_id]
    same_month_ids = [c.id for c in DECK if c.month == target.month and c.id != target_id]

    # 自分の手札にマッチがあれば、次の自分のターンで取れる → ほぼ1.0
    # ただし相手が先にマッチを場に出して取るケースもある(同月3枚揃い4枚獲得は有利側)
    my_hand_match = any(cid in state.my_hand for cid in same_month_ids)
    if my_hand_match:
        return 1.0  # 簡略化: ほぼ確実

    # マッチが不明位置にある枚数
    unknown = state.unknown_cards()
    unknown_match_ids = [cid for cid in same_month_ids if cid in unknown]
    n_match = len(unknown_match_ids)
    if n_match == 0:
        return 0.0

    unknown_total = len(unknown)
    # マッチ札が山にあり、自分がそれをめくる確率
    # + マッチ札が相手手札にあり相手が場に出して、自分の手札/引きでは取れない(この場合0)
    # → 簡略化: 自分がマッチをドローで得る確率のみ
    if unknown_total < turns or turns == 0:
        return 0.0
    try:
        p_self = 1.0 - comb(unknown_total - n_match, turns) / comb(unknown_total, turns)
    except ValueError:
        p_self = 0.0
    # さらに「マッチが相手手札にあり相手が使った場合」も場札は残るので、
    # 自分が後でマッチを引くチャンスもある。上記で既に近似済みとする。
    return p_self


def _prob_capture_from_unknown(state: GameState, target_id: int, turns: int) -> float:
    """不明位置にある札を自分の取り札にする確率。
    (a) 自分が山でめくる + 場にマッチがある or 手札にマッチがある or 次に来る山札マッチ
    (b) 相手が山でめくって場に置かれ、その後自分の手札/引きマッチで回収
    近似: "自分があと2*turns枚の山のうちturns枚を引く" 仮定下で、対象札が自分の取り札に入る期待値
    """
    target = CARD_BY_ID[target_id]
    same_month_ids = [c.id for c in DECK if c.month == target.month and c.id != target_id]
    # 自分の手札/場にマッチがあれば、対象札を自分がめくった時に取れる
    match_in_my_hand = any(cid in state.my_hand for cid in same_month_ids)
    match_on_field = any(cid in state.field_cards for cid in same_month_ids)
    can_capture_on_draw = match_in_my_hand or match_on_field

    unknown = state.unknown_cards()
    unknown_total = len(unknown)
    if unknown_total == 0 or turns == 0:
        return 0.0

    # 対象札が山にある確率
    p_in_deck = state.deck_size / unknown_total
    # 対象札が山にあり、かつ自分がそれを引く確率
    # 自分の引きtotal回 (turns) のうち1つに当たる確率 ≈ turns/unknown_total
    # → 対象札が自分の引きに来る確率: turns/unknown_total
    p_self_draw_target = turns / unknown_total

    p = 0.0
    if can_capture_on_draw:
        # 自分が引く時に取れる(手札マッチまたは場マッチ経由)
        # ただし「場マッチ」は相手も狙ってる可能性があるので、厳密には減衰すべき。ここでは近似。
        p += p_self_draw_target
    else:
        # 手札/場にマッチがない場合、対象札を引いても場に出すだけ
        # → 自分が後でマッチを引けば回収可能。確率はさらに低い(二段階)
        # 簡略化: (対象札を自分が引く) × (その後マッチを引く) は無視できる小ささとしない
        # マッチは同月3枚のうち不明位置にあるもの
        unknown_match_count = sum(1 for cid in same_month_ids if cid in unknown)
        if unknown_match_count > 0:
            p_match = turns / unknown_total  # 同様近似
            p += p_self_draw_target * p_match * 0.5  # 二段階係数で下げる
        # else: マッチ枯渇 → 0

    # 相手が対象札をめくり場に置き、自分が後で回収するケース
    p_opp_draw_target = turns / unknown_total  # 近似: 相手もturns回引く
    if can_capture_on_draw:
        p += p_opp_draw_target * 0.7  # 近似: 相手が先に流す場合もあるので減衰
    # それ以外は追加貢献小さいとして無視

    return min(p, 1.0)


# ====== 役成立確率 ======

def prob_yaku_complete(state: GameState, yaku_name: str,
                       my_remaining_turns: int = None) -> float:
    """指定の役が、現状から最終的に成立する確率(近似)"""
    if my_remaining_turns is None:
        my_remaining_turns = len(state.my_hand)

    yaku = YAKU_DEFINITIONS[yaku_name]
    required: Set[int] = yaku["required"]
    need_all: int = yaku["need_all"]

    # 必須札(雨四光の"must_include")
    must_include: Set[int] = yaku.get("must_include", set())

    # 既に取得済みの必要札
    already = state.my_captured & required
    # 既に相手取り札にある → 取得不能
    lost = state.opp_captured & required

    # 残り必要枚数
    remaining_needed = need_all - len(already)
    if remaining_needed <= 0:
        # 既に成立
        if must_include and not (must_include & state.my_captured):
            # 必須札未取得
            pass
        else:
            return 1.0

    # 取りに行ける札 = required - already - lost
    candidates = required - already - lost
    if len(candidates) < remaining_needed:
        return 0.0  # 物理的に不可能

    # 各候補札の獲得確率を計算
    probs: Dict[int, float] = {
        cid: prob_capture_card(state, cid, my_remaining_turns)
        for cid in candidates
    }

    # must_include を考慮
    if must_include:
        # must_include の札のうち取得可能なもの
        must_candidates = must_include & candidates
        if not must_candidates:
            # 既に取得済みか?
            if not (must_include & state.my_captured):
                return 0.0

    # 「remaining_needed 枚以上 成立する」確率
    # 各独立事象として近似し、包含排他で計算するのが理想だが、
    # ここでは ポアソン二項の近似または動的計画法で算出
    return _prob_at_least_k(list(probs.values()), remaining_needed,
                            must_include_probs=[probs[c] for c in (must_include & candidates)]
                            if must_include else None)


def _prob_at_least_k(probs: List[float], k: int,
                     must_include_probs: List[float] = None) -> float:
    """独立な成功確率 p_i の試行から、少なくとも k 個成功する確率。
    DPで厳密計算。

    must_include_probs が指定されている場合、それらの確率(のうち少なくとも1つ)
    は必ず成功しなければならない。
    """
    if k <= 0:
        return 1.0
    if len(probs) < k:
        return 0.0

    # DP: dp[j] = ちょうど j 個成功する確率
    # しかしmust_includeがあると条件付き確率が必要
    if must_include_probs:
        # 「must_include のどれか1つが成功 AND 全体でk個以上成功」
        # P(A ∩ B) = P(B) - P(B ∩ ¬A)
        # ¬A = must_include の全てが失敗
        p_all_must_fail = 1.0
        for pm in must_include_probs:
            p_all_must_fail *= (1 - pm)
        p_at_least_k = _prob_at_least_k_dp(probs, k)
        # 「must全部失敗」の条件下でk個成功する確率を近似計算
        # 簡略化: must以外の確率でk個必要(厳密ではないが近似)
        non_must_probs = [p for p in probs if not _in_list(p, must_include_probs)]
        p_k_without_must = _prob_at_least_k_dp(non_must_probs, k)
        return max(0.0, p_at_least_k - p_all_must_fail * p_k_without_must)

    return _prob_at_least_k_dp(probs, k)


def _in_list(x, lst, eps=1e-9):
    return any(abs(x - y) < eps for y in lst)


def _prob_at_least_k_dp(probs: List[float], k: int) -> float:
    """独立試行 n 回のうち少なくとも k 回成功する確率(ポアソン二項)"""
    n = len(probs)
    if k > n:
        return 0.0
    if k <= 0:
        return 1.0
    # dp[j] = j回成功する確率
    dp = [0.0] * (n + 1)
    dp[0] = 1.0
    for i, p in enumerate(probs):
        new_dp = [0.0] * (n + 1)
        for j in range(i + 2):
            new_dp[j] = dp[j] * (1 - p)
            if j > 0:
                new_dp[j] += dp[j - 1] * p
        dp = new_dp
    return sum(dp[k:])


# ====== すべての役の確率を一覧化 ======

def all_yaku_probabilities(state: GameState, my_remaining_turns: int = None) -> Dict[str, float]:
    """現状からの、全役の最終成立確率"""
    if my_remaining_turns is None:
        my_remaining_turns = len(state.my_hand)
    result = {}
    for yaku_name in YAKU_DEFINITIONS:
        result[yaku_name] = prob_yaku_complete(state, yaku_name, my_remaining_turns)
    return result


if __name__ == "__main__":
    # テスト: 初期状態(手札8, 場8, 山24, 相手手札8)で全役確率
    import random
    random.seed(42)
    all_ids = list(range(48))
    random.shuffle(all_ids)
    my_hand = set(all_ids[:8])
    field = set(all_ids[8:16])
    opp_hand = set(all_ids[16:24])  # 相手手札(テスト用、実際は不明)
    # 山は残り

    state = GameState(
        my_hand=my_hand,
        field_cards=field,
        my_captured=set(),
        opp_captured=set(),
        deck_size=24,
        opp_hand_size=8,
    )
    state.validate()

    print("=== 初期状態 ===")
    print(f"自分の手札: {[CARD_BY_ID[i].name for i in sorted(my_hand)]}")
    print(f"場札:       {[CARD_BY_ID[i].name for i in sorted(field)]}")
    print()
    print("=== 各役の成立確率 ===")
    probs = all_yaku_probabilities(state)
    for name, p in sorted(probs.items(), key=lambda x: -x[1]):
        bar = "█" * int(p * 40)
        print(f"{name:10s} {p*100:5.2f}% {bar}")
