// koikoi.cc — OpenSpiel Game/State wrapper

#include "open_spiel/games/koikoi/koikoi.h"

#include <algorithm>
#include <memory>
#include <sstream>
#include <utility>

#include "open_spiel/abseil-cpp/absl/strings/str_cat.h"
#include "open_spiel/abseil-cpp/absl/strings/str_join.h"
#include "open_spiel/game_parameters.h"
#include "open_spiel/spiel.h"

namespace open_spiel {
namespace koikoi {
namespace {

const GameType kGameType{
    /*short_name=*/"koikoi",
    /*long_name=*/"Hanafuda Koi-Koi",
    GameType::Dynamics::kSequential,
    GameType::ChanceMode::kExplicitStochastic,
    GameType::Information::kImperfectInformation,
    GameType::Utility::kZeroSum,
    GameType::RewardModel::kTerminal,
    /*max_num_players=*/2,
    /*min_num_players=*/2,
    /*provides_information_state_string=*/true,
    /*provides_information_state_tensor=*/true,
    /*provides_observation_string=*/true,
    /*provides_observation_tensor=*/true,
    /*parameter_specification=*/
    {
      {"oya",                 GameParameter(0)},
      {"koikoi_double",       GameParameter(true)},
      {"seven_plus_double",   GameParameter(false)},
      {"hanami",              GameParameter(true)},
      {"tsukimi",             GameParameter(true)},
      {"multi_koikoi",        GameParameter(std::string("last_koikoi"))},
      {"ryuukyoku",           GameParameter(std::string("no_change"))},
    },
    /*default_loadable=*/true,
    /*provides_factored_observation_string=*/false,
};

std::shared_ptr<const Game> Factory(const GameParameters& params) {
  return std::shared_ptr<const Game>(new KoikoiGame(params));
}

REGISTER_SPIEL_GAME(kGameType, Factory);

EngineRules ParseRules(const GameParameters& p) {
  EngineRules r;
  auto get_b = [&](const std::string& k, bool d) {
    auto it = p.find(k);
    if (it == p.end()) return d;
    return it->second.bool_value();
  };
  auto get_s = [&](const std::string& k, std::string d) {
    auto it = p.find(k);
    if (it == p.end()) return d;
    return it->second.string_value();
  };
  r.koikoi_double     = get_b("koikoi_double",     true);
  r.seven_plus_double = get_b("seven_plus_double", false);
  r.hanami            = get_b("hanami",            true);
  r.tsukimi           = get_b("tsukimi",           true);
  std::string multi   = get_s("multi_koikoi",      "last_koikoi");
  std::string ryuu    = get_s("ryuukyoku",         "no_change");
  if      (multi == "oyaken")       r.multi_koikoi = MultiKoikoiRule::kOyaken;
  else if (multi == "first_koikoi") r.multi_koikoi = MultiKoikoiRule::kFirstKoikoi;
  else                              r.multi_koikoi = MultiKoikoiRule::kLastKoikoi;
  if      (ryuu == "oyaken") r.ryuukyoku = RyuukyokuRule::kOyaken;
  else if (ryuu == "change") r.ryuukyoku = RyuukyokuRule::kChange;
  else                       r.ryuukyoku = RyuukyokuRule::kNoChange;
  return r;
}

int ParseOya(const GameParameters& p) {
  auto it = p.find("oya");
  if (it == p.end()) return 0;
  return it->second.int_value();
}

}  // namespace

// ============================================================
// KoikoiGame
// ============================================================

KoikoiGame::KoikoiGame(const GameParameters& params)
    : Game(kGameType, params),
      rules_(ParseRules(params)),
      oya_(ParseOya(params)) {
  SPIEL_CHECK_TRUE(oya_ == 0 || oya_ == 1);
}

std::unique_ptr<State> KoikoiGame::NewInitialState() const {
  return std::make_unique<KoikoiState>(shared_from_this(), rules_, oya_);
}

// ============================================================
// KoikoiState
// ============================================================

KoikoiState::KoikoiState(std::shared_ptr<const Game> game,
                         const EngineRules& rules, int oya)
    : State(game),
      parent_game_(static_cast<const KoikoiGame*>(game.get())),
      rules_(rules),
      oya_(oya),
      engine_(rules) {
  for (int i = 0; i < 48; ++i) deal_perm_[i] = -1;
}

Player KoikoiState::CurrentPlayer() const {
  if (IsInDealPhase()) return kChancePlayerId;
  if (engine_ready_ && engine_.done()) return kTerminalPlayerId;
  return engine_ready_ ? engine_.current_player() : kChancePlayerId;
}

bool KoikoiState::IsTerminal() const {
  return engine_ready_ && engine_.done();
}

std::vector<Action> KoikoiState::LegalActions() const {
  if (IsTerminal()) return {};
  if (IsInDealPhase()) {
    // 残り未配布カードを返す
    std::vector<Action> out;
    out.reserve(48 - deal_step_);
    for (int i = 0; i < kNumCards; ++i) {
      if (!card_used_[i]) out.push_back(static_cast<Action>(i));
    }
    return out;
  }
  // プレイ phase: engine から取得
  std::vector<Action> out;
  for (int a : engine_.GetLegalActions()) out.push_back(static_cast<Action>(a));
  return out;
}

std::vector<std::pair<Action, double>> KoikoiState::ChanceOutcomes() const {
  SPIEL_CHECK_TRUE(IsInDealPhase());
  std::vector<std::pair<Action, double>> outcomes;
  const int n_remaining = 48 - deal_step_;
  const double p = 1.0 / n_remaining;
  for (int i = 0; i < kNumCards; ++i) {
    if (!card_used_[i]) outcomes.emplace_back(static_cast<Action>(i), p);
  }
  return outcomes;
}

void KoikoiState::DoApplyAction(Action move) {
  if (IsInDealPhase()) {
    // チャンス: スロット deal_step_ にカード move を置く
    SPIEL_CHECK_GE(move, 0);
    SPIEL_CHECK_LT(move, kNumCards);
    SPIEL_CHECK_FALSE(card_used_[move]);
    deal_perm_[deal_step_] = static_cast<int>(move);
    card_used_[move] = true;
    deal_step_++;
    if (deal_step_ == 48) {
      FinalizeDeal();
    }
    return;
  }
  // プレイ phase: engine.Step に委譲
  SPIEL_CHECK_TRUE(engine_ready_);
  engine_.Step(static_cast<int>(move));
}

void KoikoiState::FinalizeDeal() {
  engine_.ResetWithDeck(oya_, deal_perm_);
  engine_ready_ = true;
  // 注: 手四・くっつきが起きていたら engine_.done() == true で
  //     winner_/win_score_ が既にセットされている。Returns() で扱う。
  // 注: redeal (4-of-month in field) は無視。engine も winner 設定しない。
}

std::vector<double> KoikoiState::Returns() const {
  if (!IsTerminal()) return {0.0, 0.0};
  std::vector<double> r(2, 0.0);
  const int w = engine_.winner();
  const double score = static_cast<double>(engine_.win_score());
  if (w == 0)      { r[0] =  score; r[1] = -score; }
  else if (w == 1) { r[0] = -score; r[1] =  score; }
  // winner == -1 (流局 no_change) は両者 0
  return r;
}

std::string KoikoiState::ActionToString(Player player, Action move) const {
  if (player == kChancePlayerId) {
    return absl::StrCat("Deal[", deal_step_, "]=", Card(move).name);
  }
  if (move == kActionKoikoi)   return "Koikoi";
  if (move == kActionShowdown) return "Showdown";
  if (move >= 0 && move < kNumCards) {
    return absl::StrCat("Play(", Card(move).name, ")");
  }
  return absl::StrCat("UnknownAction(", move, ")");
}

std::string KoikoiState::ToString() const {
  std::ostringstream s;
  s << "[Koi-Koi";
  if (IsInDealPhase()) {
    s << " DealStep=" << deal_step_;
  } else {
    s << " Phase=";
    switch (engine_.phase()) {
      case Phase::kHandPlay:  s << "HAND_PLAY"; break;
      case Phase::kHandMatch: s << "HAND_MATCH"; break;
      case Phase::kDrawMatch: s << "DRAW_MATCH"; break;
      case Phase::kKoikoi:    s << "KOIKOI"; break;
      case Phase::kDone:      s << "DONE"; break;
    }
    s << " cur=" << engine_.current_player()
      << " oya=" << engine_.oya_index()
      << " deck=" << engine_.deck().size();
    if (engine_.done()) {
      s << " winner=" << engine_.winner()
        << " score=" << engine_.win_score();
    }
  }
  s << "]";
  return s.str();
}

std::string KoikoiState::InformationStateString(Player player) const {
  // 配り phase 中は player にとって観測できる情報がほぼ無い。
  if (IsInDealPhase()) {
    return absl::StrCat("P", player, "|deal_step=", deal_step_);
  }
  // プレイ phase: 自分の手札 + 場 + 自分取り札 + 相手取り札 + フェーズ
  std::ostringstream s;
  s << "P" << player;
  s << "|phase=";
  switch (engine_.phase()) {
    case Phase::kHandPlay:  s << "HP"; break;
    case Phase::kHandMatch: s << "HM"; break;
    case Phase::kDrawMatch: s << "DM"; break;
    case Phase::kKoikoi:    s << "KK"; break;
    case Phase::kDone:      s << "DONE"; break;
  }
  auto join_sorted = [](const std::vector<int>& v) {
    std::vector<int> sorted = v;
    std::sort(sorted.begin(), sorted.end());
    std::ostringstream o;
    for (size_t i = 0; i < sorted.size(); ++i) {
      if (i) o << ",";
      o << sorted[i];
    }
    return o.str();
  };
  s << "|H=" << join_sorted(engine_.players_hand(player));
  s << "|F=" << join_sorted(engine_.field());
  s << "|My=" << join_sorted(engine_.players_captured(player));
  s << "|Op=" << join_sorted(engine_.players_captured(1 - player));
  s << "|D=" << engine_.deck().size();
  s << "|OH=" << engine_.players_hand(1 - player).size();
  s << "|kk=" << (engine_.players_koikoi(0) ? "1" : "0")
    << (engine_.players_koikoi(1) ? "1" : "0");
  s << "|oya=" << engine_.oya_index();
  s << "|pend=" << engine_.pending_played();
  return s.str();
}

std::string KoikoiState::ObservationString(Player player) const {
  // 観測は info_state と同じ (perfect-recall)。簡略化のため同じ文字列。
  return InformationStateString(player);
}

void KoikoiState::InformationStateTensor(Player player,
                                         absl::Span<float> values) const {
  SPIEL_CHECK_EQ(values.size(), kObsSize);
  if (!engine_ready_) {
    // 配り phase 中は全 0 (deal 中は player decision が無いので学習で参照されない)
    std::fill(values.begin(), values.end(), 0.0f);
    return;
  }
  auto obs = engine_.GetObservation(player);
  std::copy(obs.begin(), obs.end(), values.begin());
}

void KoikoiState::ObservationTensor(Player player,
                                    absl::Span<float> values) const {
  InformationStateTensor(player, values);
}

std::unique_ptr<State> KoikoiState::Clone() const {
  return std::make_unique<KoikoiState>(*this);
}

}  // namespace koikoi
}  // namespace open_spiel
