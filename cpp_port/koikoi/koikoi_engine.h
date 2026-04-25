// koikoi_engine.h — 花札こいこい1ラウンド分のステートマシン
//
// engine.py::KoikoiEngine と完全に同じ振る舞いをする C++ 実装。
// I/O は持たない。step() ベースで外部からアクションを受け取り、
// 次の決定ポイントまで自動進行する。

#ifndef OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_ENGINE_H_
#define OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_ENGINE_H_

#include <array>
#include <cstdint>
#include <optional>
#include <random>
#include <string>
#include <variant>
#include <vector>

#include "open_spiel/games/koikoi/koikoi_cards.h"
#include "open_spiel/games/koikoi/koikoi_yaku.h"

namespace open_spiel {
namespace koikoi {

// engine.py::Phase と一致
enum class Phase : uint8_t {
  kHandPlay = 0,
  kHandMatch = 1,
  kDrawMatch = 2,
  kKoikoi = 3,
  kDone = 4,
};

// engine.py::ACTION_KOIKOI / ACTION_SHOWDOWN
inline constexpr int kActionKoikoi = 48;
inline constexpr int kActionShowdown = 49;
inline constexpr int kNumActions = 50;

// engine.py::OBS_SIZE
inline constexpr int kObsSize = 340;

// 複数こいこい時のローカルルール
enum class MultiKoikoiRule : uint8_t {
  kOyaken = 0,        // 親が 6 点で勝ち
  kLastKoikoi = 1,    // 最後にこいこい宣言した人が素点で勝ち
  kFirstKoikoi = 2,   // 最初にこいこい宣言した人が素点で勝ち
};

// 流局時 (誰もこいこいしてない) のローカルルール
enum class RyuukyokuRule : uint8_t {
  kOyaken = 0,        // 親が 6 点で勝ち
  kNoChange = 1,      // 0 点・親そのまま
  kChange = 2,        // 0 点・親交代
};

struct EngineRules {
  bool koikoi_double = true;
  bool seven_plus_double = false;
  bool hanami = true;
  bool tsukimi = true;
  MultiKoikoiRule multi_koikoi = MultiKoikoiRule::kLastKoikoi;
  RyuukyokuRule ryuukyoku = RyuukyokuRule::kNoChange;

  // YakuRules は hanami / tsukimi のみ参照
  YakuRules ToYakuRules() const { return YakuRules{hanami, tsukimi}; }
};

// engine.py の info["events"] に対応するタグ付き union
// Python タプル `("hand_no_match", card_id)` 等を 1 対 1 に表現する。
struct EngineEvent {
  enum class Type : uint8_t {
    kHandNoMatch,        // (card_id)
    kHandMatch,          // (card_id, matched_id)
    kHandMatchAll,       // (card_id, [matched_ids])
    kHandChoose,         // (card_id, [match_ids])
    kDraw,               // (card_id)
    kDrawMatch,          // (card_id, matched_id)
    kDrawMatchAll,       // (card_id, [matched_ids])
    kDrawChoose,         // (card_id, [match_ids])
    kYakuFormed,         // (player, [(name, pts)], total_pts)
    kShowdown,           // (player, points)
    kKoikoi,             // (player)
    kBonus7Plus,         // ()
    kBonusOpponentKoikoi,// ()
    kRoundEnd,           // (winner, points)
    kExhausted,          // ()
  };

  Type type;
  int player = -1;                       // 関連プレイヤー (該当時)
  int card_id = -1;                      // 主カード
  int matched_id = -1;                   // 単一マッチ
  std::vector<int> matched_ids;          // 複数マッチ
  std::vector<YakuInstance> yaku;        // yaku_formed 時
  int points = 0;                        // showdown / round_end / yaku_formed の点
  int winner = -1;                       // round_end 時
};

// 特殊配り情報 (Reset の戻り値)
struct SpecialDealInfo {
  enum class Kind : uint8_t {
    kNone = 0,
    kRedeal = 1,        // 場に同月4枚 → 配り直し要求
    kTeshi = 2,         // 手四 (どちらかが)
    kKuttsuki = 3,      // くっつき (どちらかが)
  };
  Kind kind = Kind::kNone;
  int player = -1;      // teshi / kuttsuki の場合の対象プレイヤー
};

class KoikoiEngine {
 public:
  explicit KoikoiEngine(const EngineRules& rules = {});

  // engine.py::reset(oya, seed) と一致。
  // seed 由来の shuffle は Python と完全には一致しない（Mersenne Twister の
  // C++/Python 実装差異あり）。byte-parity テストには ResetWithDeck を使う。
  SpecialDealInfo Reset(int oya, uint64_t seed);

  // 検証用: 後の shuffle 結果（48 枚順列）を直接渡す。
  // engine.py の `cards = list(_master_deck); rng.shuffle(cards);` 後の状態を
  // 外部から指定するイメージ。deck_order[0..7] = player 0 hand,
  // [8..15] = player 1 hand, [16..23] = field, [24..47] = deck order。
  SpecialDealInfo ResetWithDeck(int oya, const std::array<int, 48>& deck_order);

  // engine.py::get_legal_actions と一致 (sorted ではない、順序も同じ)
  std::vector<int> GetLegalActions() const;

  // engine.py::step(action) と一致。events を返す。
  std::vector<EngineEvent> Step(int action);

  // 観測 (340 次元)。engine.py::get_observation と完全一致。
  std::array<float, kObsSize> GetObservation(int player_idx) const;

  // 50 ビットマスク
  std::array<bool, kNumActions> GetActionMask() const;

  // ===== 状態クエリ =====
  Phase phase() const { return phase_; }
  int current_player() const { return current_player_; }
  int oya_index() const { return oya_index_; }
  bool done() const { return done_; }
  int winner() const { return winner_; }
  int win_score() const { return win_score_; }
  bool ryuukyoku() const { return ryuukyoku_; }
  bool ryuukyoku_oya_swap() const { return ryuukyoku_oya_swap_; }
  const std::vector<int>& players_hand(int p) const { return players_hand_[p]; }
  const std::vector<int>& players_captured(int p) const { return players_captured_[p]; }
  bool players_koikoi(int p) const { return players_koikoi_[p]; }
  int players_prev_yaku(int p) const { return players_prev_yaku_[p]; }
  int first_koikoi_player() const { return first_koikoi_player_; }
  int last_koikoi_player() const { return last_koikoi_player_; }
  const std::vector<int>& field() const { return field_; }
  const std::vector<int>& deck() const { return deck_; }
  int pending_played() const { return pending_played_; }
  const std::vector<int>& pending_matches() const { return pending_matches_; }
  const EngineRules& rules() const { return rules_; }

 private:
  // === 内部状態 (engine.py の属性と一対一) ===
  EngineRules rules_;
  std::array<std::vector<int>, 2> players_hand_;
  std::array<std::vector<int>, 2> players_captured_;
  std::array<bool, 2> players_koikoi_{false, false};
  std::array<int, 2> players_prev_yaku_{0, 0};
  int first_koikoi_player_ = -1;
  int last_koikoi_player_ = -1;
  std::vector<int> field_;
  std::vector<int> deck_;
  int current_player_ = 0;
  int oya_index_ = 0;
  Phase phase_ = Phase::kHandPlay;
  bool done_ = false;
  int winner_ = -1;       // -1 = None
  int win_score_ = 0;
  bool ryuukyoku_ = false;
  bool ryuukyoku_oya_swap_ = false;
  int pending_played_ = -1;
  std::vector<int> pending_matches_;

  // === 内部ヘルパ ===
  void StepHandPlay(int card_id, std::vector<EngineEvent>* info);
  void StepMatch(int card_id, std::vector<EngineEvent>* info, bool from_draw);
  void StepKoikoi(int action, std::vector<EngineEvent>* info);
  void ProceedToDraw(std::vector<EngineEvent>* info);
  void CheckYakuAndAdvance(std::vector<EngineEvent>* info);
  void NextTurn(std::vector<EngineEvent>* info);
  void EndRound(int winner, int pts, std::vector<EngineEvent>* info);
  void EndRoundExhausted(std::vector<EngineEvent>* info);
  SpecialDealInfo CheckSpecialDeal();

  // 場札からカード id 同月のものを抽出 (engine.py: [c for c in self.field if c.month == card.month])
  std::vector<int> FieldMatchesByMonth(int month) const;
  void RemoveFromVector(std::vector<int>* v, int card_id) const;

  // 観測ヘルパ
  std::array<float, 11> ComputeYakuProgress(const std::vector<int>& captured) const;
};

}  // namespace koikoi
}  // namespace open_spiel

#endif  // OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_ENGINE_H_
