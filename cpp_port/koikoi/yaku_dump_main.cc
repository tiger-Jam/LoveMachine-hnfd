// yaku_dump_main.cc — stdin から 48bit captured mask を読み、役と合計点を stdout に出す。
// Python 側 (core.py::check_yaku) と 1:1 比較するためのドライバ。
//
// 入力フォーマット (各行):
//   <hex_mask>  <hanami:0/1>  <tsukimi:0/1>
//
// 出力フォーマット (各行):
//   <hex_mask> | <total> | <name1>:<p1>,<name2>:<p2>,...
//
// Build:
//   clang++ -std=c++17 -O2 -I<repo>/vendor/open_spiel \
//     koikoi_yaku.cc yaku_dump_main.cc -o yaku_dump

#include <cstdio>
#include <cstdint>
#include <iostream>
#include <string>

#include "open_spiel/games/koikoi/koikoi_yaku.h"

int main() {
  using namespace open_spiel::koikoi;
  std::ios::sync_with_stdio(false);
  std::cin.tie(nullptr);

  std::string hex;
  int hanami, tsukimi;
  while (std::cin >> hex >> hanami >> tsukimi) {
    CardMask mask = 0;
    // hex (大文字小文字両対応)
    for (char c : hex) {
      int d;
      if (c >= '0' && c <= '9') d = c - '0';
      else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
      else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
      else continue;  // ignore separators
      mask = (mask << 4) | d;
    }
    YakuRules rules;
    rules.hanami = (hanami != 0);
    rules.tsukimi = (tsukimi != 0);
    auto yaku = CheckYaku(mask, rules);
    int total = TotalYakuPoints(yaku);

    std::cout << hex << " | " << total << " | ";
    for (size_t i = 0; i < yaku.size(); ++i) {
      if (i) std::cout << ",";
      std::cout << yaku[i].name << ":" << yaku[i].points;
    }
    std::cout << "\n";
  }
  return 0;
}
