// koikoi_pybind.cc — pybind11 で C++ KoikoiEngine を Python に公開
// import _koikoi_native でロードできる。

#include <array>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include "open_spiel/games/koikoi/koikoi_engine.h"

namespace py = pybind11;
using namespace open_spiel::koikoi;

// EngineEvent を Python tuple に変換 (engine.py::info["events"] と完全互換)
static py::tuple EventToTuple(const EngineEvent& e) {
  switch (e.type) {
    case EngineEvent::Type::kHandNoMatch:
      return py::make_tuple("hand_no_match", e.card_id);
    case EngineEvent::Type::kHandMatch:
      return py::make_tuple("hand_match", e.card_id, e.matched_id);
    case EngineEvent::Type::kHandMatchAll:
      return py::make_tuple("hand_match_all", e.card_id,
                            py::cast(e.matched_ids));
    case EngineEvent::Type::kHandChoose:
      return py::make_tuple("hand_choose", e.card_id,
                            py::cast(e.matched_ids));
    case EngineEvent::Type::kDraw:
      return py::make_tuple("draw", e.card_id);
    case EngineEvent::Type::kDrawMatch:
      return py::make_tuple("draw_match", e.card_id, e.matched_id);
    case EngineEvent::Type::kDrawMatchAll:
      return py::make_tuple("draw_match_all", e.card_id,
                            py::cast(e.matched_ids));
    case EngineEvent::Type::kDrawChoose:
      return py::make_tuple("draw_choose", e.card_id,
                            py::cast(e.matched_ids));
    case EngineEvent::Type::kYakuFormed: {
      py::list yaku_list;
      for (const auto& y : e.yaku) {
        yaku_list.append(py::make_tuple(std::string(y.name), y.points));
      }
      return py::make_tuple("yaku_formed", e.player, yaku_list, e.points);
    }
    case EngineEvent::Type::kShowdown:
      return py::make_tuple("showdown", e.player, e.points);
    case EngineEvent::Type::kKoikoi:
      return py::make_tuple("koikoi", e.player);
    case EngineEvent::Type::kBonus7Plus:
      return py::make_tuple("bonus_7plus");
    case EngineEvent::Type::kBonusOpponentKoikoi:
      return py::make_tuple("bonus_opponent_koikoi");
    case EngineEvent::Type::kRoundEnd:
      return py::make_tuple("round_end", e.winner, e.points);
    case EngineEvent::Type::kExhausted:
      return py::make_tuple("exhausted");
  }
  return py::make_tuple("unknown");
}

static py::object SpecialDealToObj(const SpecialDealInfo& s) {
  // engine.py::reset の戻り値: dict, info["special"] が None / "redeal" /
  // "teshi:N" / "kuttsuki:N"
  py::dict info;
  switch (s.kind) {
    case SpecialDealInfo::Kind::kNone:    return info;
    case SpecialDealInfo::Kind::kRedeal:
      info["special"] = "redeal"; return info;
    case SpecialDealInfo::Kind::kTeshi:
      info["special"] = "teshi:" + std::to_string(s.player); return info;
    case SpecialDealInfo::Kind::kKuttsuki:
      info["special"] = "kuttsuki:" + std::to_string(s.player); return info;
  }
  return info;
}

// dict (engine.py の rules) → EngineRules
static EngineRules DictToRules(const py::dict& d) {
  EngineRules r;
  if (d.contains("koikoi_double"))
    r.koikoi_double = d["koikoi_double"].cast<bool>();
  if (d.contains("seven_plus_double"))
    r.seven_plus_double = d["seven_plus_double"].cast<bool>();
  if (d.contains("hanami"))
    r.hanami = d["hanami"].cast<bool>();
  if (d.contains("tsukimi"))
    r.tsukimi = d["tsukimi"].cast<bool>();
  if (d.contains("multi_koikoi")) {
    auto s = d["multi_koikoi"].cast<std::string>();
    if      (s == "oyaken")       r.multi_koikoi = MultiKoikoiRule::kOyaken;
    else if (s == "last_koikoi")  r.multi_koikoi = MultiKoikoiRule::kLastKoikoi;
    else if (s == "first_koikoi") r.multi_koikoi = MultiKoikoiRule::kFirstKoikoi;
  }
  if (d.contains("ryuukyoku")) {
    auto s = d["ryuukyoku"].cast<std::string>();
    if      (s == "oyaken")    r.ryuukyoku = RyuukyokuRule::kOyaken;
    else if (s == "no_change") r.ryuukyoku = RyuukyokuRule::kNoChange;
    else if (s == "change")    r.ryuukyoku = RyuukyokuRule::kChange;
  }
  return r;
}

static py::dict RulesToDict(const EngineRules& r) {
  py::dict d;
  d["koikoi_double"] = r.koikoi_double;
  d["seven_plus_double"] = r.seven_plus_double;
  d["hanami"] = r.hanami;
  d["tsukimi"] = r.tsukimi;
  d["multi_koikoi"] = (r.multi_koikoi == MultiKoikoiRule::kOyaken)      ? "oyaken"
                    : (r.multi_koikoi == MultiKoikoiRule::kLastKoikoi)  ? "last_koikoi"
                    :                                                     "first_koikoi";
  d["ryuukyoku"]    = (r.ryuukyoku    == RyuukyokuRule::kOyaken)        ? "oyaken"
                    : (r.ryuukyoku    == RyuukyokuRule::kNoChange)      ? "no_change"
                    :                                                     "change";
  return d;
}

PYBIND11_MODULE(_koikoi_native, m) {
  m.doc() = "Koi-Koi engine (C++ implementation, Python binding)";

  m.attr("NUM_CARDS")       = kNumCards;
  m.attr("ACTION_KOIKOI")   = kActionKoikoi;
  m.attr("ACTION_SHOWDOWN") = kActionShowdown;
  m.attr("NUM_ACTIONS")     = kNumActions;
  m.attr("OBS_SIZE")        = kObsSize;

  py::enum_<Phase>(m, "Phase")
    .value("HAND_PLAY",  Phase::kHandPlay)
    .value("HAND_MATCH", Phase::kHandMatch)
    .value("DRAW_MATCH", Phase::kDrawMatch)
    .value("KOIKOI",     Phase::kKoikoi)
    .value("DONE",       Phase::kDone);

  py::class_<KoikoiEngine>(m, "KoikoiEngine")
    .def(py::init([](py::object rules_obj) {
       if (rules_obj.is_none()) return new KoikoiEngine(EngineRules{});
       return new KoikoiEngine(DictToRules(rules_obj.cast<py::dict>()));
     }), py::arg("rules") = py::none())

    // 状態クエリ
    .def_property_readonly("phase", &KoikoiEngine::phase)
    .def_property_readonly("current_player", &KoikoiEngine::current_player)
    .def_property_readonly("oya_index", &KoikoiEngine::oya_index)
    .def_property_readonly("done", &KoikoiEngine::done)
    .def_property_readonly("winner",
        [](const KoikoiEngine& e) -> py::object {
          if (e.winner() == -1) return py::none();
          return py::int_(e.winner());
        })
    .def_property_readonly("win_score", &KoikoiEngine::win_score)
    .def_property_readonly("ryuukyoku", &KoikoiEngine::ryuukyoku)
    .def_property_readonly("ryuukyoku_oya_swap", &KoikoiEngine::ryuukyoku_oya_swap)
    .def_property_readonly("first_koikoi_player",
        [](const KoikoiEngine& e) -> py::object {
          if (e.first_koikoi_player() == -1) return py::none();
          return py::int_(e.first_koikoi_player());
        })
    .def_property_readonly("last_koikoi_player",
        [](const KoikoiEngine& e) -> py::object {
          if (e.last_koikoi_player() == -1) return py::none();
          return py::int_(e.last_koikoi_player());
        })
    .def_property_readonly("rules",
        [](const KoikoiEngine& e) { return RulesToDict(e.rules()); })

    // ID リスト形式の状態
    .def("hand_ids",     [](const KoikoiEngine& e, int p) { return e.players_hand(p); })
    .def("captured_ids", [](const KoikoiEngine& e, int p) { return e.players_captured(p); })
    .def("field_ids",    [](const KoikoiEngine& e) { return e.field(); })
    .def("deck_ids",     [](const KoikoiEngine& e) { return e.deck(); })
    .def("player_koikoi", [](const KoikoiEngine& e, int p) { return e.players_koikoi(p); })
    .def("players_prev_yaku",
         [](const KoikoiEngine& e, int p) { return e.players_prev_yaku(p); })
    .def("pending_played_id",
         [](const KoikoiEngine& e) -> py::object {
           if (e.pending_played() == -1) return py::none();
           return py::int_(e.pending_played());
         })
    .def("pending_match_ids",
         [](const KoikoiEngine& e) { return e.pending_matches(); })

    // 操作
    .def("reset",
         [](KoikoiEngine& e, int oya, py::object seed_obj) {
           uint64_t seed = 0;
           if (seed_obj.is_none()) {
             // engine.py: if seed is None: ランダム化(再現性なし)
             // ここは std::random_device 経由で 1 回だけシードする
             seed = std::random_device{}();
           } else {
             seed = seed_obj.cast<uint64_t>();
           }
           return SpecialDealToObj(e.Reset(oya, seed));
         },
         py::arg("oya") = 0, py::arg("seed") = py::none())
    .def("reset_with_deck",
         [](KoikoiEngine& e, int oya, const std::vector<int>& deck) {
           if (deck.size() != 48) throw std::runtime_error("deck must have 48 ids");
           std::array<int, 48> a;
           for (int i = 0; i < 48; ++i) a[i] = deck[i];
           return SpecialDealToObj(e.ResetWithDeck(oya, a));
         },
         py::arg("oya"), py::arg("deck"))
    .def("get_legal_actions", &KoikoiEngine::GetLegalActions)
    .def("step",
         [](KoikoiEngine& e, int action) {
           auto evs = e.Step(action);
           py::list ev_list;
           for (const auto& ev : evs) ev_list.append(EventToTuple(ev));
           py::dict info;
           info["events"] = ev_list;
           return info;
         })
    .def("get_observation",
         [](const KoikoiEngine& e, int p) {
           auto a = e.GetObservation(p);
           py::array_t<float> arr(static_cast<py::ssize_t>(kObsSize));
           std::memcpy(arr.mutable_data(), a.data(), kObsSize * sizeof(float));
           return arr;
         })
    .def("get_action_mask",
         [](const KoikoiEngine& e) {
           auto a = e.GetActionMask();
           py::array_t<bool> arr(static_cast<py::ssize_t>(kNumActions));
           bool* p = arr.mutable_data();
           for (int i = 0; i < kNumActions; ++i) p[i] = a[i];
           return arr;
         });
}
