# engine.py → C++ OpenSpiel 完全再現ポート 設計書

## 0. 要旨

`engine.py` + `core.py`（合計 709 行）を C++ で完全再現し、OpenSpiel の `Game` / `State` サブクラスとして登録する。Python binding は OpenSpiel の `pyspiel` ビルドで自動生成される。目的は **NFSP / Deep CFR 等の imperfect-info 学習アルゴリズムを Python で高速に回す**こと。研究調査 (`NASH_RESEARCH.md`) で判明した「Python 実装ゲームは C++ より 4-350 倍遅い」を回避する。

## 1. スコープと原則

### 1.1 「完全再現」の定義

- **振る舞い等価**: 同一シードで `engine.py` と C++ 実装が
  - 初期配布（手札 8/8、場 8、山 24）
  - 全ての step 後の合法手
  - 全ての yaku 判定
  - 倍率適用（7点以上 × こいこい × 複数こいこい × 流局ローカルルール）
  - `winner` と `win_score`
  を **完全一致**させる。

- **観測ベクトル等価**: `get_observation(player_idx)` の 340 次元 float32 が `engine.py` のそれと **浮動小数の表現誤差を除いて一致**。

- **非目標**: `rule_based_policy` の C++ 移植は **やらない**。Python 側で OpenSpiel 経由で state を読んで行動選ぶだけでよい。ベンチマークにも影響しない。

### 1.2 ポート対象・非対象

| ファイル | 対象 | 備考 |
|---|---|---|
| `core.py` | ✅ | 48 枚カードデータ、`check_yaku`, `total_yaku_points` |
| `engine.py` | ✅ | `KoikoiEngine` クラス全体、`Phase`, 定数 |
| `env.py` | ❌ | Gym wrapper は Python のまま（OpenSpiel が env 相当） |
| `hanafuda.py` | ❌ | Legacy console 版、game logic として不要 |
| `web.py`, `static/` | ❌ | Web UI は引き続き Python engine を使う |
| `train.py` | ❌ | 既存 PPO 用、Nash 学習とは別系統 |

## 2. OpenSpiel 統合方針

### 2.1 統合方式

OpenSpiel を `vendor/open_spiel/` にサブモジュール化（shallow clone 済）し、**in-tree で** `vendor/open_spiel/open_spiel/games/koikoi/` にコードを配置する。OpenSpiel の CMake ビルドに組み込まれ、`pyspiel` に含まれる。

### 2.2 ファイル構成

```
vendor/open_spiel/open_spiel/games/koikoi/
  koikoi.h              # Game / State 宣言
  koikoi.cc             # 実装本体
  koikoi_cards.h        # カードデータ (enum + 静的配列)
  koikoi_yaku.h         # 役定義
  koikoi_yaku.cc        # check_yaku 実装
  koikoi_observation.h  # 340 次元観測ビルダー
  koikoi_observation.cc
  koikoi_test.cc        # C++ 単体テスト
  CMakeLists.txt        # OpenSpiel の game_list に追加
```

プロジェクトルートから見た追加ファイル：

```
cpp/
  validate.py           # engine.py vs C++ のクロス検証スクリプト
  benchmark.py          # スループット計測
```

### 2.3 チャンスノード設計

**採用: Approach B** — デッキを multiset として扱い、各 draw は chance node。

理由：
- OpenSpiel の慣習的パターン（poker, gin_rummy と同じ）
- CFR が chance outcome を enumerate / sample しやすい
- 初期配布も 8+8+8 を sequential chance で分解可能

**ゲームフロー (OpenSpiel 視点)**:

```
ROOT
├─ ChanceNode[deal_0]      24 枚目まで chance で公開:
│   → 48 通り → player 0 の 1 枚目                 8 枚 → player 0 hand
├─ ChanceNode[deal_1]                              8 枚 → player 1 hand
│   → 47 通り → player 0 の 2 枚目                 8 枚 → field
...                                                24 枚 → deck (multiset)
├─ ChanceNode[deal_24]  (field 最後)
│   → 25 通り → field の最後
│
├─ (特殊配布判定: 4-in-field → ゲーム中止で再開 or game rejected)
│   (手四 / くっつき → 即終局 6 点)
│
├─ PlayerNode[oya]  ← HAND_PLAY
│   legal actions: 手札カード id 集合 (最大 8)
│   apply → HAND_MATCH (if matches==2) か、直接 Draw
├─ ChanceNode[draw]     (deck multiset から 1 枚)
│   → remaining deck size 通り
├─ (2-match → PlayerNode[DRAW_MATCH])
├─ (役成立 → PlayerNode[KOIKOI])  ← action: 48=koikoi / 49=showdown
├─ 手札両切れ → TerminalNode (exhausted rule 適用)
└─ 勝負宣言 → TerminalNode
```

### 2.4 Chance mode

OpenSpiel の `ChanceMode`：

- `kExplicitStochastic`: chance outcome を全列挙 + 確率。初期 48 枚デッキで 48 分岐までは現実的。
- `kSampledStochastic`: chance をサンプルのみ。CFR では推奨。

**採用: `kExplicitStochastic`**。各 deal/draw の分岐数は最大 48（減っていく）で、多くても数十。CFR の chance traversal で enumerate 可能。exploitability 計算にも有利。

### 2.5 Utility (zero-sum)

`engine.py` の `win_score` (0〜30) を 2 プレイヤー zero-sum に変換：
- winner が winner_idx、`win_score = W` → utility[winner_idx] = +W, utility[loser_idx] = -W
- 流局 winner=None → utility[0] = utility[1] = 0
- 親権勝ち（oyaken ルール、W=6）→ utility[oya_idx] = +6, utility[other] = -6

`GameType::utility = kZeroSum`, `max_utility = 30.0` (五光 + 倍率)、`min_utility = -30.0`。

## 3. 状態機械（C++ 側）

### 3.1 Phase enum

`Phase::kHandPlay`, `kHandMatch`, `kDrawMatch`, `kKoikoi`, `kDone`, **新規** `kChanceDeal`, `kChanceDraw`。

### 3.2 内部状態フィールド

`engine.py` の属性と一対一対応：

```cpp
class KoikoiState : public State {
  // === ゲーム状態 ===
  Phase phase_;
  std::array<std::vector<int>, 2> players_hand_;   // カード id
  std::array<std::vector<int>, 2> players_captured_;
  std::array<bool, 2> players_koikoi_;
  std::array<int, 2> players_prev_yaku_;
  int first_koikoi_player_ = -1;                    // -1 = None
  int last_koikoi_player_ = -1;
  std::vector<int> field_;
  std::vector<int> deck_;                           // ordered (for byte-parity w/ Python)
  int current_player_;
  int oya_index_;
  bool done_ = false;
  int winner_ = kInvalidPlayer;
  int win_score_ = 0;
  bool ryuukyoku_ = false;
  bool ryuukyoku_oya_swap_ = false;
  int pending_played_ = -1;                         // card id
  std::vector<int> pending_matches_;

  // === Deal 進行 (chance phase) ===
  int deal_idx_ = 0;  // 0..23

  // === ルール ===
  const KoikoiRules& rules_;                        // Game から参照
};
```

### 3.3 ルール構造

`engine.py` の `DEFAULT_RULES` を C++ 側で同等に持つ：

```cpp
struct KoikoiRules {
  bool koikoi_double = true;
  bool seven_plus_double = false;
  bool hanami = true;
  bool tsukimi = true;
  enum class MultiKoikoi { kOyaken, kLastKoikoi, kFirstKoikoi };
  MultiKoikoi multi_koikoi = MultiKoikoi::kLastKoikoi;
  enum class Ryuukyoku { kOyaken, kNoChange, kChange };
  Ryuukyoku ryuukyoku = Ryuukyoku::kNoChange;
};
```

OpenSpiel のゲームパラメータ経由で上書き可 (`GameType::parameter_specification`)。

## 4. カードデータ

### 4.1 `koikoi_cards.h`

```cpp
namespace open_spiel::koikoi {

enum class CardType : uint8_t { kHikari, kTane, kTanzaku, kKasu };
enum class TanzakuType : uint8_t { kNone, kAkatan, kAotan, kMuji };

struct CardInfo {
  uint8_t id;
  uint8_t month;           // 1..12
  const char* name;
  CardType type;
  TanzakuType tanzaku;
};

// core.py::make_deck() と完全一致する 48 枚静的配列。
extern const std::array<CardInfo, 48> kDeck;

inline const CardInfo& Card(int id) { return kDeck[id]; }

// 便利集合 (ビットマスク uint64_t)
constexpr uint64_t kHikariMask = /*松鶴|桜幕|芒月|柳光|桐鳳凰*/;
constexpr uint64_t kTaneMask   = /*...*/;
// etc.

} // namespace
```

カード id は `engine.py` と完全一致（`make_deck()` の追加順）。役判定は 48bit bitmask で高速化。

### 4.2 役判定 `koikoi_yaku.cc`

`check_yaku` を移植：

```cpp
struct Yaku { const char* name; int points; };

std::vector<Yaku> CheckYaku(uint64_t captured_mask, const KoikoiRules& rules);
int TotalYakuPoints(const std::vector<Yaku>& yaku);
```

Python 版と完全一致：
- 光系排他（五光 / 四光 / 雨四光 / 三光）
- 柳光含む3枚以上の扱い（`non_ono >= 3` で三光）
- 短冊 5+: 「たん」= `1 + (n_tanzaku - 5)`
- 種 5+: 「たね」
- カス 10+: 「カス」
- 猪鹿蝶、花見、月見（ルールで on/off）

## 5. 観測ベクトル

### 5.1 OpenSpiel Observer

OpenSpiel の `Observer` API で 340 次元を 2 種類供給：

- `InformationStateTensor(player)`: 完全な観測（CFR の info-set に使う）
- `ObservationTensor(player)`: 観測情報（同じ 340 次元を返す）
- `InformationStateString(player)`: 表形式 CFR 用のキー。48 枚の可視集合 + phase + hand sort を canonical 文字列化。

Python 側の `get_observation` と **完全に同じ順序・同じ正規化**：

```
[  0: 48] my hand           (binary)
[ 48: 96] field             (binary)
[ 96:144] my captured       (binary)
[144:192] opponent captured (binary)
[192:240] unknown cards     (binary)  // not in visible set
[240:244] phase one-hot     (HAND_PLAY/HAND_MATCH/DRAW_MATCH/KOIKOI)
[244]     I am oya
[245]     I declared koikoi
[246]     opp declared koikoi
[247]     my current points / 15
[248]     opp current points / 15
[249]     deck size / 24
[250:298] pending played card (one-hot)
[298:309] my yaku progress (11-dim)
[309:320] opp yaku progress (11-dim)
[320:332] month-wise unseen ratio (12-dim)
[332:336] my captured type counts (hikari/tane/tanzaku/kasu normalized)
[336:340] opp captured type counts
```

### 5.2 InformationStateString の canonical 形式

```
P<idx>|Phase:HAND_PLAY|Hand:0,3,7,12,...|Field:1,5,...|MyCap:...|OppCap:...|DeckN:24|OppHand:8|Koikoi:00|OyaI:0|Pending:-1
```

ソート済み card id list を `,` 区切り。Tabular CFR のハッシュキーとして使える。

## 6. ビルドシステム

### 6.1 OpenSpiel への統合

`vendor/open_spiel/open_spiel/games/CMakeLists.txt` に一行追加：
```cmake
add_subdirectory(koikoi)
```

`koikoi/CMakeLists.txt`:
```cmake
add_library(koikoi OBJECT
  koikoi.cc
  koikoi_yaku.cc
  koikoi_observation.cc
)
target_include_directories(koikoi PRIVATE ${OPEN_SPIEL_ROOT})
add_executable(koikoi_test koikoi_test.cc $<TARGET_OBJECTS:koikoi>)
target_link_libraries(koikoi_test open_spiel_core absl::...)
add_test(NAME koikoi_test COMMAND koikoi_test)
```

### 6.2 pyspiel への登録

`koikoi.cc` の先頭で:
```cpp
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
    {{"koikoi_double", GameParameter(true)},
     {"seven_plus_double", GameParameter(false)},
     {"hanami", GameParameter(true)},
     {"tsukimi", GameParameter(true)},
     {"multi_koikoi", GameParameter(std::string("last_koikoi"))},
     {"ryuukyoku", GameParameter(std::string("no_change"))}}
};

REGISTER_SPIEL_GAME(kGameType, Factory);
}  // namespace
```

### 6.3 ビルド手順

```bash
cd vendor/open_spiel
./install.sh  # 初回のみ (abseil 等の依存を pull)
mkdir build && cd build
cmake -DPython3_EXECUTABLE=$(which python3) ../open_spiel
make -j$(sysctl -n hw.ncpu) koikoi_test pyspiel
ctest --output-on-failure
```

その後：
```bash
export PYTHONPATH=$(pwd):$(pwd)/python:$PYTHONPATH
python -c "import pyspiel; g = pyspiel.load_game('koikoi'); print(g)"
```

## 7. 検証戦略

### 7.1 C++ 単体テスト (`koikoi_test.cc`)

- `open_spiel::testing::RandomSimTest(game, 100)` — ランダムプレイが例外なく完走
- `open_spiel::testing::LegalActionsIsSerializable(game, 100)`
- `open_spiel::testing::ResampleInfostateTest(game, 10)`
- Yaku 判定の既知入力ケース（五光 / 四光 / 雨四光 / 三光 / 猪鹿蝶 / 花見 / 月見 / たね6枚 / たん7枚 / カス12枚）

### 7.2 Python ↔ C++ クロス検証 (`cpp/validate.py`)

```python
# 同一シード S で:
#   1. engine.py の KoikoiEngine.reset(oya, seed=S) + ランダム方策
#   2. pyspiel load_game('koikoi') + 同シード + 同ランダム方策
# を並走させ、各 step 後に以下を一致確認:
#   - 合法手集合
#   - phase
#   - players_hand (sorted)
#   - field (sorted)
#   - players_captured (sorted)
#   - deck 順序
#   - 観測ベクトル (L_inf < 1e-6)
# 最終状態:
#   - winner, win_score
#   - ryuukyoku フラグ
# N=10000 ゲームでパス。
```

**注意**: OpenSpiel は chance node を明示的に消費するため、Python 側の `random.Random(seed)` と C++ 側のシャッフル順が一致するように、C++ 実装でも **初回 chance node の一括シード化**（同じ seed → 同じ 48! 置換）をサポートする。方法：`game.new_initial_state()` の後に `state.apply_action(deal_id)` として 24 連続 chance action を applied chain で与え、deck 順を `engine.py` と一致させる。

### 7.3 性能ベンチ (`cpp/benchmark.py`)

- Python engine: ランダム方策で 1 万ゲーム / 秒
- C++ engine (pyspiel): 同 → 目標 5 万+ ゲーム / 秒（engine.py 比 5x 以上）
- CFR 1 iteration の時間比較

## 8. 実装順序 (Phase 化)

| Phase | 内容 | 推定工数 | 完了条件 | 状態 |
|---|---|---|---|---|
| 0 | OpenSpiel clone + ビルド確認 (kuhn_poker が動く) | 0.5 日 | `python -c "import pyspiel"` 成功 | ✅ done (pip 1.6.3 + source clone) |
| 1 | `koikoi_cards.h` + `koikoi_yaku.cc` + unit test | 1 日 | Python 側 `check_yaku` と 1000 ランダム入力で一致 | ✅ done (10020 ケース PASS) |
| 2-5 | `KoikoiEngine` C++ 実装 (deal / phase 遷移 / koikoi / 流局 / 倍率) | 4-5 日 | engine.py と全 step 一致 | ✅ done (engine_dump で 2000 ゲーム step+events+obs 一致) |
| 6 | 340 次元観測 | 1 日 | Python と一致 | ✅ done (上記に統合済) |
| 7 | クロス検証 (`cpp/validate.py`) | 1 日 | 10000 ゲーム fully identical | ✅ done (`validate_engine.py` 2000 PASS、上限なし) |
| 8 | OpenSpiel `Game`/`State` wrapper + `REGISTER_SPIEL_GAME` | 1 日 | `pyspiel.load_game("koikoi")` で動作 | 未 |
| 9 | pybind11 バインディング (`koikoi_cpp` モジュール) | 1-2 日 | `from koikoi_cpp import KoikoiEngine` | 未 |
| 10 | `engine.py` を `koikoi_cpp` 差し替え + web.py 通し動作 | 0.5 日 | ブラウザ対局正常 | 未 |
| 11 | NFSP smoke test (`open_spiel.python.algorithms.nfsp`) | 0.5 日 | 100 episode で exploitability が下がる | 未 |

合計 **8-9 日** 実装 + 余裕で **10 日**程度。

## 9. リスクと mitigation

| リスク | 影響 | 対策 |
|---|---|---|
| OpenSpiel の M4 native build が失敗 | 全体停止 | 最悪 Docker 内で Linux build → volume mount で開発 |
| Chance node の確率分布再現で Python と非一致 | 検証失敗 | deal を 48 連続 chance action に分解 → シード同期容易 |
| 観測ベクトルの浮動小数誤差 | クロス検証失敗 | 比較閾値 1e-5、かつ整数部のみ比較する path を保険で用意 |
| 役判定の Edge case (雨含む三光など) | 学習が誤収束 | unit test で Python の 1000 個入力から参照解答をダンプ、bit-exact で比較 |
| OpenSpiel のビルドが 30 分以上 | 開発イテレーション遅い | 最初の全ビルド後は `make -j koikoi_test pyspiel` のみ増分ビルド |
| Python engine に将来仕様変更 | ドリフト | `cpp/validate.py` を CI 相当（`Makefile` target）として毎回走らせる |

## 10. 非スコープ・将来拡張

- **Multi-round match (3/6/12 局通しゲーム)**: Phase B 以降で単一ラウンド版が安定したら拡張。
- **`rule_based_policy` の C++ 移植**: パフォーマンス的に不要。Python で engine state を読んで判断で十分。
- **PPO 既存モデル (`models/*.zip`) との互換性**: 観測ベクトルは同一 340 次元なので、MaskablePPO のモデルを OpenSpiel 経由で呼び出すアダプタは可能だが、今回の直接ポートでは対応しない。
