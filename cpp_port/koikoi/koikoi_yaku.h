// koikoi_yaku.h — 役判定
// Python 実装 (core.py::check_yaku / total_yaku_points) と完全に一致する結果を返す。

#ifndef OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_YAKU_H_
#define OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_YAKU_H_

#include <string>
#include <string_view>
#include <vector>

#include "open_spiel/games/koikoi/koikoi_cards.h"

namespace open_spiel {
namespace koikoi {

struct YakuInstance {
  std::string_view name;
  int points;
};

// ルール: core.py::check_yaku の rules dict に対応。
// - hanami : 花見で一杯を採用するか (default true)
// - tsukimi: 月見で一杯を採用するか (default true)
struct YakuRules {
  bool hanami = true;
  bool tsukimi = true;
};

// 取り札 (bitmask) から成立役リストを返す。順序は core.py と一致。
std::vector<YakuInstance> CheckYaku(CardMask captured,
                                    const YakuRules& rules = {});

inline int TotalYakuPoints(const std::vector<YakuInstance>& yaku) {
  int total = 0;
  for (const auto& y : yaku) total += y.points;
  return total;
}

// 捕捉: リストを生成せず合計点のみ欲しいときの最速経路。
int TotalYakuPointsFast(CardMask captured, const YakuRules& rules = {});

}  // namespace koikoi
}  // namespace open_spiel

#endif  // OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_YAKU_H_
