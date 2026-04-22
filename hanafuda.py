#!/usr/bin/env python3
"""花札こいこい - コンソールゲーム"""

import random
from dataclasses import dataclass, field as dfield
from typing import Optional

from core import (
    HIKARI, TANE, TANZAKU, KASU, AKATAN, AOTAN, MUJI, MONTHS,
    Card, make_deck, check_yaku, total_yaku_points,
)


# =============================================================================
# プレイヤー
# =============================================================================

@dataclass
class Player:
    name: str
    hand: list[Card] = dfield(default_factory=list)
    captured: list[Card] = dfield(default_factory=list)
    is_cpu: bool = False
    total_score: int = 0
    koikoi_declared: bool = False
    prev_yaku_points: int = 0  # こいこい前の役点

    def reset_round(self):
        self.hand.clear()
        self.captured.clear()
        self.koikoi_declared = False
        self.prev_yaku_points = 0


# =============================================================================
# ゲーム本体
# =============================================================================

class HanafudaGame:
    def __init__(self):
        self.players: list[Player] = []
        self.field: list[Card] = []
        self.deck: list[Card] = []
        self.oya_index: int = 0  # 親のインデックス
        self.round_num: int = 1
        self.max_rounds: int = 12

    def setup_players(self):
        name = input("あなたの名前を入力してください: ").strip()
        if not name:
            name = "プレイヤー"
        self.players = [
            Player(name=name, is_cpu=False),
            Player(name="CPU", is_cpu=True),
        ]

    def deal(self) -> Optional[str]:
        """カードを配る。特殊役があれば役名を返す"""
        all_cards = make_deck()
        random.shuffle(all_cards)

        for p in self.players:
            p.reset_round()

        self.players[0].hand = all_cards[0:8]
        self.players[1].hand = all_cards[8:16]
        self.field = all_cards[16:24]
        self.deck = all_cards[24:]

        # 場札に同月4枚チェック → 配り直し
        month_counts: dict[int, int] = {}
        for c in self.field:
            month_counts[c.month] = month_counts.get(c.month, 0) + 1
        if any(v == 4 for v in month_counts.values()):
            return "配り直し"

        # 手四・くっつきチェック
        for p in self.players:
            mc: dict[int, int] = {}
            for c in p.hand:
                mc[c.month] = mc.get(c.month, 0) + 1
            if any(v == 4 for v in mc.values()):
                return f"手四:{p.name}"
            if all(v == 2 for v in mc.values()) and len(mc) == 4:
                return f"くっつき:{p.name}"

        return None

    def get_matches(self, card: Card) -> list[Card]:
        """場から同月の札を取得"""
        return [c for c in self.field if c.month == card.month]

    def play_card(self, card: Card, player: Player) -> list[Card]:
        """手札/山札から1枚プレイ。取れた札のリストを返す"""
        matches = self.get_matches(card)

        if len(matches) == 0:
            self.field.append(card)
            return []
        elif len(matches) == 1:
            taken = matches[0]
            self.field.remove(taken)
            player.captured.extend([card, taken])
            return [card, taken]
        elif len(matches) == 3:
            # 4枚目 → 全部取る
            for m in matches:
                self.field.remove(m)
            player.captured.append(card)
            player.captured.extend(matches)
            return [card] + matches
        else:
            # 2枚マッチ → 選択
            if player.is_cpu:
                chosen = self.cpu_choose_match(card, matches, player)
            else:
                chosen = self.player_choose_match(card, matches)
            self.field.remove(chosen)
            player.captured.extend([card, chosen])
            return [card, chosen]

    def player_choose_match(self, played: Card, matches: list[Card]) -> Card:
        print(f"\n  「{played}」に合う札が2枚あります。どちらを取りますか？")
        for i, m in enumerate(matches):
            print(f"    {i + 1}: {m}")
        while True:
            try:
                choice = int(input("  番号> ")) - 1
                if 0 <= choice < len(matches):
                    return matches[choice]
            except (ValueError, EOFError):
                pass
            print("  正しい番号を入力してください")

    def cpu_choose_match(self, played: Card, matches: list[Card], player: Player) -> Card:
        """CPUが2枚から選ぶ：点数の高い方を取る"""
        type_rank = {HIKARI: 4, TANE: 3, TANZAKU: 2, KASU: 1}
        return max(matches, key=lambda c: type_rank.get(c.card_type, 0))

    def draw_from_deck(self, player: Player) -> Optional[Card]:
        if not self.deck:
            return None
        card = self.deck.pop(0)
        return card

    # =========================================================================
    # 表示
    # =========================================================================

    def display_state(self, current_player: Player):
        human = self.players[0]
        cpu = self.players[1]

        print("\n" + "=" * 60)
        print(f"  第{self.round_num}回戦 | "
              f"{human.name}: {human.total_score}点 | CPU: {cpu.total_score}点")
        print("=" * 60)

        # CPU取り札
        print(f"\n  【CPU取り札】({len(cpu.captured)}枚)")
        if cpu.captured:
            self._print_cards_inline(cpu.captured, "    ")

        # 場札
        print(f"\n  【場　札】({len(self.field)}枚)")
        if self.field:
            self._print_cards_numbered(self.field, "    ", show_num=False)
        else:
            print("    （なし）")

        # 自分の取り札
        print(f"\n  【自分の取り札】({len(human.captured)}枚)")
        if human.captured:
            self._print_cards_inline(human.captured, "    ")

        # 自分の手札
        if current_player == human:
            print(f"\n  【手　札】({len(human.hand)}枚)")
            self._print_cards_numbered(human.hand, "    ")

    def _print_cards_inline(self, cards: list[Card], indent: str):
        types_order = [HIKARI, TANE, TANZAKU, KASU]
        for ct in types_order:
            group = [c for c in cards if c.card_type == ct]
            if group:
                names = " ".join(str(c) for c in group)
                print(f"{indent}{names}")

    def _print_cards_numbered(self, cards: list[Card], indent: str, show_num: bool = True):
        line = ""
        for i, c in enumerate(cards):
            label = f"{i + 1}:{c}" if show_num else str(c)
            if len(line) + len(label) > 50:
                print(f"{indent}{line}")
                line = ""
            line += label + "  "
        if line:
            print(f"{indent}{line}")

    def display_yaku(self, player: Player):
        yaku = check_yaku(player.captured)
        if yaku:
            print(f"\n  ★ {player.name}の役:")
            for name, pts in yaku:
                print(f"    {name}: {pts}点")
            print(f"    合計: {total_yaku_points(yaku)}点")

    # =========================================================================
    # ターン処理
    # =========================================================================

    def player_turn(self, player: Player) -> Optional[tuple[str, int]]:
        """1ターン実行。ラウンド終了なら(勝者名, 点数)を返す"""
        self.display_state(player)

        if not player.is_cpu:
            # --- 手札からプレイ ---
            print(f"\n  ▶ {player.name}のターン")
            card = self._player_select_hand(player)
            print(f"  → 手札から「{card}」を出しました")
            taken = self.play_card(card, player)
            if taken:
                print(f"    取得: {', '.join(str(c) for c in taken)}")
        else:
            # --- CPUターン ---
            print(f"\n  ▶ CPUのターン")
            card = self._cpu_select_hand(player)
            print(f"  → CPUが「{card}」を出しました")
            taken = self.play_card(card, player)
            if taken:
                print(f"    取得: {', '.join(str(c) for c in taken)}")

        # --- 山札めくり ---
        drawn = self.draw_from_deck(player)
        if drawn:
            print(f"  → 山札から「{drawn}」をめくりました")
            taken2 = self.play_card(drawn, player)
            if taken2:
                print(f"    取得: {', '.join(str(c) for c in taken2)}")

        # --- 役チェック ---
        yaku = check_yaku(player.captured)
        current_pts = total_yaku_points(yaku)

        if current_pts > player.prev_yaku_points and current_pts > 0:
            self.display_yaku(player)

            if not player.is_cpu:
                result = self._ask_koikoi(player, current_pts)
            else:
                result = self._cpu_decide_koikoi(player, current_pts)

            if result == "勝負":
                return self._finish_round(player, current_pts)
            else:
                player.koikoi_declared = True
                player.prev_yaku_points = current_pts

        return None

    def _player_select_hand(self, player: Player) -> Card:
        while True:
            try:
                choice = int(input("\n  出す札の番号> ")) - 1
                if 0 <= choice < len(player.hand):
                    return player.hand.pop(choice)
            except (ValueError, EOFError):
                pass
            print("  正しい番号を入力してください")

    def _cpu_select_hand(self, player: Player) -> Card:
        """CPUの手札選択：マッチできる札を優先、高い札を狙う"""
        type_rank = {HIKARI: 4, TANE: 3, TANZAKU: 2, KASU: 1}

        # マッチ可能な手札
        matchable = []
        for c in player.hand:
            matches = self.get_matches(c)
            if matches:
                best_match = max(matches, key=lambda m: type_rank.get(m.card_type, 0))
                score = type_rank.get(c.card_type, 0) + type_rank.get(best_match.card_type, 0)
                matchable.append((c, score))

        if matchable:
            matchable.sort(key=lambda x: x[1], reverse=True)
            card = matchable[0][0]
        else:
            # マッチなし → 最も低い札を場に出す
            player.hand.sort(key=lambda c: type_rank.get(c.card_type, 0))
            card = player.hand[0]

        player.hand.remove(card)
        return card

    def _ask_koikoi(self, player: Player, pts: int) -> str:
        print(f"\n  現在 {pts}点の役が成立しています。")
        print("  1: 勝負（ラウンド終了）")
        print("  2: こいこい（続行）")
        while True:
            try:
                choice = int(input("  選択> "))
                if choice == 1:
                    return "勝負"
                elif choice == 2:
                    print("  「こいこい！」")
                    return "こいこい"
            except (ValueError, EOFError):
                pass
            print("  1か2を入力してください")

    def _cpu_decide_koikoi(self, player: Player, pts: int) -> str:
        """CPU: 7点未満ならこいこい、7点以上なら勝負"""
        if pts < 7:
            print("  CPUは「こいこい」を宣言しました！")
            return "こいこい"
        else:
            print("  CPUは「勝負」を宣言しました！")
            return "勝負"

    def _finish_round(self, winner: Player, pts: int) -> tuple[str, int]:
        """ラウンド終了の得点計算"""
        loser = self.players[1] if winner == self.players[0] else self.players[0]

        # 7点以上で2倍
        if pts >= 7:
            pts *= 2
            print(f"  ※7点以上のため2倍！")

        # 相手がこいこいしていた場合さらに2倍
        if loser.koikoi_declared:
            pts *= 2
            print(f"  ※相手がこいこい宣言していたため2倍！")

        print(f"\n  ◆ {winner.name}の勝ち！ {pts}点獲得！")
        winner.total_score += pts
        return (winner.name, pts)

    # =========================================================================
    # ラウンド・ゲームループ
    # =========================================================================

    def play_round(self):
        print(f"\n{'━' * 60}")
        print(f"  第{self.round_num}回戦 開始！ 親: {self.players[self.oya_index].name}")
        print(f"{'━' * 60}")

        # 配り（特殊役/配り直しチェック）
        while True:
            result = self.deal()
            if result is None:
                break
            if result == "配り直し":
                print("  場札に同月4枚！配り直します。")
                continue
            if result.startswith("手四:"):
                winner_name = result.split(":")[1]
                print(f"  ★ {winner_name}の手四！ 6点獲得！")
                winner = next(p for p in self.players if p.name == winner_name)
                winner.total_score += 6
                return
            if result.startswith("くっつき:"):
                winner_name = result.split(":")[1]
                print(f"  ★ {winner_name}のくっつき！ 6点獲得！")
                winner = next(p for p in self.players if p.name == winner_name)
                winner.total_score += 6
                return

        # ターン交互実行
        turn_order = [self.oya_index, 1 - self.oya_index]
        while True:
            for pi in turn_order:
                player = self.players[pi]
                if not player.hand and not self.deck:
                    # 手札も山札もなし → 親の勝ち（6点）
                    oya = self.players[self.oya_index]
                    print(f"\n  手札がなくなりました。親({oya.name})の勝ち！ 6点")
                    oya.total_score += 6
                    self.oya_index = self.players.index(oya)
                    return

                if not player.hand:
                    continue

                result = self.player_turn(player)
                if result:
                    winner_name, _ = result
                    self.oya_index = next(
                        i for i, p in enumerate(self.players) if p.name == winner_name
                    )
                    return

    def play_game(self):
        print("=" * 60)
        print("  花 札 こ い こ い")
        print("=" * 60)

        self.setup_players()

        # 親決め
        self.oya_index = random.randint(0, 1)
        print(f"\n  親は {self.players[self.oya_index].name} です。")

        for r in range(1, self.max_rounds + 1):
            self.round_num = r
            self.play_round()

            print(f"\n  --- 現在のスコア ---")
            for p in self.players:
                print(f"  {p.name}: {p.total_score}点")

            if r < self.max_rounds:
                try:
                    input("\n  Enterで次のラウンドへ...")
                except EOFError:
                    break

        # 最終結果
        print(f"\n{'=' * 60}")
        print("  ゲーム終了！最終結果")
        print(f"{'=' * 60}")
        for p in self.players:
            print(f"  {p.name}: {p.total_score}点")

        if self.players[0].total_score > self.players[1].total_score:
            print(f"\n  🎉 {self.players[0].name}の勝利！")
        elif self.players[0].total_score < self.players[1].total_score:
            print(f"\n  CPUの勝利！")
        else:
            print(f"\n  引き分け！")


# =============================================================================
# メイン
# =============================================================================

if __name__ == "__main__":
    try:
        game = HanafudaGame()
        game.play_game()
    except KeyboardInterrupt:
        print("\n\n  ゲームを終了します。")
