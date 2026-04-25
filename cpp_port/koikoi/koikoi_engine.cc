// koikoi_engine.cc — engine.py::KoikoiEngine の C++ 実装

#include "open_spiel/games/koikoi/koikoi_engine.h"

#include <algorithm>
#include <cassert>
#include <numeric>
#include <unordered_map>

namespace open_spiel {
namespace koikoi {

namespace {

// engine.py: total_yaku_points(check_yaku(captured, rules))
int CapturedTotalPoints(const std::vector<int>& captured,
                        const YakuRules& yaku_rules) {
  CardMask m = 0;
  for (int id : captured) m |= kBit(id);
  return TotalYakuPointsFast(m, yaku_rules);
}

// 取り札 (id list) → bitmask
CardMask ToMask(const std::vector<int>& cards) {
  CardMask m = 0;
  for (int id : cards) m |= kBit(id);
  return m;
}

}  // namespace

KoikoiEngine::KoikoiEngine(const EngineRules& rules) : rules_(rules) {}

void KoikoiEngine::RemoveFromVector(std::vector<int>* v, int card_id) const {
  // engine.py の hand.remove(card) や field.remove(c) と同じく、最初の出現を削除。
  for (auto it = v->begin(); it != v->end(); ++it) {
    if (*it == card_id) { v->erase(it); return; }
  }
}

std::vector<int> KoikoiEngine::FieldMatchesByMonth(int month) const {
  std::vector<int> matches;
  for (int id : field_) {
    if (Card(id).month == month) matches.push_back(id);
  }
  return matches;
}

// ============================================================
// Reset / 特殊配り
// ============================================================

SpecialDealInfo KoikoiEngine::Reset(int oya, uint64_t seed) {
  // engine.py: random.Random(seed).shuffle(cards) と挙動が異なる
  // (Python の Mersenne Twister の状態と一致させるのは大変なので、
  //  このメソッドはバイト一致テストには使わない。
  //  クロス検証は ResetWithDeck() で行う。)
  std::array<int, 48> deck_order;
  std::iota(deck_order.begin(), deck_order.end(), 0);
  std::mt19937_64 rng(seed);
  // Fisher-Yates (Python の random.shuffle と同じアルゴリズム、ただし
  // Python の random.random() とは値が違うので順列も別物)
  for (int i = 47; i > 0; --i) {
    std::uniform_int_distribution<int> dist(0, i);
    std::swap(deck_order[i], deck_order[dist(rng)]);
  }
  return ResetWithDeck(oya, deck_order);
}

SpecialDealInfo KoikoiEngine::ResetWithDeck(
    int oya, const std::array<int, 48>& deck_order) {
  players_hand_[0].assign(deck_order.begin() + 0,  deck_order.begin() + 8);
  players_hand_[1].assign(deck_order.begin() + 8,  deck_order.begin() + 16);
  field_       .assign(deck_order.begin() + 16, deck_order.begin() + 24);
  deck_        .assign(deck_order.begin() + 24, deck_order.end());

  players_captured_[0].clear();
  players_captured_[1].clear();
  players_koikoi_ = {false, false};
  players_prev_yaku_ = {0, 0};
  first_koikoi_player_ = -1;
  last_koikoi_player_ = -1;
  current_player_ = oya;
  oya_index_ = oya;
  phase_ = Phase::kHandPlay;
  done_ = false;
  winner_ = -1;
  win_score_ = 0;
  ryuukyoku_ = false;
  ryuukyoku_oya_swap_ = false;
  pending_played_ = -1;
  pending_matches_.clear();

  return CheckSpecialDeal();
}

SpecialDealInfo KoikoiEngine::CheckSpecialDeal() {
  // engine.py::_check_special_deal
  // 場札の同月4枚 → redeal
  std::array<int, 13> field_month{};
  for (int id : field_) field_month[Card(id).month]++;
  for (int m = 1; m <= 12; ++m) {
    if (field_month[m] == 4) return {SpecialDealInfo::Kind::kRedeal, -1};
  }

  // 各プレイヤーの手札について手四 / くっつき判定 (engine.py 順)
  for (int pi = 0; pi < 2; ++pi) {
    std::array<int, 13> hand_month{};
    for (int id : players_hand_[pi]) hand_month[Card(id).month]++;

    // 手四: いずれかの月が 4 枚
    bool teshi = false;
    for (int m = 1; m <= 12; ++m) {
      if (hand_month[m] == 4) { teshi = true; break; }
    }
    if (teshi) {
      done_ = true;
      phase_ = Phase::kDone;
      winner_ = pi;
      win_score_ = 6;
      return {SpecialDealInfo::Kind::kTeshi, pi};
    }

    // くっつき: 4 種の月がそれぞれ 2 枚ずつ
    int month_kinds = 0;
    bool all_pairs = true;
    for (int m = 1; m <= 12; ++m) {
      if (hand_month[m] > 0) ++month_kinds;
      if (hand_month[m] != 0 && hand_month[m] != 2) { all_pairs = false; }
    }
    if (all_pairs && month_kinds == 4) {
      done_ = true;
      phase_ = Phase::kDone;
      winner_ = pi;
      win_score_ = 6;
      return {SpecialDealInfo::Kind::kKuttsuki, pi};
    }
  }
  return {SpecialDealInfo::Kind::kNone, -1};
}

// ============================================================
// 合法手 / step
// ============================================================

std::vector<int> KoikoiEngine::GetLegalActions() const {
  if (phase_ == Phase::kHandPlay) {
    return players_hand_[current_player_];
  }
  if (phase_ == Phase::kHandMatch || phase_ == Phase::kDrawMatch) {
    return pending_matches_;
  }
  if (phase_ == Phase::kKoikoi) {
    return {kActionKoikoi, kActionShowdown};
  }
  return {};
}

std::array<bool, kNumActions> KoikoiEngine::GetActionMask() const {
  std::array<bool, kNumActions> mask{};
  for (int a : GetLegalActions()) mask[a] = true;
  return mask;
}

std::vector<EngineEvent> KoikoiEngine::Step(int action) {
  assert(!done_);
  // 合法手チェック (engine.py: assert action in legal)
  bool found = false;
  for (int a : GetLegalActions()) if (a == action) { found = true; break; }
  assert(found);

  std::vector<EngineEvent> events;
  switch (phase_) {
    case Phase::kHandPlay:
      StepHandPlay(action, &events); break;
    case Phase::kHandMatch:
      StepMatch(action, &events, /*from_draw=*/false); break;
    case Phase::kDrawMatch:
      StepMatch(action, &events, /*from_draw=*/true); break;
    case Phase::kKoikoi:
      StepKoikoi(action, &events); break;
    case Phase::kDone:
      break;
  }
  return events;
}

void KoikoiEngine::StepHandPlay(int card_id, std::vector<EngineEvent>* info) {
  RemoveFromVector(&players_hand_[current_player_], card_id);
  const int month = Card(card_id).month;
  std::vector<int> matches = FieldMatchesByMonth(month);

  if (matches.empty()) {
    field_.push_back(card_id);
    EngineEvent e;
    e.type = EngineEvent::Type::kHandNoMatch;
    e.card_id = card_id;
    info->push_back(std::move(e));
    ProceedToDraw(info);
  } else if (matches.size() == 1) {
    RemoveFromVector(&field_, matches[0]);
    players_captured_[current_player_].push_back(card_id);
    players_captured_[current_player_].push_back(matches[0]);
    EngineEvent e;
    e.type = EngineEvent::Type::kHandMatch;
    e.card_id = card_id;
    e.matched_id = matches[0];
    info->push_back(std::move(e));
    ProceedToDraw(info);
  } else if (matches.size() == 3) {
    for (int m : matches) RemoveFromVector(&field_, m);
    players_captured_[current_player_].push_back(card_id);
    for (int m : matches) players_captured_[current_player_].push_back(m);
    EngineEvent e;
    e.type = EngineEvent::Type::kHandMatchAll;
    e.card_id = card_id;
    e.matched_ids = matches;
    info->push_back(std::move(e));
    ProceedToDraw(info);
  } else {
    // matches.size() == 2 → ユーザ選択待ち
    pending_played_ = card_id;
    pending_matches_ = matches;
    phase_ = Phase::kHandMatch;
    EngineEvent e;
    e.type = EngineEvent::Type::kHandChoose;
    e.card_id = card_id;
    e.matched_ids = matches;
    info->push_back(std::move(e));
  }
}

void KoikoiEngine::StepMatch(int card_id, std::vector<EngineEvent>* info,
                             bool from_draw) {
  const int played = pending_played_;
  RemoveFromVector(&field_, card_id);
  players_captured_[current_player_].push_back(played);
  players_captured_[current_player_].push_back(card_id);
  pending_played_ = -1;
  pending_matches_.clear();

  if (from_draw) {
    CheckYakuAndAdvance(info);
  } else {
    ProceedToDraw(info);
  }
}

void KoikoiEngine::ProceedToDraw(std::vector<EngineEvent>* info) {
  if (deck_.empty()) {
    CheckYakuAndAdvance(info);
    return;
  }
  const int drawn = deck_.front();
  deck_.erase(deck_.begin());

  EngineEvent draw_ev;
  draw_ev.type = EngineEvent::Type::kDraw;
  draw_ev.card_id = drawn;
  info->push_back(std::move(draw_ev));

  std::vector<int> matches = FieldMatchesByMonth(Card(drawn).month);
  if (matches.empty()) {
    field_.push_back(drawn);
    CheckYakuAndAdvance(info);
  } else if (matches.size() == 1) {
    RemoveFromVector(&field_, matches[0]);
    players_captured_[current_player_].push_back(drawn);
    players_captured_[current_player_].push_back(matches[0]);
    EngineEvent e;
    e.type = EngineEvent::Type::kDrawMatch;
    e.card_id = drawn;
    e.matched_id = matches[0];
    info->push_back(std::move(e));
    CheckYakuAndAdvance(info);
  } else if (matches.size() == 3) {
    for (int m : matches) RemoveFromVector(&field_, m);
    players_captured_[current_player_].push_back(drawn);
    for (int m : matches) players_captured_[current_player_].push_back(m);
    EngineEvent e;
    e.type = EngineEvent::Type::kDrawMatchAll;
    e.card_id = drawn;
    e.matched_ids = matches;
    info->push_back(std::move(e));
    CheckYakuAndAdvance(info);
  } else {
    pending_played_ = drawn;
    pending_matches_ = matches;
    phase_ = Phase::kDrawMatch;
    EngineEvent e;
    e.type = EngineEvent::Type::kDrawChoose;
    e.card_id = drawn;
    e.matched_ids = matches;
    info->push_back(std::move(e));
  }
}

void KoikoiEngine::CheckYakuAndAdvance(std::vector<EngineEvent>* info) {
  const int cp = current_player_;
  const auto yaku_rules = rules_.ToYakuRules();
  std::vector<YakuInstance> yaku =
      CheckYaku(ToMask(players_captured_[cp]), yaku_rules);
  const int pts = TotalYakuPoints(yaku);

  if (pts > players_prev_yaku_[cp] && pts > 0) {
    EngineEvent e;
    e.type = EngineEvent::Type::kYakuFormed;
    e.player = cp;
    e.yaku = yaku;
    e.points = pts;
    info->push_back(std::move(e));
    phase_ = Phase::kKoikoi;
  } else {
    NextTurn(info);
  }
}

void KoikoiEngine::StepKoikoi(int action, std::vector<EngineEvent>* info) {
  const int cp = current_player_;
  const auto yaku_rules = rules_.ToYakuRules();
  std::vector<YakuInstance> yaku =
      CheckYaku(ToMask(players_captured_[cp]), yaku_rules);
  const int pts = TotalYakuPoints(yaku);

  if (action == kActionShowdown) {
    EngineEvent e;
    e.type = EngineEvent::Type::kShowdown;
    e.player = cp;
    e.points = pts;
    info->push_back(std::move(e));
    EndRound(cp, pts, info);
  } else {
    EngineEvent e;
    e.type = EngineEvent::Type::kKoikoi;
    e.player = cp;
    info->push_back(std::move(e));
    players_koikoi_[cp] = true;
    players_prev_yaku_[cp] = pts;
    if (first_koikoi_player_ == -1) first_koikoi_player_ = cp;
    last_koikoi_player_ = cp;
    NextTurn(info);
  }
}

void KoikoiEngine::NextTurn(std::vector<EngineEvent>* info) {
  if (players_hand_[0].empty() && players_hand_[1].empty()) {
    EndRoundExhausted(info);
    return;
  }
  current_player_ = 1 - current_player_;
  phase_ = Phase::kHandPlay;
}

void KoikoiEngine::EndRound(int winner, int pts,
                            std::vector<EngineEvent>* info) {
  const int loser = 1 - winner;
  if (rules_.seven_plus_double && pts >= 7) {
    pts *= 2;
    EngineEvent e; e.type = EngineEvent::Type::kBonus7Plus;
    info->push_back(std::move(e));
  }
  if (rules_.koikoi_double && players_koikoi_[loser]) {
    pts *= 2;
    EngineEvent e; e.type = EngineEvent::Type::kBonusOpponentKoikoi;
    info->push_back(std::move(e));
  }
  done_ = true;
  phase_ = Phase::kDone;
  winner_ = winner;
  win_score_ = pts;

  EngineEvent e;
  e.type = EngineEvent::Type::kRoundEnd;
  e.winner = winner;
  e.points = pts;
  info->push_back(std::move(e));
}

void KoikoiEngine::EndRoundExhausted(std::vector<EngineEvent>* info) {
  EngineEvent ex;
  ex.type = EngineEvent::Type::kExhausted;
  info->push_back(std::move(ex));
  done_ = true;
  phase_ = Phase::kDone;

  const int n_koikoi =
      static_cast<int>(players_koikoi_[0]) + static_cast<int>(players_koikoi_[1]);

  const auto yaku_rules = rules_.ToYakuRules();

  if (n_koikoi == 0) {
    ryuukyoku_ = true;
    switch (rules_.ryuukyoku) {
      case RyuukyokuRule::kChange:
        winner_ = -1; win_score_ = 0; ryuukyoku_oya_swap_ = true; break;
      case RyuukyokuRule::kNoChange:
        winner_ = -1; win_score_ = 0; break;
      case RyuukyokuRule::kOyaken:
        winner_ = oya_index_; win_score_ = 6; break;
    }
  } else if (n_koikoi == 1) {
    const int w = players_koikoi_[0] ? 0 : 1;
    winner_ = w;
    win_score_ = CapturedTotalPoints(players_captured_[w], yaku_rules);
  } else {
    auto by_player = [&](int w) {
      winner_ = w;
      win_score_ = CapturedTotalPoints(players_captured_[w], yaku_rules);
    };
    switch (rules_.multi_koikoi) {
      case MultiKoikoiRule::kLastKoikoi:
        if (last_koikoi_player_ != -1) by_player(last_koikoi_player_);
        else { winner_ = oya_index_; win_score_ = 6; }
        break;
      case MultiKoikoiRule::kFirstKoikoi:
        if (first_koikoi_player_ != -1) by_player(first_koikoi_player_);
        else { winner_ = oya_index_; win_score_ = 6; }
        break;
      case MultiKoikoiRule::kOyaken:
        winner_ = oya_index_; win_score_ = 6; break;
    }
  }
}

// ============================================================
// 観測 (340 次元)
// ============================================================

std::array<float, 11> KoikoiEngine::ComputeYakuProgress(
    const std::vector<int>& captured) const {
  // engine.py::_compute_yaku_progress を完全再現
  std::array<float, 11> p{};
  CardMask mask = ToMask(captured);
  CardMask hikari = mask & kHikariMask;
  CardMask tane = mask & kTaneMask;
  CardMask tanzaku = mask & kTanzakuMask;
  CardMask kasu = mask & kKasuMask;

  const int n_hikari = PopCount(hikari);
  const int n_tane = PopCount(tane);
  const int n_tanzaku = PopCount(tanzaku);
  const int n_kasu = PopCount(kasu);
  const bool has_yanagi = (hikari & kYanagiHikariBit) != 0;
  const int non_rain = n_hikari - (has_yanagi ? 1 : 0);

  p[0] = n_hikari / 5.0f;            // 五光
  p[1] = non_rain / 4.0f;            // 四光
  p[2] = std::min(non_rain / 3.0f, 1.0f);  // 三光
  const int n_akatan = PopCount(tanzaku & kAkatanMask);
  const int n_aotan  = PopCount(tanzaku & kAotanMask);
  p[3] = n_akatan / 3.0f;            // 赤短
  p[4] = n_aotan  / 3.0f;            // 青短
  p[5] = std::min(n_tanzaku / 5.0f, 1.0f);  // たん

  const bool has_ino   = (mask & kBit(kIdHagiIno))     != 0;
  const bool has_shika = (mask & kBit(kIdMomijiShika)) != 0;
  const bool has_chou  = (mask & kBit(kIdBotanChou))   != 0;
  p[6] = (static_cast<int>(has_ino) + static_cast<int>(has_shika)
          + static_cast<int>(has_chou)) / 3.0f;

  p[7] = std::min(n_tane / 5.0f, 1.0f);    // たね
  p[8] = std::min(n_kasu / 10.0f, 1.0f);   // カス

  const bool has_maku  = (mask & kBit(kIdSakuraMaku))    != 0;
  const bool has_tsuki = (mask & kBit(kIdSusukiTsuki))   != 0;
  const bool has_sakaz = (mask & kBit(kIdKikuSakazuki))  != 0;
  p[9]  = (static_cast<int>(has_maku)  + static_cast<int>(has_sakaz)) / 2.0f;
  p[10] = (static_cast<int>(has_tsuki) + static_cast<int>(has_sakaz)) / 2.0f;
  return p;
}

std::array<float, kObsSize> KoikoiEngine::GetObservation(int player_idx) const {
  std::array<float, kObsSize> obs{};
  const int opp = 1 - player_idx;

  // [0:48] 自分の手札
  for (int id : players_hand_[player_idx]) obs[id] = 1.0f;
  // [48:96] 場札
  for (int id : field_) obs[48 + id] = 1.0f;
  // [96:144] 自分の取り札
  for (int id : players_captured_[player_idx]) obs[96 + id] = 1.0f;
  // [144:192] 相手の取り札
  for (int id : players_captured_[opp]) obs[144 + id] = 1.0f;

  // [192:240] 未確認カード
  std::array<bool, kNumCards> visible{};
  for (int id : players_hand_[player_idx]) visible[id] = true;
  for (int id : field_) visible[id] = true;
  for (int id : players_captured_[player_idx]) visible[id] = true;
  for (int id : players_captured_[opp]) visible[id] = true;
  for (int i = 0; i < kNumCards; ++i) {
    if (!visible[i]) obs[192 + i] = 1.0f;
  }

  // [240:244] phase one-hot (engine.py: HAND_PLAY=0, HAND_MATCH=1, DRAW_MATCH=2, KOIKOI=3)
  switch (phase_) {
    case Phase::kHandPlay:  obs[240] = 1.0f; break;
    case Phase::kHandMatch: obs[241] = 1.0f; break;
    case Phase::kDrawMatch: obs[242] = 1.0f; break;
    case Phase::kKoikoi:    obs[243] = 1.0f; break;
    case Phase::kDone:      break;
  }

  obs[244] = (player_idx == oya_index_) ? 1.0f : 0.0f;
  obs[245] = players_koikoi_[player_idx] ? 1.0f : 0.0f;
  obs[246] = players_koikoi_[opp]        ? 1.0f : 0.0f;

  const auto yaku_rules = rules_.ToYakuRules();
  const int my_pts  = CapturedTotalPoints(players_captured_[player_idx], yaku_rules);
  const int opp_pts = CapturedTotalPoints(players_captured_[opp], yaku_rules);
  obs[247] = std::min(my_pts  / 15.0f, 1.0f);
  obs[248] = std::min(opp_pts / 15.0f, 1.0f);
  obs[249] = deck_.size() / 24.0f;

  // [250:298] pending_played one-hot
  if (pending_played_ != -1) obs[250 + pending_played_] = 1.0f;

  // [298:309] / [309:320] yaku progress
  auto my_prog  = ComputeYakuProgress(players_captured_[player_idx]);
  auto opp_prog = ComputeYakuProgress(players_captured_[opp]);
  for (int i = 0; i < 11; ++i) {
    obs[298 + i] = my_prog[i];
    obs[309 + i] = opp_prog[i];
  }

  // [320:332] 月別未確認比 (4 枚で正規化)
  std::array<int, 13> unseen_per_month{};
  for (int i = 0; i < kNumCards; ++i) {
    if (!visible[i]) unseen_per_month[Card(i).month]++;
  }
  for (int month = 1; month <= 12; ++month) {
    obs[320 + month - 1] = unseen_per_month[month] / 4.0f;
  }

  // [332:340] 取り札種別カウント
  // engine.py の type_norms: HIKARI=5, TANE=9, TANZAKU=10, KASU=24
  auto count_type = [](const std::vector<int>& cap, CardType t) {
    int n = 0;
    for (int id : cap) if (Card(id).type == t) ++n;
    return n;
  };
  const float norms[4] = {5.0f, 9.0f, 10.0f, 24.0f};
  const CardType types[4] = {
      CardType::kHikari, CardType::kTane, CardType::kTanzaku, CardType::kKasu};
  for (int i = 0; i < 4; ++i) {
    obs[332 + i] = count_type(players_captured_[player_idx], types[i]) / norms[i];
    obs[336 + i] = count_type(players_captured_[opp],         types[i]) / norms[i];
  }

  return obs;
}

}  // namespace koikoi
}  // namespace open_spiel
