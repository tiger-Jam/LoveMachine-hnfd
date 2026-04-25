// koikoi.h — OpenSpiel Game/State wrapper for Koi-Koi
//
// 既存の C++ KoikoiEngine を `pyspiel::State` のサブクラスとして包み、
// OpenSpiel の CFR / NFSP / Deep CFR から呼び出せるようにする。
//
// チャンスノード設計:
//   - 親 (oya) は GameParameter で固定 (default 0)。学習側が両方の親を
//     回せば均等性は確保される。
//   - 配り 48 ステップを逐次 chance node として表現。
//     step k: 残り (48-k) 枚から 1 枚選ぶ → スロット k に配置
//     スロット 0..7  → player 0 hand
//     スロット 8..15 → player 1 hand
//     スロット 16..23 → field
//     スロット 24..47 → deck (この順で draw される)
//   - 配り直し (4-of-month in field) は学習簡略化のため**無視**してプレイ続行。
//   - 手四・くっつきは 48 ステップ完了後の terminal として処理 (winner +6 / loser -6)。
//
// アクション空間:
//   - Decision: 0..47 = カード id, 48 = こいこい, 49 = 勝負
//   - Chance:   0..47 = 次に配るカード id

#ifndef OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_H_
#define OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_H_

#include <array>
#include <memory>
#include <string>
#include <vector>

#include "open_spiel/spiel.h"
#include "open_spiel/spiel_globals.h"
#include "open_spiel/spiel_utils.h"

#include "open_spiel/games/koikoi/koikoi_engine.h"

namespace open_spiel {
namespace koikoi {

class KoikoiGame;

class KoikoiState : public State {
 public:
  explicit KoikoiState(std::shared_ptr<const Game> game,
                       const EngineRules& rules,
                       int oya);
  KoikoiState(const KoikoiState& other) = default;

  Player CurrentPlayer() const override;
  std::vector<Action> LegalActions() const override;
  std::vector<std::pair<Action, double>> ChanceOutcomes() const override;
  std::string ActionToString(Player player, Action move) const override;
  std::string ToString() const override;
  bool IsTerminal() const override;
  std::vector<double> Returns() const override;
  std::string InformationStateString(Player player) const override;
  std::string ObservationString(Player player) const override;
  void InformationStateTensor(Player player,
                              absl::Span<float> values) const override;
  void ObservationTensor(Player player,
                         absl::Span<float> values) const override;
  std::unique_ptr<State> Clone() const override;

 protected:
  void DoApplyAction(Action move) override;

 private:
  const KoikoiGame* parent_game_;
  EngineRules rules_;
  int oya_;

  // === 配り進捗 ===
  // 48 ステップ完了後に engine_.ResetWithDeck(...) する。
  std::array<int, 48> deal_perm_{};   // すべて -1 から始まる
  std::array<bool, 48> card_used_{};  // どのカードが配り済か
  int deal_step_ = 0;                 // 0..48

  // === エンジン本体 (deal 完了後にアクティブ) ===
  KoikoiEngine engine_;
  bool engine_ready_ = false;

  // 内部ヘルパ
  bool IsInDealPhase() const { return deal_step_ < 48; }
  void FinalizeDeal();
};

class KoikoiGame : public Game {
 public:
  explicit KoikoiGame(const GameParameters& params);

  int NumDistinctActions() const override { return kNumActions; }
  std::unique_ptr<State> NewInitialState() const override;
  int MaxChanceOutcomes() const override { return kNumCards; }
  int NumPlayers() const override { return 2; }
  // 倍率最大: 五光 15 × 7+ 2 × こいこい 2 = 60。安全マージン込み。
  double MinUtility() const override { return -60.0; }
  double MaxUtility() const override { return  60.0; }
  absl::optional<double> UtilitySum() const override { return 0.0; }
  std::vector<int> InformationStateTensorShape() const override {
    return {kObsSize};
  }
  std::vector<int> ObservationTensorShape() const override {
    return {kObsSize};
  }
  // 1 ラウンドの最大アクション数:
  //   配り 48 + プレイ ~16 ターン × 平均 3 イベント (play+match+draw_match)
  //   + こいこい判断数回。安全に大きめ。
  int MaxGameLength() const override { return 200; }
  int MaxChanceNodesInHistory() const override { return 48; }

  EngineRules rules() const { return rules_; }
  int oya() const { return oya_; }

 private:
  EngineRules rules_;
  int oya_;
};

}  // namespace koikoi
}  // namespace open_spiel

#endif  // OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_H_
