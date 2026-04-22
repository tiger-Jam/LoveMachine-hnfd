#!/usr/bin/env python3
"""花札カード画像をWikimedia Commonsからダウンロード

Louie Mantia作、CC BY-SA 4.0ライセンス
"""

import hashlib
import subprocess
import time
from pathlib import Path

CARDS_DIR = Path(__file__).parent / "static" / "cards"

CARD_FILES = {
    0:  "Hanafuda_January_Hikari.svg",
    1:  "Hanafuda_January_Tanzaku.svg",
    2:  "Hanafuda_January_Kasu_1.svg",
    3:  "Hanafuda_January_Kasu_2.svg",
    4:  "Hanafuda_February_Tane.svg",
    5:  "Hanafuda_February_Tanzaku.svg",
    6:  "Hanafuda_February_Kasu_1.svg",
    7:  "Hanafuda_February_Kasu_2.svg",
    8:  "Hanafuda_March_Hikari.svg",
    9:  "Hanafuda_March_Tanzaku.svg",
    10: "Hanafuda_March_Kasu_1.svg",
    11: "Hanafuda_March_Kasu_2.svg",
    12: "Hanafuda_April_Tane.svg",
    13: "Hanafuda_April_Tanzaku.svg",
    14: "Hanafuda_April_Kasu_1.svg",
    15: "Hanafuda_April_Kasu_2.svg",
    16: "Hanafuda_May_Tane.svg",
    17: "Hanafuda_May_Tanzaku.svg",
    18: "Hanafuda_May_Kasu_1.svg",
    19: "Hanafuda_May_Kasu_2.svg",
    20: "Hanafuda_June_Tane.svg",
    21: "Hanafuda_June_Tanzaku.svg",
    22: "Hanafuda_June_Kasu_1.svg",
    23: "Hanafuda_June_Kasu_2.svg",
    24: "Hanafuda_July_Tane.svg",
    25: "Hanafuda_July_Tanzaku.svg",
    26: "Hanafuda_July_Kasu_1.svg",
    27: "Hanafuda_July_Kasu_2.svg",
    28: "Hanafuda_August_Hikari.svg",
    29: "Hanafuda_August_Tane.svg",
    30: "Hanafuda_August_Kasu_1.svg",
    31: "Hanafuda_August_Kasu_2.svg",
    32: "Hanafuda_September_Tane.svg",
    33: "Hanafuda_September_Tanzaku.svg",
    34: "Hanafuda_September_Kasu_1.svg",
    35: "Hanafuda_September_Kasu_2.svg",
    36: "Hanafuda_October_Tane.svg",
    37: "Hanafuda_October_Tanzaku.svg",
    38: "Hanafuda_October_Kasu_1.svg",
    39: "Hanafuda_October_Kasu_2.svg",
    40: "Hanafuda_November_Hikari.svg",
    41: "Hanafuda_November_Tane.svg",
    42: "Hanafuda_November_Tanzaku.svg",
    43: "Hanafuda_November_Kasu.svg",
    44: "Hanafuda_December_Hikari.svg",
    45: "Hanafuda_December_Kasu_1.svg",
    46: "Hanafuda_December_Kasu_2.svg",
    47: "Hanafuda_December_Kasu_3.svg",
}

BACK_FILE = "Hanafuda_card_back.svg"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def wikimedia_url(filename):
    md5 = hashlib.md5(filename.encode()).hexdigest()
    return f"https://upload.wikimedia.org/wikipedia/commons/{md5[0]}/{md5[:2]}/{filename}"


def download_file(filename, dest):
    url = wikimedia_url(filename)
    print(f"  {filename} ... ", end="", flush=True)
    try:
        result = subprocess.run(
            ["curl", "-sfL", "-A", UA, "-o", str(dest), url],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and dest.exists() and dest.stat().st_size > 100:
            print(f"OK ({dest.stat().st_size} bytes)")
            return True
        else:
            dest.unlink(missing_ok=True)
            print(f"FAILED (curl exit {result.returncode})")
            return False
    except Exception as e:
        dest.unlink(missing_ok=True)
        print(f"FAILED: {e}")
        return False


def main():
    CARDS_DIR.mkdir(parents=True, exist_ok=True)

    print("花札カード画像をダウンロード中...")
    print(f"保存先: {CARDS_DIR}")
    print(f"ライセンス: CC BY-SA 4.0 (Louie Mantia)\n")

    success = 0
    total = len(CARD_FILES) + 1

    for card_id, filename in sorted(CARD_FILES.items()):
        dest = CARDS_DIR / f"{card_id}.svg"
        if dest.exists():
            print(f"  {card_id}.svg exists, skip")
            success += 1
            continue
        if download_file(filename, dest):
            success += 1
        time.sleep(2)

    dest_back = CARDS_DIR / "back.svg"
    if dest_back.exists():
        print(f"  back.svg exists, skip")
        success += 1
    elif download_file(BACK_FILE, dest_back):
        success += 1

    print(f"\n完了: {success}/{total} ファイル")
    if success == total:
        print("全カード画像のダウンロード成功!")
    else:
        print("一部のダウンロードに失敗しました。再実行してください。")


if __name__ == "__main__":
    main()
