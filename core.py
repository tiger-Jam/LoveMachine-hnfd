"""花札こいこい - カード定義・役判定（共通モジュール）"""

from dataclasses import dataclass
from typing import Optional


# カード種別
HIKARI = "光"
TANE = "種"
TANZAKU = "短冊"
KASU = "カス"

# 短冊サブタイプ
AKATAN = "赤短"
AOTAN = "青短"
MUJI = "無地"

MONTHS = {
    1: "松", 2: "梅", 3: "桜", 4: "藤", 5: "菖蒲", 6: "牡丹",
    7: "萩", 8: "芒", 9: "菊", 10: "紅葉", 11: "柳", 12: "桐",
}

CARD_TYPE_RANK = {HIKARI: 4, TANE: 3, TANZAKU: 2, KASU: 1}


@dataclass
class Card:
    id: int
    month: int
    name: str
    card_type: str
    tanzaku_type: Optional[str] = None

    def __eq__(self, other):
        return isinstance(other, Card) and self.id == other.id

    def __hash__(self):
        return self.id

    def __str__(self):
        mark = ""
        if self.card_type == HIKARI:
            mark = "☆"
        elif self.card_type == TANE:
            mark = "◎"
        elif self.card_type == TANZAKU:
            mark = "＃"
        return f"{self.name}{mark}"

    def short(self):
        return str(self)


def make_deck() -> list[Card]:
    """48枚のデッキを生成"""
    cards: list[Card] = []
    cid = 0

    def add(month, name, ctype, tanzaku=None):
        nonlocal cid
        cards.append(Card(cid, month, name, ctype, tanzaku))
        cid += 1

    add(1, "松に鶴", HIKARI)
    add(1, "松に赤短", TANZAKU, AKATAN)
    add(1, "松のカス①", KASU)
    add(1, "松のカス②", KASU)
    add(2, "梅に鶯", TANE)
    add(2, "梅に赤短", TANZAKU, AKATAN)
    add(2, "梅のカス①", KASU)
    add(2, "梅のカス②", KASU)
    add(3, "桜に幕", HIKARI)
    add(3, "桜に赤短", TANZAKU, AKATAN)
    add(3, "桜のカス①", KASU)
    add(3, "桜のカス②", KASU)
    add(4, "藤に不如帰", TANE)
    add(4, "藤に短冊", TANZAKU, MUJI)
    add(4, "藤のカス①", KASU)
    add(4, "藤のカス②", KASU)
    add(5, "菖蒲に八橋", TANE)
    add(5, "菖蒲に短冊", TANZAKU, MUJI)
    add(5, "菖蒲のカス①", KASU)
    add(5, "菖蒲のカス②", KASU)
    add(6, "牡丹に蝶", TANE)
    add(6, "牡丹に青短", TANZAKU, AOTAN)
    add(6, "牡丹のカス①", KASU)
    add(6, "牡丹のカス②", KASU)
    add(7, "萩に猪", TANE)
    add(7, "萩に短冊", TANZAKU, MUJI)
    add(7, "萩のカス①", KASU)
    add(7, "萩のカス②", KASU)
    add(8, "芒に月", HIKARI)
    add(8, "芒に雁", TANE)
    add(8, "芒のカス①", KASU)
    add(8, "芒のカス②", KASU)
    add(9, "菊に盃", TANE)
    add(9, "菊に青短", TANZAKU, AOTAN)
    add(9, "菊のカス①", KASU)
    add(9, "菊のカス②", KASU)
    add(10, "紅葉に鹿", TANE)
    add(10, "紅葉に青短", TANZAKU, AOTAN)
    add(10, "紅葉のカス①", KASU)
    add(10, "紅葉のカス②", KASU)
    add(11, "柳に小野道風", HIKARI)
    add(11, "柳に燕", TANE)
    add(11, "柳に短冊", TANZAKU, MUJI)
    add(11, "柳のカス", KASU)
    add(12, "桐に鳳凰", HIKARI)
    add(12, "桐のカス①", KASU)
    add(12, "桐のカス②", KASU)
    add(12, "桐のカス③", KASU)

    return cards


def check_yaku(captured: list[Card], rules=None) -> list[tuple[str, int]]:
    """取り札から成立している役をすべて返す [(役名, 点数), ...]"""
    yaku: list[tuple[str, int]] = []
    if rules is None:
        rules = {}

    hikari = [c for c in captured if c.card_type == HIKARI]
    tane = [c for c in captured if c.card_type == TANE]
    tanzaku = [c for c in captured if c.card_type == TANZAKU]
    kasu = [c for c in captured if c.card_type == KASU]

    hikari_names = {c.name for c in hikari}
    has_ono = "柳に小野道風" in hikari_names

    if len(hikari) == 5:
        yaku.append(("五光", 15))
    elif len(hikari) == 4:
        if has_ono:
            yaku.append(("雨四光", 8))
        else:
            yaku.append(("四光", 10))
    elif len(hikari) >= 3 and not has_ono:
        yaku.append(("三光", 6))
    elif len(hikari) >= 3 and has_ono:
        non_ono = len(hikari) - 1
        if non_ono >= 3:
            yaku.append(("三光", 6))

    akatan_cards = [c for c in tanzaku if c.tanzaku_type == AKATAN]
    aotan_cards = [c for c in tanzaku if c.tanzaku_type == AOTAN]

    if len(akatan_cards) >= 3:
        yaku.append(("赤短", 6))
    if len(aotan_cards) >= 3:
        yaku.append(("青短", 6))
    if len(tanzaku) >= 5:
        yaku.append(("たん", 1 + (len(tanzaku) - 5)))

    has_ino = any(c.name == "萩に猪" for c in captured)
    has_shika = any(c.name == "紅葉に鹿" for c in captured)
    has_cho = any(c.name == "牡丹に蝶" for c in captured)
    if has_ino and has_shika and has_cho:
        yaku.append(("猪鹿蝶", 5))

    if len(tane) >= 5:
        yaku.append(("たね", 1 + (len(tane) - 5)))

    if len(kasu) >= 10:
        yaku.append(("カス", 1 + (len(kasu) - 10)))

    has_maku = any(c.name == "桜に幕" for c in captured)
    has_tsuki = any(c.name == "芒に月" for c in captured)
    has_sakazuki = any(c.name == "菊に盃" for c in captured)

    if has_maku and has_sakazuki and rules.get("hanami", True):
        yaku.append(("花見で一杯", 5))
    if has_tsuki and has_sakazuki and rules.get("tsukimi", True):
        yaku.append(("月見で一杯", 5))

    return yaku


def total_yaku_points(yaku_list: list[tuple[str, int]]) -> int:
    return sum(pts for _, pts in yaku_list)
