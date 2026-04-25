// engine_dump_main.cc — Python とのクロス検証用 stdin/stdout ドライバ
//
// Protocol (all line-based):
//
//   IN  > "DECK <48 ints>"     初期 deck order (player0[0..7] player1[8..15]
//                              field[16..23] deck[24..47])
//   IN  > "OYA <int>"          oya index (0 or 1)
//   IN  > "RULES <kk_double> <7p_double> <hanami> <tsukimi> <multi> <ryuu>"
//                              kk_double, 7p_double, hanami, tsukimi: 0/1
//                              multi:  oyaken | last_koikoi | first_koikoi
//                              ryuu :  oyaken | no_change   | change
//   IN  > "RESET"              ResetWithDeck 実行 → "STATE..." 出力
//   IN  > "ACTION <int>"       step(action) → "STATE..." 出力
//   IN  > "OBS <player>"       get_observation → "OBS <340 floats>"
//   IN  > "QUIT"
//
//   OUT > "STATE phase=<P> cur=<P> oya=<O> done=<0/1> winner=<W> score=<S> "
//             "ryuu=<0/1> ryuu_swap=<0/1> "
//             "h0=<csv> h1=<csv> c0=<csv> c1=<csv> field=<csv> deck=<csv> "
//             "kk0=<0/1> kk1=<0/1> prev0=<int> prev1=<int> "
//             "first_kk=<int> last_kk=<int> pending=<int> pmatches=<csv> "
//             "special=<none|redeal|teshi:N|kuttsuki:N>"
//   OUT > "EVENTS <n>" 続いて n 行 "EV <name> <args>"

#include <array>
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "open_spiel/games/koikoi/koikoi_engine.h"

using namespace open_spiel::koikoi;

static std::string CsvIds(const std::vector<int>& v) {
  std::ostringstream s;
  for (size_t i = 0; i < v.size(); ++i) {
    if (i) s << ",";
    s << v[i];
  }
  return s.str();
}

static std::string PhaseStr(Phase p) {
  switch (p) {
    case Phase::kHandPlay:  return "HAND_PLAY";
    case Phase::kHandMatch: return "HAND_MATCH";
    case Phase::kDrawMatch: return "DRAW_MATCH";
    case Phase::kKoikoi:    return "KOIKOI";
    case Phase::kDone:      return "DONE";
  }
  return "?";
}

static void DumpState(const KoikoiEngine& e,
                      SpecialDealInfo special = {SpecialDealInfo::Kind::kNone, -1}) {
  std::string special_str;
  switch (special.kind) {
    case SpecialDealInfo::Kind::kNone:     special_str = "none"; break;
    case SpecialDealInfo::Kind::kRedeal:   special_str = "redeal"; break;
    case SpecialDealInfo::Kind::kTeshi:
      special_str = "teshi:" + std::to_string(special.player); break;
    case SpecialDealInfo::Kind::kKuttsuki:
      special_str = "kuttsuki:" + std::to_string(special.player); break;
  }
  std::cout
      << "STATE phase=" << PhaseStr(e.phase())
      << " cur="    << e.current_player()
      << " oya="    << e.oya_index()
      << " done="   << (e.done() ? 1 : 0)
      << " winner=" << e.winner()
      << " score="  << e.win_score()
      << " ryuu="   << (e.ryuukyoku() ? 1 : 0)
      << " ryuu_swap=" << (e.ryuukyoku_oya_swap() ? 1 : 0)
      << " h0="    << CsvIds(e.players_hand(0))
      << " h1="    << CsvIds(e.players_hand(1))
      << " c0="    << CsvIds(e.players_captured(0))
      << " c1="    << CsvIds(e.players_captured(1))
      << " field=" << CsvIds(e.field())
      << " deck="  << CsvIds(e.deck())
      << " kk0="   << (e.players_koikoi(0) ? 1 : 0)
      << " kk1="   << (e.players_koikoi(1) ? 1 : 0)
      << " prev0=" << e.players_prev_yaku(0)
      << " prev1=" << e.players_prev_yaku(1)
      << " first_kk=" << e.first_koikoi_player()
      << " last_kk="  << e.last_koikoi_player()
      << " pending="  << e.pending_played()
      << " pmatches=" << CsvIds(e.pending_matches())
      << " special=" << special_str
      << "\n";
}

static void DumpEvents(const std::vector<EngineEvent>& evs) {
  std::cout << "EVENTS " << evs.size() << "\n";
  for (const auto& e : evs) {
    std::cout << "EV ";
    switch (e.type) {
      case EngineEvent::Type::kHandNoMatch:
        std::cout << "hand_no_match " << e.card_id; break;
      case EngineEvent::Type::kHandMatch:
        std::cout << "hand_match " << e.card_id << " " << e.matched_id; break;
      case EngineEvent::Type::kHandMatchAll:
        std::cout << "hand_match_all " << e.card_id << " " << CsvIds(e.matched_ids); break;
      case EngineEvent::Type::kHandChoose:
        std::cout << "hand_choose " << e.card_id << " " << CsvIds(e.matched_ids); break;
      case EngineEvent::Type::kDraw:
        std::cout << "draw " << e.card_id; break;
      case EngineEvent::Type::kDrawMatch:
        std::cout << "draw_match " << e.card_id << " " << e.matched_id; break;
      case EngineEvent::Type::kDrawMatchAll:
        std::cout << "draw_match_all " << e.card_id << " " << CsvIds(e.matched_ids); break;
      case EngineEvent::Type::kDrawChoose:
        std::cout << "draw_choose " << e.card_id << " " << CsvIds(e.matched_ids); break;
      case EngineEvent::Type::kYakuFormed: {
        std::ostringstream y;
        for (size_t i = 0; i < e.yaku.size(); ++i) {
          if (i) y << ",";
          y << e.yaku[i].name << ":" << e.yaku[i].points;
        }
        std::cout << "yaku_formed " << e.player << " " << e.points << " " << y.str();
        break;
      }
      case EngineEvent::Type::kShowdown:
        std::cout << "showdown " << e.player << " " << e.points; break;
      case EngineEvent::Type::kKoikoi:
        std::cout << "koikoi " << e.player; break;
      case EngineEvent::Type::kBonus7Plus:
        std::cout << "bonus_7plus"; break;
      case EngineEvent::Type::kBonusOpponentKoikoi:
        std::cout << "bonus_opponent_koikoi"; break;
      case EngineEvent::Type::kRoundEnd:
        std::cout << "round_end " << e.winner << " " << e.points; break;
      case EngineEvent::Type::kExhausted:
        std::cout << "exhausted"; break;
    }
    std::cout << "\n";
  }
}

int main() {
  std::ios::sync_with_stdio(false);
  std::cin.tie(nullptr);

  EngineRules rules;
  std::array<int, 48> deck{};
  int oya = 0;
  KoikoiEngine* engine = nullptr;
  SpecialDealInfo last_special{SpecialDealInfo::Kind::kNone, -1};

  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream iss(line);
    std::string cmd; iss >> cmd;
    if (cmd == "DECK") {
      for (int i = 0; i < 48; ++i) iss >> deck[i];
      std::cout << "OK\n";
    } else if (cmd == "OYA") {
      iss >> oya;
      std::cout << "OK\n";
    } else if (cmd == "RULES") {
      int kkd, sevenp, han, tsu;
      std::string multi, ryuu;
      iss >> kkd >> sevenp >> han >> tsu >> multi >> ryuu;
      rules.koikoi_double = kkd != 0;
      rules.seven_plus_double = sevenp != 0;
      rules.hanami = han != 0;
      rules.tsukimi = tsu != 0;
      if      (multi == "oyaken")       rules.multi_koikoi = MultiKoikoiRule::kOyaken;
      else if (multi == "last_koikoi")  rules.multi_koikoi = MultiKoikoiRule::kLastKoikoi;
      else if (multi == "first_koikoi") rules.multi_koikoi = MultiKoikoiRule::kFirstKoikoi;
      if      (ryuu == "oyaken")    rules.ryuukyoku = RyuukyokuRule::kOyaken;
      else if (ryuu == "no_change") rules.ryuukyoku = RyuukyokuRule::kNoChange;
      else if (ryuu == "change")    rules.ryuukyoku = RyuukyokuRule::kChange;
      std::cout << "OK\n";
    } else if (cmd == "RESET") {
      delete engine;
      engine = new KoikoiEngine(rules);
      last_special = engine->ResetWithDeck(oya, deck);
      DumpState(*engine, last_special);
    } else if (cmd == "ACTION") {
      int a; iss >> a;
      auto evs = engine->Step(a);
      DumpState(*engine);
      DumpEvents(evs);
    } else if (cmd == "OBS") {
      int p; iss >> p;
      auto obs = engine->GetObservation(p);
      std::cout << "OBS";
      // 浮動小数の出力は小数点以下8桁固定 (Python の round(x, 8) と比較しやすく)
      char buf[32];
      for (int i = 0; i < kObsSize; ++i) {
        std::snprintf(buf, sizeof(buf), " %.8g", obs[i]);
        std::cout << buf;
      }
      std::cout << "\n";
    } else if (cmd == "LEGAL") {
      auto la = engine->GetLegalActions();
      std::cout << "LEGAL " << CsvIds(la) << "\n";
    } else if (cmd == "QUIT" || cmd.empty()) {
      break;
    } else {
      std::cout << "ERROR unknown_cmd " << cmd << "\n";
    }
    std::cout.flush();
  }
  delete engine;
  return 0;
}
