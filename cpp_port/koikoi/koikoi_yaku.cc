// koikoi_yaku.cc — 役判定の実装
// core.py::check_yaku と完全に同じ順序・同じ成立条件・同じ点数を返す。

#include "open_spiel/games/koikoi/koikoi_yaku.h"

namespace open_spiel {
namespace koikoi {

std::vector<YakuInstance> CheckYaku(CardMask captured, const YakuRules& rules) {
  std::vector<YakuInstance> yaku;
  yaku.reserve(8);

  const CardMask hikari  = captured & kHikariMask;
  const CardMask tane    = captured & kTaneMask;
  const CardMask tanzaku = captured & kTanzakuMask;
  const CardMask kasu    = captured & kKasuMask;
  const int n_hikari  = PopCount(hikari);
  const int n_tane    = PopCount(tane);
  const int n_tanzaku = PopCount(tanzaku);
  const int n_kasu    = PopCount(kasu);
  const bool has_ono  = (hikari & kYanagiHikariBit) != 0;

  // --- 光系 (core.py の分岐を完全再現) ---
  // 5 枚 → 五光
  // 4 枚 + 柳光あり → 雨四光、柳光なし → 四光
  // 3 枚以上 + 柳光なし → 三光
  // 3 枚以上 + 柳光あり → 柳光を除いた枚数 >= 3 なら三光 (= 4枚以上のとき)
  if (n_hikari == 5) {
    yaku.push_back({"五光", 15});
  } else if (n_hikari == 4) {
    if (has_ono) {
      yaku.push_back({"雨四光", 8});
    } else {
      yaku.push_back({"四光", 10});
    }
  } else if (n_hikari >= 3 && !has_ono) {
    yaku.push_back({"三光", 6});
  } else if (n_hikari >= 3 && has_ono) {
    const int non_ono = n_hikari - 1;
    if (non_ono >= 3) {
      yaku.push_back({"三光", 6});
    }
  }

  // --- 短冊系 ---
  const int n_akatan = PopCount(tanzaku & kAkatanMask);
  const int n_aotan  = PopCount(tanzaku & kAotanMask);
  if (n_akatan >= 3) yaku.push_back({"赤短", 6});
  if (n_aotan  >= 3) yaku.push_back({"青短", 6});
  if (n_tanzaku >= 5) yaku.push_back({"たん", 1 + (n_tanzaku - 5)});

  // --- 猪鹿蝶 ---
  if ((captured & kInoshikachoMask) == kInoshikachoMask) {
    yaku.push_back({"猪鹿蝶", 5});
  }

  // --- 種系 ---
  if (n_tane >= 5) yaku.push_back({"たね", 1 + (n_tane - 5)});

  // --- カス ---
  if (n_kasu >= 10) yaku.push_back({"カス", 1 + (n_kasu - 10)});

  // --- 花見・月見 (ルール依存) ---
  if (rules.hanami && (captured & kHanamiMask) == kHanamiMask) {
    yaku.push_back({"花見で一杯", 5});
  }
  if (rules.tsukimi && (captured & kTsukimiMask) == kTsukimiMask) {
    yaku.push_back({"月見で一杯", 5});
  }

  return yaku;
}

int TotalYakuPointsFast(CardMask captured, const YakuRules& rules) {
  int total = 0;

  const CardMask hikari  = captured & kHikariMask;
  const CardMask tane    = captured & kTaneMask;
  const CardMask tanzaku = captured & kTanzakuMask;
  const CardMask kasu    = captured & kKasuMask;
  const int n_hikari  = PopCount(hikari);
  const int n_tane    = PopCount(tane);
  const int n_tanzaku = PopCount(tanzaku);
  const int n_kasu    = PopCount(kasu);
  const bool has_ono  = (hikari & kYanagiHikariBit) != 0;

  if (n_hikari == 5) {
    total += 15;
  } else if (n_hikari == 4) {
    total += has_ono ? 8 : 10;
  } else if (n_hikari >= 3 && !has_ono) {
    total += 6;
  } else if (n_hikari >= 3 && has_ono && (n_hikari - 1) >= 3) {
    total += 6;
  }

  if (PopCount(tanzaku & kAkatanMask) >= 3) total += 6;
  if (PopCount(tanzaku & kAotanMask)  >= 3) total += 6;
  if (n_tanzaku >= 5) total += 1 + (n_tanzaku - 5);

  if ((captured & kInoshikachoMask) == kInoshikachoMask) total += 5;
  if (n_tane >= 5) total += 1 + (n_tane - 5);
  if (n_kasu >= 10) total += 1 + (n_kasu - 10);

  if (rules.hanami && (captured & kHanamiMask) == kHanamiMask) total += 5;
  if (rules.tsukimi && (captured & kTsukimiMask) == kTsukimiMask) total += 5;

  return total;
}

}  // namespace koikoi
}  // namespace open_spiel
