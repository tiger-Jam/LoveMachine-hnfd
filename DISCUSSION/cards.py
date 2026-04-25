"""
花札こいこい - 札データと役判定
ルール: ユーザー指定のルール文書に準拠
"""
from enum import Enum
from dataclasses import dataclass
from typing import List, Set, Tuple, Dict, Optional


class CardType(Enum):
    """札の種類"""
    HIKARI = "光"       # 光札 20点相当
    TANE = "種"         # 種札 10点相当
    TANZAKU = "短冊"    # 短冊札 5点相当
    KASU = "カス"       # カス札 1点相当


class TanzakuColor(Enum):
    """短冊の色分類"""
    AKA = "赤短"     # あかよろし (1月,2月,3月)
    AO = "青短"      # 青短 (6月,9月,10月)
    PLAIN = "無地"   # 藤,菖蒲,萩,柳


@dataclass(frozen=True)
class Card:
    """花札1枚を表す。idで一意識別。"""
    id: int                  # 0-47の通し番号
    month: int               # 1-12
    card_type: CardType
    name: str                # 名称 (例: "松に鶴")
    tanzaku_color: Optional[TanzakuColor] = None  # 短冊の場合のみ

    def __repr__(self):
        return f"{self.month}月/{self.name}"


def _build_deck() -> List[Card]:
    """ルール文書の月別一覧を元に48枚を構築"""
    cards = []
    cid = 0

    def add(month, name, ct, tc=None):
        nonlocal cid
        cards.append(Card(id=cid, month=month, card_type=ct, name=name, tanzaku_color=tc))
        cid += 1

    # 1月 松
    add(1, "松に鶴", CardType.HIKARI)
    add(1, "松に赤短", CardType.TANZAKU, TanzakuColor.AKA)
    add(1, "松のカス", CardType.KASU)
    add(1, "松のカス", CardType.KASU)
    # 2月 梅
    add(2, "梅に鶯", CardType.TANE)
    add(2, "梅に赤短", CardType.TANZAKU, TanzakuColor.AKA)
    add(2, "梅のカス", CardType.KASU)
    add(2, "梅のカス", CardType.KASU)
    # 3月 桜
    add(3, "桜に幕", CardType.HIKARI)
    add(3, "桜に赤短", CardType.TANZAKU, TanzakuColor.AKA)
    add(3, "桜のカス", CardType.KASU)
    add(3, "桜のカス", CardType.KASU)
    # 4月 藤
    add(4, "藤に不如帰", CardType.TANE)
    add(4, "藤に短冊", CardType.TANZAKU, TanzakuColor.PLAIN)
    add(4, "藤のカス", CardType.KASU)
    add(4, "藤のカス", CardType.KASU)
    # 5月 菖蒲
    add(5, "菖蒲に八橋", CardType.TANE)
    add(5, "菖蒲に短冊", CardType.TANZAKU, TanzakuColor.PLAIN)
    add(5, "菖蒲のカス", CardType.KASU)
    add(5, "菖蒲のカス", CardType.KASU)
    # 6月 牡丹
    add(6, "牡丹に蝶", CardType.TANE)
    add(6, "牡丹に青短", CardType.TANZAKU, TanzakuColor.AO)
    add(6, "牡丹のカス", CardType.KASU)
    add(6, "牡丹のカス", CardType.KASU)
    # 7月 萩
    add(7, "萩に猪", CardType.TANE)
    add(7, "萩に短冊", CardType.TANZAKU, TanzakuColor.PLAIN)
    add(7, "萩のカス", CardType.KASU)
    add(7, "萩のカス", CardType.KASU)
    # 8月 芒
    add(8, "芒に月", CardType.HIKARI)
    add(8, "芒に雁", CardType.TANE)
    add(8, "芒のカス", CardType.KASU)
    add(8, "芒のカス", CardType.KASU)
    # 9月 菊
    add(9, "菊に盃", CardType.TANE)   # デフォで菊盃=タネのみ扱い
    add(9, "菊に青短", CardType.TANZAKU, TanzakuColor.AO)
    add(9, "菊のカス", CardType.KASU)
    add(9, "菊のカス", CardType.KASU)
    # 10月 紅葉
    add(10, "紅葉に鹿", CardType.TANE)
    add(10, "紅葉に青短", CardType.TANZAKU, TanzakuColor.AO)
    add(10, "紅葉のカス", CardType.KASU)
    add(10, "紅葉のカス", CardType.KASU)
    # 11月 柳
    add(11, "柳に小野道風", CardType.HIKARI)
    add(11, "柳に燕", CardType.TANE)
    add(11, "柳に短冊", CardType.TANZAKU, TanzakuColor.PLAIN)
    add(11, "柳のカス", CardType.KASU)
    # 12月 桐
    add(12, "桐に鳳凰", CardType.HIKARI)
    add(12, "桐のカス", CardType.KASU)
    add(12, "桐のカス", CardType.KASU)
    add(12, "桐のカス", CardType.KASU)

    assert len(cards) == 48, f"札数がおかしい: {len(cards)}"
    return cards


DECK: List[Card] = _build_deck()
CARD_BY_ID: Dict[int, Card] = {c.id: c for c in DECK}

# よく使う特定札の参照
def _find(name: str) -> Card:
    for c in DECK:
        if c.name == name:
            return c
    raise ValueError(name)

CARD_MATSU_TSURU = _find("松に鶴")          # 1月光
CARD_SAKURA_MAKU = _find("桜に幕")          # 3月光
CARD_SUSUKI_TSUKI = _find("芒に月")         # 8月光
CARD_YANAGI_MICHIKAZE = _find("柳に小野道風")  # 11月光 (雨)
CARD_KIRI_HOOU = _find("桐に鳳凰")          # 12月光
CARD_HAGI_INO = _find("萩に猪")             # 7月猪
CARD_MOMIJI_SHIKA = _find("紅葉に鹿")       # 10月鹿
CARD_BOTAN_CHOU = _find("牡丹に蝶")         # 6月蝶
CARD_KIKU_SAKAZUKI = _find("菊に盃")        # 9月盃

HIKARI_IDS: Set[int] = {c.id for c in DECK if c.card_type == CardType.HIKARI}
TANE_IDS:   Set[int] = {c.id for c in DECK if c.card_type == CardType.TANE}
TANZAKU_IDS: Set[int] = {c.id for c in DECK if c.card_type == CardType.TANZAKU}
KASU_IDS:   Set[int] = {c.id for c in DECK if c.card_type == CardType.KASU}
AKA_TAN_IDS: Set[int] = {c.id for c in DECK if c.tanzaku_color == TanzakuColor.AKA}
AO_TAN_IDS:  Set[int] = {c.id for c in DECK if c.tanzaku_color == TanzakuColor.AO}

YANAGI_HIKARI_ID = CARD_YANAGI_MICHIKAZE.id
INOSHIKACHO_IDS = {CARD_HAGI_INO.id, CARD_MOMIJI_SHIKA.id, CARD_BOTAN_CHOU.id}
HANAMI_IDS = {CARD_SAKURA_MAKU.id, CARD_KIKU_SAKAZUKI.id}
TSUKIMI_IDS = {CARD_SUSUKI_TSUKI.id, CARD_KIKU_SAKAZUKI.id}


# ====== 役判定 ======

@dataclass
class YakuResult:
    """成立した役とその得点"""
    name: str
    points: int


def score_yaku(captured: Set[int]) -> List[YakuResult]:
    """取り札の集合から、成立している出来役と合計点を列挙。
    光系の役は排他的に最上位のみカウント。"""
    results: List[YakuResult] = []

    # --- 光系(排他) ---
    hikari_held = captured & HIKARI_IDS
    n_hikari = len(hikari_held)
    has_rain = YANAGI_HIKARI_ID in hikari_held
    if n_hikari == 5:
        results.append(YakuResult("五光", 15))
    elif n_hikari == 4 and not has_rain:
        results.append(YakuResult("四光", 10))
    elif n_hikari == 4 and has_rain:
        results.append(YakuResult("雨四光", 8))
    elif n_hikari == 3 and not has_rain:
        results.append(YakuResult("三光", 6))
    # 三光は雨を含まないので柳なし3枚のみ

    # --- 種系 ---
    if INOSHIKACHO_IDS.issubset(captured):
        results.append(YakuResult("猪鹿蝶", 5))
    if HANAMI_IDS.issubset(captured):
        results.append(YakuResult("花見で一杯", 5))
    if TSUKIMI_IDS.issubset(captured):
        results.append(YakuResult("月見で一杯", 5))
    n_tane = len(captured & TANE_IDS)
    if n_tane >= 5:
        results.append(YakuResult("たね", 1 + (n_tane - 5)))

    # --- 短冊系 ---
    if AKA_TAN_IDS.issubset(captured):
        results.append(YakuResult("赤短", 6))
    if AO_TAN_IDS.issubset(captured):
        results.append(YakuResult("青短", 6))
    n_tanzaku = len(captured & TANZAKU_IDS)
    if n_tanzaku >= 5:
        results.append(YakuResult("たん", 1 + (n_tanzaku - 5)))

    # --- カス ---
    n_kasu = len(captured & KASU_IDS)
    if n_kasu >= 10:
        results.append(YakuResult("カス", 1 + (n_kasu - 10)))

    return results


def total_points(captured: Set[int]) -> int:
    return sum(y.points for y in score_yaku(captured))


# ====== 手役(配り直し)判定 ======

def check_hand_yaku(hand: List[Card]) -> Optional[str]:
    """手札8枚について手四・くっつきを判定。配り直し役が成立した場合は役名を返す。"""
    if len(hand) != 8:
        return None
    by_month: Dict[int, int] = {}
    for c in hand:
        by_month[c.month] = by_month.get(c.month, 0) + 1
    # 手四: いずれかの月が4枚
    if any(v == 4 for v in by_month.values()):
        return "手四"
    # くっつき: 全ての月が2枚ずつ、かつ月数4
    if len(by_month) == 4 and all(v == 2 for v in by_month.values()):
        return "くっつき"
    return None


if __name__ == "__main__":
    print(f"デッキサイズ: {len(DECK)}")
    print(f"光: {len(HIKARI_IDS)}, 種: {len(TANE_IDS)}, 短冊: {len(TANZAKU_IDS)}, カス: {len(KASU_IDS)}")
    print(f"赤短: {len(AKA_TAN_IDS)}, 青短: {len(AO_TAN_IDS)}")
    # 五光テスト
    test = HIKARI_IDS
    print(f"光5枚の役: {score_yaku(test)}")
    # 猪鹿蝶+青短テスト
    test2 = INOSHIKACHO_IDS | AO_TAN_IDS
    print(f"猪鹿蝶+青短: {score_yaku(test2)}")
