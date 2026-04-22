#!/usr/bin/env python3
"""花札こいこい - Web GUI サーバー

使い方:
    python3 web.py
    ブラウザで http://localhost:8800 を開く
"""

import json
import os
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from core import HIKARI, TANE, TANZAKU, KASU, MONTHS, check_yaku, total_yaku_points
from engine import (
    KoikoiEngine, Phase, rule_based_policy,
    ACTION_KOIKOI, ACTION_SHOWDOWN, NUM_CARDS,
)

STATIC_DIR = Path(__file__).parent / "static"
KIFU_DIR = Path(__file__).parent / "kifu"


class GameSession:
    def __init__(self, total_rounds=12, opponent="rule", rules=None):
        self.engine = KoikoiEngine(rules=rules)
        self.rules = self.engine.rules
        self.total_rounds = total_rounds
        self.current_round = 1
        self.scores = [0, 0]
        self.oya = 0
        self.opponent = opponent
        self.kifu = {"rounds": [], "total_rounds": total_rounds}
        self._round_actions = []
        self._last_opponent_actions = []
        self._start_round()

    def _start_round(self):
        while True:
            info = self.engine.reset(oya=self.oya, seed=int(time.time() * 1000) % (2**31))
            special = info.get("special")
            if special == "redeal":
                continue
            if self.engine.done:
                self._record_special(special)
                break
            break
        self._round_actions = []
        if not self.engine.done:
            self._play_opponent_if_needed()

    def _record_special(self, special):
        if special and ("teshi" in special or "kuttsuki" in special):
            winner = self.engine.winner
            score = self.engine.win_score
            self.scores[winner] += score
            self.kifu["rounds"].append({
                "round": self.current_round,
                "oya": self.oya,
                "special": special,
                "winner": winner,
                "score": score,
                "actions": [],
            })

    def _play_opponent_if_needed(self):
        self._last_opponent_actions = []
        while (not self.engine.done and
               self.engine.current_player == 1):
            action = self._get_opponent_action()
            phase = self.engine.phase.name
            card_id = action if action < NUM_CARDS else None
            card_name = None
            if action < NUM_CARDS:
                card_name = self.engine.card_by_id(action).name
            elif action == ACTION_KOIKOI:
                card_name = "こいこい"
            elif action == ACTION_SHOWDOWN:
                card_name = "勝負"
            self._last_opponent_actions.append({
                "phase": phase,
                "action": action,
                "card_id": card_id,
                "card_name": card_name,
            })
            self._record_action(1, action)
            self.engine.step(action)

    def _get_opponent_action(self):
        return rule_based_policy(self.engine, 1)

    def _record_action(self, player, action):
        phase = self.engine.phase.name
        card_name = None
        if action < NUM_CARDS:
            card_name = self.engine.card_by_id(action).name
        elif action == ACTION_KOIKOI:
            card_name = "こいこい"
        elif action == ACTION_SHOWDOWN:
            card_name = "勝負"
        self._round_actions.append({
            "player": player,
            "phase": phase,
            "action": action,
            "card_name": card_name,
        })

    def do_action(self, action):
        events = []
        self._record_action(0, action)
        info = self.engine.step(action)
        events.extend(info.get("events", []))

        if not self.engine.done:
            self._play_opponent_if_needed()

        if self.engine.done:
            self._finish_round()

        return events

    def _finish_round(self):
        winner = self.engine.winner
        score = self.engine.win_score
        if winner is not None:
            self.scores[winner] += score

        p0_yaku = check_yaku(self.engine.players_captured[0], self.rules)
        p1_yaku = check_yaku(self.engine.players_captured[1], self.rules)

        self.kifu["rounds"].append({
            "round": self.current_round,
            "oya": self.oya,
            "winner": winner,
            "score": score,
            "player_yaku": [(name, pts) for name, pts in p0_yaku],
            "opponent_yaku": [(name, pts) for name, pts in p1_yaku],
            "actions": list(self._round_actions),
        })

    def next_round(self):
        if self.current_round >= self.total_rounds:
            return False
        if self.engine.winner is not None:
            self.oya = self.engine.winner
        self.current_round += 1
        self._start_round()
        return True

    def get_state(self):
        e = self.engine
        hand_ids = sorted([c.id for c in e.players_hand[0]])
        field_ids = sorted([c.id for c in e.field], key=lambda i: e.card_by_id(i).month)
        p_cap = sorted([c.id for c in e.players_captured[0]])
        o_cap = sorted([c.id for c in e.players_captured[1]])

        legal = e.get_legal_actions() if (
            not e.done and e.current_player == 0
        ) else []

        p_yaku = check_yaku(e.players_captured[0], self.rules)
        o_yaku = check_yaku(e.players_captured[1], self.rules)

        pending = None
        if e._pending_played is not None:
            pending = e._pending_played.id

        game_over = (e.done and self.current_round >= self.total_rounds)

        return {
            "phase": e.phase.name,
            "hand": hand_ids,
            "field": field_ids,
            "player_captured": p_cap,
            "opponent_captured": o_cap,
            "opponent_hand_count": len(e.players_hand[1]),
            "legal_actions": legal,
            "deck_remaining": len(e.deck),
            "player_koikoi": e.players_koikoi[0],
            "opponent_koikoi": e.players_koikoi[1],
            "player_yaku": p_yaku,
            "opponent_yaku": o_yaku,
            "player_yaku_points": total_yaku_points(p_yaku),
            "opponent_yaku_points": total_yaku_points(o_yaku),
            "done": e.done,
            "winner": e.winner,
            "win_score": e.win_score,
            "pending_card": pending,
            "round": self.current_round,
            "total_rounds": self.total_rounds,
            "scores": list(self.scores),
            "oya": self.oya,
            "game_over": game_over,
            "opponent_actions": getattr(self, "_last_opponent_actions", []),
        }

    def save_kifu(self):
        KIFU_DIR.mkdir(exist_ok=True)
        self.kifu["scores"] = list(self.scores)
        self.kifu["winner"] = 0 if self.scores[0] > self.scores[1] else (
            1 if self.scores[1] > self.scores[0] else None
        )
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = KIFU_DIR / f"kifu_{ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.kifu, f, ensure_ascii=False, indent=2)
        return str(path)


game = None  # type: Optional[GameSession]


def get_cards_data():
    from core import make_deck
    deck = make_deck()
    return [
        {
            "id": c.id,
            "month": c.month,
            "month_name": MONTHS[c.month],
            "name": c.name,
            "card_type": c.card_type,
            "tanzaku_type": c.tanzaku_type,
        }
        for c in deck
    ]


CARDS_DATA = get_cards_data()


class GameHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.path = "/index.html"

        if self.path.startswith("/api/"):
            self._handle_api_get()
        else:
            self._serve_static()

    def do_POST(self):
        self._handle_api_post()

    def _serve_static(self):
        path = STATIC_DIR / self.path.lstrip("/")
        if not path.exists():
            self.send_error(404)
            return
        content = path.read_bytes()
        self.send_response(200)
        ct = "text/html"
        if path.suffix == ".css":
            ct = "text/css"
        elif path.suffix == ".js":
            ct = "application/javascript"
        elif path.suffix == ".json":
            ct = "application/json"
        elif path.suffix == ".svg":
            ct = "image/svg+xml"
        self.send_header("Content-Type", f"{ct}; charset=utf-8")
        self.send_header("Content-Length", len(content))
        if path.suffix == ".svg":
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(content)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _handle_api_get(self):
        if self.path == "/api/cards":
            self._json_response(CARDS_DATA)
        elif self.path == "/api/state":
            global game
            if game is None:
                self._json_response({"error": "No active game"}, 400)
            else:
                self._json_response(game.get_state())
        elif self.path == "/api/kifu":
            if game is None:
                self._json_response({"error": "No active game"}, 400)
            else:
                self._json_response(game.kifu)
        elif self.path == "/api/kifu_list":
            KIFU_DIR.mkdir(exist_ok=True)
            files = sorted(KIFU_DIR.glob("kifu_*.json"), reverse=True)
            self._json_response([f.name for f in files[:50]])
        elif self.path.startswith("/api/kifu_load/"):
            name = self.path.split("/")[-1]
            path = KIFU_DIR / name
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    self._json_response(json.load(f))
            else:
                self._json_response({"error": "Not found"}, 404)
        else:
            self.send_error(404)

    def _handle_api_post(self):
        global game
        body = self._read_body()

        if self.path == "/api/new_game":
            rounds = body.get("rounds", 12)
            rules = body.get("rules")
            game = GameSession(total_rounds=rounds, rules=rules)
            self._json_response(game.get_state())

        elif self.path == "/api/action":
            if game is None:
                self._json_response({"error": "No active game"}, 400)
                return
            action = body.get("action")
            if action is None:
                self._json_response({"error": "No action"}, 400)
                return
            game.do_action(int(action))
            self._json_response(game.get_state())

        elif self.path == "/api/next_round":
            if game is None:
                self._json_response({"error": "No active game"}, 400)
                return
            ok = game.next_round()
            resp = game.get_state()
            resp["round_started"] = ok
            self._json_response(resp)

        elif self.path == "/api/save_kifu":
            if game is None:
                self._json_response({"error": "No active game"}, 400)
                return
            path = game.save_kifu()
            self._json_response({"path": path})

        else:
            self.send_error(404)

    def log_message(self, format, *args):
        if "/api/" in (args[0] if args else ""):
            return
        super().log_message(format, *args)


def main():
    port = 8800
    server = HTTPServer(("", port), GameHandler)
    print(f"花札こいこい Web GUI")
    print(f"http://localhost:{port}")
    print("Ctrl+C で終了")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了")
        server.server_close()


if __name__ == "__main__":
    main()
