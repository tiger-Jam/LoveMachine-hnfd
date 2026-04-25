# 花札こいこい Nash均衡近似AI 技術調査

> Scope: OpenSpiel + NFSP / Deep CFR 路線で、こいこい(2人零和・不完全情報・確率遷移)について「近似Nash均衡」強度のAIを構築するための前提知識・先行研究・実装判断材料をまとめる。対象読者: 既に `engine.py` / MaskablePPO 自己対戦モデルを動かしている ML エンジニア。計算資源: 常時利用可能な GTX 1650 (4GB) + M4 Mac。

---

## 要旨 (Executive Summary)

こいこいは2人零和・不完全情報・チャンスノード(山札シャッフル)を含む拡張形ゲームで、理論的には CFR 系アルゴリズムが近似Nash均衡に収束できる対象である。先行研究は事実上 Guan et al. (IEEE TAI 2023) の Transformer + Monte-Carlo RL(人間プロ相手 53% 勝率)のみで、CFR/NFSP 路線の公開研究は存在しない。OpenSpiel は NFSP / Deep CFR / PSRO / 厳密 exploitability 計算を Python で標準提供しており、`pyspiel.Game` を純 Python で subclass することで既存の `engine.py` を比較的低コストに移植できる(ただし Python ゲームは C++ ゲームより4〜350倍遅いので CFR のサンプリングループではボトルネックになる)。実務上は **(1) 各ラウンドを独立ゲームとしてまず解く → (2) こいこい判断は "terminal-or-continue" 型のプレイヤーノードとして自然に符号化できる → (3) NFSP でベースライン exploitability を取り、Deep CFR へスケール → (4) 必要なら ReBeL 型の推論時 subgame solving** の順で段階的に進めるのが最もリスクが低い。「近傍 Nash」の数値指標は exploitability (mbb/g 類似の 1ラウンド平均得失点) で、Kuhn/Leduc クラスでは 1〜数ポイント以内を狙える。Koi-Koi 全局の情報集合数は Kuhn/Leduc より数桁大きいが、Heads-Up Limit Hold'em (10^14 states) より小さいので、function approximation 前提なら GTX 1650 クラスでも十分に到達可能な規模である。

---

## 1. Koi-Koi 特化の先行研究

### 1.1 Guan et al., IEEE TAI 2023 — 唯一の主要先行研究

- **完全引用**: S. Guan, J. Wang, R. Zhu, J. Qian, Z. Wei. "Learning to Play Koi-Koi Hanafuda Card Games With Transformers." *IEEE Transactions on Artificial Intelligence*, vol. 4, no. 6, pp. 1449–1460, Dec. 2023. DOI: 10.1109/TAI.2023.3240077. IEEE Xplore: <https://ieeexplore.ieee.org/document/10032777>
- **コード**: <https://github.com/guansanghai/KoiKoi-AI> (PyTorch 1.8.1, PySimpleGUI GUI)
- **arXiv preprint**: 確認できなかった。IEEE Xplore と ResearchGate のみに掲載。arXiv:2209.13220 は別の論文(T2TL, robotics)で、検索で誤ヒットするので注意。

**アーキテクチャ** (論文 abstract + リポジトリ構成から):
- Transformer encoder をバックボーンとし、カード状態を **tokenized** 入力として与える(各カードを 1 トークン扱い)
- 出力はアクション確率分布(打牌 / マッチ / こいこい判断)
- リポジトリに `koikoinet2L.py` (2層構成を示唆) と `torch_text_mha.py` (自作 multi-head attention) がある
- **注意**: 論文本文(層数・ヘッド数・hidden dim の正確な値)は IEEE Xplore 有料、ResearchGate でも Fetch できず。数値はコードを直接読む必要あり。

**学習設定**:
- **Monte-Carlo 強化学習** + "phased round reward"(論文 abstract が示す独自のラウンド単位報酬設計)
- 教師あり事前学習 (`sl_train.py`) → RL fine-tune (`rl_train.py`) の2段構成が推察される
- `gamerecords_dataset` を参照しており、人間プレイ棋譜からの warm-start が組み込まれている可能性が高い
- 具体的ステップ数 / 計算資源 / 対戦相手プール(self-play か固定相手か)は公開情報から確定できない

**ルール**: Steam 版 *KoiKoi-Japan* と同一(README 明記)。日本標準ルールに近いが、手役(手四・くっつき)・月見/花見盃・7 点以上倍率などの採用有無は要確認。

**評価**:
- 多局こいこいで熟練人間相手に **勝率 53%**、**平均得点差 +2.02 点**
- 注意: 熟練プレイヤーの定義・対戦数・統計的有意差検定の詳細は確認できず

**弱点として推察される点**:
- Monte-Carlo RL は policy gradient 系であり、一般に Nash 均衡への収束保証はない(NFSP/Deep CFR と対比)
- exploitability 指標での評価は報告されていない — つまり「熟練人間に勝てる」が「近傍 Nash」かは不明
- 多局間戦略(親権保持による長期最適化, 既存 DESIGN.md §2.3)の明示的モデル化は触れられていない

### 1.2 その他の学術研究

ハナフダ・こいこいに関する査読論文は Guan et al. 以外ほぼ存在しない(2026 年 4 月時点、Google Scholar・IEEE Xplore で確認)。関連ジャンル:
- 花札系は学術的ブルーオーシャンで、先行研究少ないことはリサーチ寄与の余地がある反面、ベンチマーク不在という不便さも意味する
- 関連性のある和製カードゲーム研究は花ゆげや大貧民(Daihinmin, UEC大会系)など別系統にある

---

## 2. 不完全情報ゲーム Nash 均衡の理論基盤

### 2.1 なぜ近似 Nash が定義できるか

- 2人零和・perfect recall・extensive-form ゲームは **sequence form** に変換することで、Koller–Megiddo–von Stengel (1994) の線形計画で多項式時間で Nash を求められる。これが Minimax 定理の拡張形である
- 大規模ゲームでは LP が解けないので、**反復型 self-play アルゴリズム**(CFR 系・FSP 系)で近似する
- 近似度の尺度は **exploitability**: 各プレイヤーが均衡戦略に対する最良応答に乗り換えた場合の獲得利得の合計(2人零和ではこれが 0 で Nash)

### 2.2 CFR(Zinkevich et al., NIPS 2007)

Zinkevich, Bowling, Johanson, Piccione. "Regret Minimization in Games with Incomplete Information." NIPS 2007. <https://poker.cs.ualberta.ca/publications/NIPS07-cfr.pdf>

- 各情報集合で **counterfactual regret** を独立にミニマイズすれば、全体の regret が O(√T) で抑えられ平均戦略が Nash に収束するという命題
- 当時 10^12 states の Limit Texas Hold'em 抽象ゲームを解き、ブレイクスルーとなった
- Vanilla CFR は全ゲーム木を毎イテレーション走査するので、情報集合数 N に比例したコスト

### 2.3 MCCFR(Lanctot et al., NIPS 2009)

Lanctot, Waugh, Zinkevich, Bowling. "Monte Carlo Sampling for Regret Minimization in Extensive Games." NIPS 2009. <https://mlanctot.info/files/papers/nips09mccfr.pdf>

3つの主要サンプリング変種:
- **Outcome-sampling (OS)**: 1反復で1本のプレイアウトのみ。最軽量、variance 高い
- **External-sampling (ES)**: チャンスと相手手番のみサンプル。自分の手番は全列挙。poker で事実上の定番
- **Chance-sampling (CS)**: チャンスノードのみサンプル。OS と ES の中間

Goofspiel では MCCFR が Vanilla CFR より3桁少ないノード数で ε_σ < 0.5 に到達。Koi-Koi でも、チャンスノードが毎ターンあるため ES または OS が妥当。

### 2.4 Deep CFR(Brown, Lerer, Gross, Sandholm. ICML 2019)

arXiv:1811.00164 <https://arxiv.org/abs/1811.00164>

- Regret / average strategy を NN で近似し、明示的なカード抽象(abstraction)が不要に
- 2つのネットワーク: **advantage network**(regret 推定)+ **average strategy network**
- **Reservoir sampling** のバッファに訪問した infoset を蓄積し、毎 CFR イテレーションで network を再学習(sliding window だと exploitability が頭打ちになる点に注意)
- Linear CFR (iteration t に t の重み) 相当の更新規則
- 5-card abstracted FHP (Flop Hold'em Poker) で NFSP より低 exploitability (Deep CFR: 37 mbb/g, NFSP: 47 mbb/g, 3.6M クラスタ tabular abstraction と同等)
- **実装複雑度**: ややトリッキー。Reservoir buffer, scratch-from-initialization recommendation, 2 ネットワーク管理

### 2.5 NFSP(Heinrich & Silver, 2016)

arXiv:1603.01121 <https://arxiv.org/abs/1603.01121>

- Fictitious Self-Play を関数近似化: **best response 学習 (DQN)** + **average policy 学習 (supervised)** の2ネットワーク構成
- **anticipatory parameter η** (〜0.1) で両者を混合
- Leduc で Nash に実験的に収束、vanilla RL は発散する
- **実装複雑度**: 低〜中。DQN が書ければほぼ書ける。OpenSpiel に Python 参考実装あり
- **収束速度**: Leduc で 100 mA/g ラインを 230k iter(約4.4時間)、60 mA/g ラインを 850k iter(約19時間)(公開実装の報告値)

### 2.6 PSRO(Lanctot et al., NIPS 2017)

arXiv:1711.00832, <https://mlanctot.info/files/papers/nips17-psro.pdf>

- "A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning"
- 経験ゲーム(empirical game)にメタ戦略を定義し、各反復で **best response oracle** を追加して empirical game を拡張
- Fictitious Play, Double Oracle, Independent RL を統一的に包含
- Koi-Koi のような 2人零和には fictitious play / double oracle 相当で作動。NFSP よりメモリ・ネットワーク数が多くなりがちだが、より柔軟
- OpenSpiel に `psro_v2` 実装あり

### 2.7 アルゴリズム比較表

| アルゴリズム | 実装複雑度 | サンプル効率 | 既知の収束性 | Koi-Koi 向き度 |
|---|---|---|---|---|
| Tabular CFR | 低 | 中 (全列挙) | Nash に O(1/√T) | × (state が多すぎ) |
| MCCFR (ES) | 中 | 中〜高 | Nash に O(1/√T) (expected) | △ (tabular だと infoset 爆発) |
| Deep CFR | **中高** | **高** | 近似 Nash (NN 誤差込み) | **◎ (function approx が本命)** |
| NFSP | 中 | 中 | Leduc 実験で収束 | ○ (簡潔、最初の基線に適) |
| PSRO | 中 | 中 | Double Oracle 系 | △ (2人零和なら NFSP で十分) |
| MaskablePPO (現行) | 低 | 高 | 保証なし (Nash 到達は偶発) | △ (moderate 強度止まりの理由) |

> 結論的に、**NFSP で基線 → Deep CFR で本線** が王道。現行 MaskablePPO は Nash 到達の理論保証がないため "moderate" 止まりなのは自然。

---

## 3. 近年の SOTA マイルストーン(短縮版)

| 年 | システム | 主要著者 | 会場 | 要点 |
|---|---|---|---|---|
| 2017 | **DeepStack** | Moravčík et al. | Science | 初のスーパーヒューマン HU NL ポーカー。**continual re-solving**(各アクションごとに深さ限定 CFR を走らせる)+ value network でイントゥイション代替。arXiv:1701.01724 |
| 2018 | **Libratus** | Brown & Sandholm | Science (vol.359) | HU NL を 120k ハンドで人間プロ撃破。**blueprint (precomputed) + nested subgame solving + self-improvement**。ドメイン知識なし |
| 2019 | **Pluribus** | Brown & Sandholm | Science (vol.365) | 6人 NL で人間プロ超え。blueprint を **8日 / 12,400 core-hours** で学習、オンラインは 28 cores。MCCFR 系(MCCFRM)で適応 |
| 2019 | **Deep CFR** | Brown et al. | ICML | NN regret 近似で abstraction を不要化。NFSP 超え |
| 2020 | **ReBeL** | Brown et al. | NeurIPS | **public belief state (PBS)** 上で AlphaZero 型 search + RL を拡張。2人零和で Nash への収束証明あり。arXiv:2007.13544, コード: <https://github.com/facebookresearch/rebel> |
| 2021 | **Player of Games** | Schmid et al. | DeepMind tech report | 完全情報/不完全情報の両方に適用可能な一般フレーム。Slumbot 超え、Scotland Yard で SOTA |
| 2022 | **AlphaHoldem** | Zhao et al. | AAAI (Distinguished Paper) | **End-to-end RL(search なし)** で DeepStack・Slumbot 撃破。3日・1 PC・推論 2.9 ms/decision。pseudo-Siamese + multi-task loss |

**通底する教訓**:
1. **Subgame solving at inference** (DeepStack, Libratus, ReBeL) が Nash 達成の決定打。Blueprint だけでは理論的にも実用的にも限界がある
2. ただし **AlphaHoldem** のように、**大規模 end-to-end + 綿密な state encoding + self-play curriculum** で search なしでも強力になる例もある(計算資源とモデルサイズ次第)
3. 2人零和なら ReBeL が最も理論的に clean(Nash 収束証明 + search)

Koi-Koi 規模なら、**Deep CFR ベースライン → ReBeL 型 subgame solving** が理想ルート。GTX 1650 + 時間無制限という条件では十分射程内。

---

## 4. OpenSpiel 実用ガイド

### 4.1 Python で使える主要アルゴリズム

(公式ドキュメント: <https://openspiel.readthedocs.io/en/latest/algorithms.html>)

- `cfr` (Vanilla CFR), `cfr_br` (CFR against Best Response)
- `external_sampling_mccfr`, `outcome_sampling_mccfr`
- `discounted_cfr`, `fixed_strategy_iteration_cfr` (FSICFR)
- `deep_cfr` (PyTorch/JAX 両方の実装あり)
- `nfsp`
- `psro_v2`
- `exploitability`, `best_response`, `nash_conv`
- `regression_cfr` (RCFR)
- `extensive_form_fictitious_play` (XFP)

例: Kuhn Poker NFSP 参考実装 — <https://github.com/google-deepmind/open_spiel/blob/master/open_spiel/python/examples/kuhn_nfsp.py>

### 4.2 ゲーム実装の2経路

**経路 A: C++ でゲームを書いて pybind11 で Python 公開**
- 長所: アルゴリズム実行速度が Python ゲームの 4〜350 倍速い(GPU-CFR 論文で報告されたベンチマーク幅)。CFR の数百万反復に本気で耐える
- 短所: C++ ビルド環境(cmake + pybind11)、既存 `engine.py` を再実装、差分バグが混入しやすい
- 所要: ソロエンジニアで 2〜4 週間

**経路 B: `pyspiel.Game` / `pyspiel.State` を純 Python で subclass**
- 長所: 既存 `engine.py` を thin adapter で包める。`open_spiel/python/games/tic_tac_toe.py` が雛形(74 行程度)
- 短所: Python ゲームは C++ 例 binary から呼べない、CFR loop が遅い
- 推奨 override メソッド: `current_player()`, `_legal_actions(player)`, `_apply_action(action)`, `is_terminal()`, `returns()`, `information_state_string()`, `information_state_tensor()`, `chance_outcomes()`
- 登録: `pyspiel.register_game(_GAME_TYPE, MyGame)`

**ソロエンジニアへの推奨**: **まず経路 B で MVP**。NFSP の学習スループットが致命的に遅い場合のみ、後で経路 A に書き換える。Koi-Koi のゲームロジックは十分小さい(1手あたり数十個の action) ので、Python でも数万局/時間 は出るはず。

### 4.3 OpenSpiel 標準実装済みの類似カードゲーム

(`open_spiel/python/games/` の時点の一覧)
- `kuhn_poker`, `liars_poker`, `tic_tac_toe`, `block_dominoes`, `team_dominoes`, `hangman`, `iterated_prisoners_dilemma`, `ant_foraging`, `dynamic_routing`, `chat_game`, `pokerkit_wrapper`, `repeated_pokerkit`

C++ 側には `leduc_poker`, `universal_poker` (ACPC), `tiny_bridge_2p`, `tiny_bridge_4p`, `gin_rummy`, `goofspiel`, `hearts`, `bridge`, `skat` など実装あり。**ハナフダ / こいこい 実装は存在しない**(2026/04 時点で検索結果にヒットなし)。`gin_rummy` は Python 側にはないが C++ で既に wrap されているので、メルド系カードゲーム実装の参考コードとして有用。

### 4.4 Exploitability / NashConv の計算

- `python/algorithms/exploitability.py` で strategy を与えると NashConv を計算
- **厳密計算は情報集合数 N に対して O(N) のツリー走査**が必要。Kuhn (infoset 12) / Leduc (infoset 936) クラスでは秒オーダー。Koi-Koi 全局は infoset 数が数桁大きいはずで、厳密 NashConv は多分 **tractable ではない**
- 代替: **approximate exploitability** (IJCAI 2022, <https://www.ijcai.org/proceedings/2022/0484.pdf>) — best response 自体を学習する方法。Koi-Koi でも使える
- 実用的には「簡約版ゲーム(手札 4 枚, 場 4 枚 など)で厳密 NashConv」「本番ゲームで学習 BR の平均利得」という2本立て評価

### 4.5 GTX 1650 級での学習時間の目安

- Kuhn NFSP: 数分〜数十分で Nash 近傍(infoset 12個)
- Leduc NFSP: 4〜19 時間で exploitability 60 mA/g(公開実装の報告値)
- Leduc Deep CFR: 100k iter 台で Leduc 解決、Deep CFR 論文の FHP(5-card)はベンチマーク
- HU Limit Hold'em 級 Deep CFR: マルチ GPU で 数日レンジ
- **Koi-Koi 1ラウンド**: Leduc より 2〜3 桁 infoset が多いと見積もると、**NFSP で数日〜2週間、Deep CFR で数日〜1週間**(GTX 1650 1台、python ゲーム). 見積もりには以下の不確定要素があるので実測が必須: Python ゲームのステップ速度、ネットワークサイズ、batch 並列度。4GB VRAM 制約でバッチは 512〜2048 程度に抑えざるを得ない

---

## 5. Koi-Koi 特化の設計検討

### 5.1 局分解(1ラウンド vs 全マッチ)

| 方式 | 状態空間 | 長所 | 短所 |
|---|---|---|---|
| **1ラウンド独立** | カード 48 枚 × 手札 8 枚 ≒ C(48,8) ≈ 3.77×10^8 配り + 軌跡 | 小さく解きやすい、NFSP/Deep CFR が実現的 | 多局戦略(親権保持・こいこい閾値の局数依存)を表現できない |
| **3/6/12 局全体** | 上記 × ラウンド数 × 累積得点状態 | 多局最適化を内包(DESIGN.md §2.3 の戦略を表現可能) | 状態空間が桁違い、CFR の infoset 爆発、学習困難 |
| **ハイブリッド**: 1ラウンド policy + meta-controller(外側) | 1ラウンドは CFR で解き、ラウンド間重み(こいこい閾値など)は別途 RL / grid search | 実現可能 + 多局表現可能 | 2段構成のインターフェース設計が要 |

**推奨**: まず **1ラウンド独立** で Nash を取り、**meta-controller** で多局要素を重ねる(DESIGN.md §8 のパラメータ化と親和的)。1ラウンド Nash が解ければ他は「こいこい判断閾値の調整」で 90% 解ける問題に還元される。

### 5.2 こいこい判断の符号化

- 役成立時に **"continue (koi-koi) / stop (agari)"** の 2 択プレイヤーノードを挿入する
- CFR の regret 会計は、このノードでの regret を通常通り infoset で積算する
- **倍率 (相手のこいこい後に自分が勝った場合 ×2) は utility / reward に乗せる**。terminal での payoff が枝分かれするだけで CFR 側は変更不要
- 注意: こいこい宣言 → 手札ゼロまで続行 → 流局という終端パスが追加される。流局時の親権継続は **1ラウンド独立モデルでは reward 0**、meta-controller に親権フラグを渡す

### 5.3 チャンスノード(山札)

- 配り(手札 8, 場 8, 残 24)は1回大きなチャンスノード。あるいは8回の1枚ずつチャンスノード — **後者の方が external sampling MCCFR と相性がよい**(1枚ずつ chance outcome を sample できる)
- 山札からの引きは毎ターンのチャンスノード(相手が取った後に1枚めくる)
- OpenSpiel の chance node API (`chance_outcomes()` が `[(action, prob), ...]` を返す) に自然に乗る

### 5.4 情報状態エンコーディング

カード集合ベース(category embedding)vs bit-vector:

- **Bit vector 方式** (推奨 for NFSP/Deep CFR): 48 カード × 位置クラス(自手/相手取り/自取り/場/捨てた/山残/不可視)で 48 × ~7 = **336 bit の one-hot / multi-hot**。補助特徴(月別カウント、役進捗、ラウンド番号、累積得点差)を concat
- **Category embedding 方式** (Guan et al. 方式): 各カードを token として transformer に流す。より表現力が高いが遅い。Deep CFR の advantage network には過剰設計になりがち
- 参考: AlphaHoldem は手札+公開カード+betting history を **3D テンソル(pseudo-image)**で表現。Koi-Koi では「12 月 × 4 枚」の 2D grid + チャネル(所属状態)で同様の設計が可能。CNN に乗る

**推奨**: Deep CFR / NFSP の初期実装は **bit vector + MLP** で。性能が頭打ちしたら **2D grid + 小さい CNN** に upgrade。Transformer は overkill(Guan et al. の方式は Monte-Carlo RL 固有の理由で採用された節あり)。

### 5.5 Abstraction 必要性

- HU Limit Hold'em は 10^14 infosets で abstraction 必須、HU NL は 10^161 と言われる
- Koi-Koi 1ラウンドは concretely 評価が必要だが、 **手札 8 / 場 8 / 山 24 の組合せ空間 ≪ 10^12** のはず
- Deep CFR は「NN 自体が soft abstraction」として働くので、**明示的 card abstraction は不要**と判断してよい
- Action abstraction も Koi-Koi では不要(合法手は常に数十個まで)

---

## 6. 実装ロードマップ

### Phase 0: OpenSpiel 導入検証 (1〜2日)

- `pip install open_spiel` または source build (Mac M4 + Linux GTX 1650 双方で)
- `examples/kuhn_nfsp.py` を1回走らせて exploitability 曲線が描けること
- Go/No-Go: Kuhn で NashConv < 0.1 が取れた

### Phase 1: engine.py → pyspiel.Game 移植 (2〜4週)

- `open_spiel/python/games/tic_tac_toe.py` (簡単) と OpenSpiel C++ の `gin_rummy` (カード+メルド類似) を参考
- 実装行数目安: ~600〜1000 行 (cards.py の活用含む)
- チェックリスト:
  - Action encoding: {discard card_i, match field_j, call koikoi, call agari} を整数 id に落とす
  - Chance node 設計: 配り・毎ターンの山札引き
  - `information_state_string()`: CFR tabular 用に一意な文字列
  - `information_state_tensor()`: NN 用ベクトル (§5.4 の bit vector)
  - 合法手マスキングが既存 MaskablePPO と整合すること
- 検証: 既存の `replay.py` で生成した棋譜が pyspiel 上で同じ payoff を返すこと
- Go/No-Go: 100局のランダム対戦が pyspiel 経由で動く。平均対戦時間 < 数秒/局

### Phase 2: 縮小版での tabular CFR (1週)

- 手札 4 / 場 4 / 山 8 程度に縮小したバージョンで `cfr.py` を回す
- Exploitability が 1000 iter で 0 に収束すること
- 目的: **ゲーム木実装のバグ検出**。Payoff 対称性、chance prob の正規化、infoset key のユニーク性
- Go/No-Go: 縮小版で exploitability < 0.01 まで落とせる

### Phase 3: フルサイズで NFSP (2〜6週)

- `examples/leduc_nfsp.py` をベースに改造
- Hyperparam 起点: RL lr=0.1 (DQN), SL lr=0.005, replay buffer 200k, reservoir buffer 2M, anticipatory η=0.1
- Network: 2 隠れ層 × 128〜256 units の MLP(情報状態 tensor → action logits)
- 評価: approximate exploitability(学習された best response の平均利得)を 10k iter ごとに計算
- Go/No-Go: MaskablePPO 現行 model に対して勝率 ≥ 55%、approximate exploitability が単調減少

### Phase 4: Deep CFR へスケール (2〜4週)

- `python/algorithms/deep_cfr.py` を流用
- External sampling、advantage network 2 個(P1/P2)+ average strategy network、reservoir sampler
- Batch size 2048 (4GB VRAM 制約下の上限)、traversals/iter 500〜5000
- Deep CFR 論文の付録を hyperparam reference として使用
- Go/No-Go: NFSP より低 exploitability、または NFSP policy に対し勝率 ≥ 55%

### Phase 5 (オプション): 推論時 subgame solving (ReBeL 型)

- ReBeL 公開実装 <https://github.com/facebookresearch/rebel> は Heads-Up Poker 専用だが、参考にできる
- Public Belief State を Koi-Koi に定義: 両プレイヤーの手札分布への信念 × 公開情報(場・取り・捨て・点数)
- 推論時に現在の PBS から depth-limited CFR を回し、policy を更新
- 効果の目安: DeepStack クラスだと exploitability を 1 桁落とせる
- Go/No-Go: exploitability がさらに 50% 以上改善

---

## 7. リスク・落とし穴

1. **Reward スケール**: CFR は payoff の大きさに scale 不変だが、Deep CFR の NN fitting は scale 依存。1ラウンド payoff を ±1 に正規化(またはマッチ終局で ±1)してから学習
2. **Per-round vs per-match gradient signal**: 1ラウンド独立モデルで学習する場合、多局的情報(残局数、累積得点)を状態に含めないこと。含めると独立仮定が崩れる
3. **Reservoir buffer 満杯問題** (Deep CFR): sliding window にすると exploitability が頭打ちに(Brown et al. 2019 が明示報告)。必ず **reservoir sampling** で
4. **Opponent pool の stale化** (NFSP): average policy のバッファサイズが小さいと過去戦略を忘れる。reservoir ≥ 2M infoset 経験
5. **評価指標**:
   - 勝率 vs MaskablePPO は相対指標に過ぎず、Nash 近傍の証明にはならない
   - Exploitability(または approximate exploitability) が本来の指標
   - Koi-Koi フルゲームでの正確な exploitability は計算困難 → approximate で代替
6. **「近傍 Nash」の数値感**:
   - Kuhn: NashConv < 0.01 が現実的
   - Leduc: exploitability < 60 mA/g が通常の "解けた" の基準
   - Koi-Koi: 1ラウンド平均点 (max 15 点) で **exploitability < 0.5 点** なら実用上 Nash 相当と呼べる。これより厳しい値は測定困難
7. **Python ゲームの速度**: pyspiel Python game は C++ game より 4〜350× 遅い(GPU-CFR 論文ベンチマーク)。Phase 3 で学習が 2 週間を超えるようなら、engine.py の C++ 移植 or Cython 化を検討
8. **GTX 1650 の 4GB VRAM 制約**: Deep CFR の advantage net + strategy net × 2 で合計 4 個のネットワーク。モデルサイズは hidden 256 程度に抑える必要あり
9. **手役(くっつき・手四)配り直し**: 配り直しはチャンスノードの再試行で表現できるが、期待値計算が若干厄介。最初は「手役イベントはない」として解き、後付けで扱う
10. **多局親権継続ルール**: 1ラウンド payoff = 得点そのものとしてよいが、流局時の親権継続価値はモデル外に置かざるを得ない(meta-controller で調整)

---

## 8. 参考文献・コードリンク

### 主要論文

- Zinkevich, Bowling, Johanson, Piccione (2007). "Regret Minimization in Games with Incomplete Information." NIPS 2007. <https://poker.cs.ualberta.ca/publications/NIPS07-cfr.pdf>
- Lanctot, Waugh, Zinkevich, Bowling (2009). "Monte Carlo Sampling for Regret Minimization in Extensive Games." NIPS 2009. <https://mlanctot.info/files/papers/nips09mccfr.pdf>
- Heinrich & Silver (2016). "Deep Reinforcement Learning from Self-Play in Imperfect-Information Games." arXiv:1603.01121. <https://arxiv.org/abs/1603.01121>
- Moravčík et al. (2017). "DeepStack: Expert-Level Artificial Intelligence in Heads-Up No-Limit Poker." *Science*. arXiv:1701.01724. <https://arxiv.org/abs/1701.01724>
- Lanctot et al. (2017). "A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning." NIPS 2017. <https://mlanctot.info/files/papers/nips17-psro.pdf>
- Brown & Sandholm (2018). "Superhuman AI for Heads-Up No-Limit Poker: Libratus Beats Top Professionals." *Science*, vol. 359. <https://www.science.org/doi/10.1126/science.aao1733>
- Brown, Lerer, Gross, Sandholm (2019). "Deep Counterfactual Regret Minimization." ICML 2019. arXiv:1811.00164. <https://arxiv.org/abs/1811.00164>
- Brown & Sandholm (2019). "Superhuman AI for Multiplayer Poker." *Science*, vol. 365. <https://www.science.org/doi/10.1126/science.aay2400>
- Brown, Bakhtin, Lerer, Gong (2020). "Combining Deep Reinforcement Learning and Search for Imperfect-Information Games (ReBeL)." NeurIPS 2020. arXiv:2007.13544. <https://arxiv.org/abs/2007.13544>
- Schmid et al. (2021). "Player of Games." DeepMind. <https://arxiv.org/abs/2112.03178>
- Zhao, Yan, Li, Li, Xing (2022). "AlphaHoldem: High-Performance AI for Heads-Up No-Limit Poker via End-to-End RL." AAAI 2022. <https://ojs.aaai.org/index.php/AAAI/article/view/20394>
- Guan, Wang, Zhu, Qian, Wei (2023). "Learning to Play Koi-Koi Hanafuda Card Games With Transformers." *IEEE Transactions on Artificial Intelligence*, vol. 4, no. 6, pp. 1449–1460. DOI: 10.1109/TAI.2023.3240077. <https://ieeexplore.ieee.org/document/10032777>
- Lanctot et al. (2019). "OpenSpiel: A Framework for Reinforcement Learning in Games." arXiv:1908.09453. <https://arxiv.org/abs/1908.09453>

### コード・リポジトリ

- **OpenSpiel**: <https://github.com/google-deepmind/open_spiel>
  - ドキュメント: <https://openspiel.readthedocs.io/>
  - Python games: `open_spiel/python/games/` (tic_tac_toe, kuhn_poker ほか)
  - NFSP example: `open_spiel/python/examples/kuhn_nfsp.py`, `leduc_nfsp.py`
  - Deep CFR: `open_spiel/python/algorithms/deep_cfr.py` (PyTorch) / `deep_cfr_tf2.py`
  - Exploitability: `open_spiel/python/algorithms/exploitability.py`
- **KoiKoi-AI (Guan et al.)**: <https://github.com/guansanghai/KoiKoi-AI>
- **ReBeL (Facebook Research)**: <https://github.com/facebookresearch/rebel>
- **EricSteinberger/Neural-Fictitious-Self-Play**: <https://github.com/EricSteinberger/Neural-Fictitous-Self-Play> (NFSP のスケーラブル実装、OpenSpiel 外)
- **RLCard**: <https://github.com/datamllab/rlcard> (カードゲーム専用の軽量フレーム、参考価値あり)
- **Hanafuda (Yaruki00)**: <https://github.com/Yaruki00/HANAFUDA> (ゲームロジックのみ、AI なし)

### 追加リソース

- OpenSpiel Colab tutorial: <https://colab.research.google.com/github/deepmind/open_spiel/blob/master/open_spiel/colabs/OpenSpielTutorial.ipynb>
- Lanctot's OpenSpiel introduction slides: <https://mlanctot.info/open_spiel-tutorial-kuleuven-mar11-2020.pdf>
- Sandholm CMU lecture on CFR: <http://www.cs.cmu.edu/~sandholm/cs15-888F23/Lecture_5_CFR.pdf>
- GPU-Accelerated CFR (参考 — Python/C++ 速度比較): arXiv:2408.14778

### 未解決の確認事項

- Guan et al. IEEE TAI 2023 の本文数値(transformer 層数・ヘッド・hidden dim、総学習ステップ数、計算資源、人間相手の試合数と検定)は、IEEE Xplore 有料アクセスかリポジトリのコード直読みが必要。現時点の記述は abstract + README からの推察
- OpenSpiel 公式リポジトリに **hanafuda / koikoi の PR や issue** は見つからなかった。新規実装としてはパイオニア
- Koi-Koi 全局(3/6/12 ラウンド連続)の exploitability を厳密に求めた研究は 0 件。1ラウンド独立 + meta controller で近似するのが最初の現実解
