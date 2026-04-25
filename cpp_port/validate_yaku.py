#!/usr/bin/env python3
"""Python (core.py) vs C++ (koikoi_yaku.cc) の役判定クロス検証。

使い方:
    cd <repo>
    python cpp_port/validate_yaku.py

戦略:
  - 10000 個のランダム captured 集合 + ランダムルールを生成
  - Python 側で check_yaku を実行 → (total, sorted list) に canonical 化
  - 同じ入力を yaku_dump バイナリに投げて結果を読み、同じ canonical 形式に
  - 完全一致を assert

エッジケースも別に 20 個ほど手書きで入れる。
"""
import random
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core import make_deck, check_yaku, total_yaku_points

DECK = make_deck()
NUM_CARDS = 48

CPP_BIN = REPO / "cpp_port" / "koikoi" / "yaku_dump"


def mask_from_ids(ids):
    m = 0
    for i in ids:
        m |= 1 << i
    return m


def ids_from_mask(m):
    ids = []
    for i in range(NUM_CARDS):
        if m & (1 << i):
            ids.append(i)
    return ids


def canonical(total, yaku_list):
    # Python 側は (name, points) のリスト。順序は check_yaku の内部で固定
    # だが、C++ 側とは順序が完全一致するかは別問題。ここでは合計と
    # ソート済み (name, points) 集合で比較する。
    entries = sorted((n, p) for (n, p) in yaku_list)
    return (total, tuple(entries))


def cpp_run(inputs):
    """inputs: list of (mask:int, hanami:bool, tsukimi:bool)
    returns: list of (total:int, [(name,pts),...]) matching inputs order
    """
    stdin_data = "\n".join(
        f"{m:012x} {int(h)} {int(t)}" for (m, h, t) in inputs
    ) + "\n"
    proc = subprocess.run(
        [str(CPP_BIN)],
        input=stdin_data,
        capture_output=True,
        text=True,
        check=True,
    )
    results = []
    for line in proc.stdout.strip().split("\n"):
        # format: <hex> | <total> | <name1>:<p1>,<name2>:<p2>,...
        parts = line.split(" | ")
        assert len(parts) == 3, f"bad line: {line!r}"
        total = int(parts[1])
        yaku = []
        if parts[2]:
            for entry in parts[2].split(","):
                name, pts_s = entry.rsplit(":", 1)
                yaku.append((name, int(pts_s)))
        results.append((total, yaku))
    return results


def random_mask(rng):
    # カード数 0..48 を一様 + もう少し多めに分布させる
    n = rng.randint(0, NUM_CARDS)
    ids = rng.sample(range(NUM_CARDS), n)
    return mask_from_ids(ids)


def hand_crafted_cases():
    cases = []

    # 1. 空
    cases.append((0, True, True))

    # 2. 五光 (光5枚)
    hikari = [c.id for c in DECK if c.card_type == "光"]
    assert len(hikari) == 5
    cases.append((mask_from_ids(hikari), True, True))

    # 3. 四光 (柳光除く光4枚)
    yanagi = next(c for c in DECK if c.name == "柳に小野道風")
    non_rain_hikari = [c.id for c in DECK if c.card_type == "光" and c.id != yanagi.id]
    cases.append((mask_from_ids(non_rain_hikari), True, True))

    # 4. 雨四光 (柳光を含む光4枚)
    cases.append((mask_from_ids(non_rain_hikari[:3] + [yanagi.id]), True, True))

    # 5. 三光 (柳光なし 3枚)
    cases.append((mask_from_ids(non_rain_hikari[:3]), True, True))

    # 6. 柳光含む 3枚 — 三光は成立しない (柳以外は 2 枚のみ)
    cases.append((mask_from_ids(non_rain_hikari[:2] + [yanagi.id]), True, True))

    # 7. 柳光含む 4枚 — 雨四光
    cases.append((mask_from_ids(non_rain_hikari[:3] + [yanagi.id]), True, True))

    # 8. 猪鹿蝶
    ino = next(c for c in DECK if c.name == "萩に猪")
    shika = next(c for c in DECK if c.name == "紅葉に鹿")
    cho = next(c for c in DECK if c.name == "牡丹に蝶")
    cases.append((mask_from_ids([ino.id, shika.id, cho.id]), True, True))

    # 9. 赤短
    akatan = [c.id for c in DECK if c.tanzaku_type == "赤短"]
    assert len(akatan) == 3
    cases.append((mask_from_ids(akatan), True, True))

    # 10. 青短
    aotan = [c.id for c in DECK if c.tanzaku_type == "青短"]
    assert len(aotan) == 3
    cases.append((mask_from_ids(aotan), True, True))

    # 11. たん (短冊 5)
    tanzaku = [c.id for c in DECK if c.card_type == "短冊"][:5]
    cases.append((mask_from_ids(tanzaku), True, True))

    # 12. たん (短冊 7)
    tanzaku7 = [c.id for c in DECK if c.card_type == "短冊"][:7]
    cases.append((mask_from_ids(tanzaku7), True, True))

    # 13. たね (種 5)
    tane5 = [c.id for c in DECK if c.card_type == "種"][:5]
    cases.append((mask_from_ids(tane5), True, True))

    # 14. カス (カス 10)
    kasu10 = [c.id for c in DECK if c.card_type == "カス"][:10]
    cases.append((mask_from_ids(kasu10), True, True))

    # 15. カス (カス 12)
    kasu12 = [c.id for c in DECK if c.card_type == "カス"][:12]
    cases.append((mask_from_ids(kasu12), True, True))

    # 16. 花見で一杯
    sakura = next(c for c in DECK if c.name == "桜に幕")
    kiku = next(c for c in DECK if c.name == "菊に盃")
    cases.append((mask_from_ids([sakura.id, kiku.id]), True, True))

    # 17. 花見で一杯 (ルール off)
    cases.append((mask_from_ids([sakura.id, kiku.id]), False, True))

    # 18. 月見で一杯
    susuki = next(c for c in DECK if c.name == "芒に月")
    cases.append((mask_from_ids([susuki.id, kiku.id]), True, True))

    # 19. 月見で一杯 (ルール off)
    cases.append((mask_from_ids([susuki.id, kiku.id]), True, False))

    # 20. 全札 (48枚全部)
    cases.append(((1 << 48) - 1, True, True))

    return cases


def main():
    if not CPP_BIN.exists():
        print(f"ERROR: {CPP_BIN} not found. Build first.", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(0xC0FFEE)

    inputs = []
    inputs.extend(hand_crafted_cases())
    for _ in range(10000):
        m = random_mask(rng)
        h = rng.randint(0, 1)
        t = rng.randint(0, 1)
        inputs.append((m, bool(h), bool(t)))

    cpp_results = cpp_run(inputs)
    assert len(cpp_results) == len(inputs)

    mismatches = 0
    first_errors = []
    for (m, h, t), (c_total, c_yaku) in zip(inputs, cpp_results):
        captured = [DECK[i] for i in ids_from_mask(m)]
        rules = {"hanami": h, "tsukimi": t}
        py_yaku = check_yaku(captured, rules)
        py_total = total_yaku_points(py_yaku)

        if canonical(c_total, c_yaku) != canonical(py_total, py_yaku):
            mismatches += 1
            if len(first_errors) < 5:
                first_errors.append({
                    "mask": f"{m:012x}",
                    "hanami": h,
                    "tsukimi": t,
                    "py_total": py_total,
                    "py_yaku": sorted(py_yaku),
                    "cpp_total": c_total,
                    "cpp_yaku": sorted(c_yaku),
                    "card_count": bin(m).count("1"),
                })

    n = len(inputs)
    print(f"Checked: {n} inputs")
    print(f"Mismatches: {mismatches}")
    if mismatches:
        print()
        print("First errors:")
        for e in first_errors:
            print(f"  mask={e['mask']} (cards={e['card_count']}) hanami={e['hanami']} tsukimi={e['tsukimi']}")
            print(f"    py : total={e['py_total']} yaku={e['py_yaku']}")
            print(f"    cpp: total={e['cpp_total']} yaku={e['cpp_yaku']}")
        sys.exit(1)
    print(f"PASS — Python {n}/{n}==== C++")


if __name__ == "__main__":
    main()
