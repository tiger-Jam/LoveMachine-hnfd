#!/usr/bin/env python3
"""花札こいこい - Web GUI サーバー

使い方:
    python3 web.py
    ブラウザで http://localhost:8800 を開く
"""

import json
import os
import random as _random
import secrets
import time
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from core import (
    HIKARI, TANE, TANZAKU, KASU, MONTHS,
    Card, check_yaku, total_yaku_points,
)
from engine import (
    KoikoiEngine, Phase, rule_based_policy,
    ACTION_KOIKOI, ACTION_SHOWDOWN, NUM_CARDS,
)

STATIC_DIR = Path(__file__).parent / "static"
KIFU_DIR = Path(__file__).parent / "kifu"

KIFU_VERSION = 2


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def card_info(c: Card) -> dict:
    """Full card metadata — used in initial_deal where fan-out matters."""
    return {
        "id": c.id,
        "name": c.name,
        "month": c.month,
        "card_type": c.card_type,
        "tanzaku_type": c.tanzaku_type,
    }


def cards_info(cards) -> list:
    return [card_info(c) for c in cards]


def card_ref(c: Card) -> dict:
    """Compact card reference — id + name for quick read/scan."""
    return {"id": c.id, "name": c.name}


def cards_ref(cards) -> list:
    return [card_ref(c) for c in cards]


class GameSession:
    def __init__(self, total_rounds=12, opponent="rule", rules=None):
        self.engine = KoikoiEngine(rules=rules)
        self.rules = dict(self.engine.rules)
        self.total_rounds = total_rounds
        self.current_round = 1
        self.scores = [0, 0]
        self.oya = 0
        self.opponent = opponent
        self._session_rng = _random.Random(secrets.randbits(64))

        # Session identity + kifu path
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.session_id = f"{ts}_{secrets.token_hex(2)}"
        KIFU_DIR.mkdir(exist_ok=True)
        self.kifu_path = KIFU_DIR / f"kifu_{self.session_id}.json"

        self.kifu = {
            "version": KIFU_VERSION,
            "session_id": self.session_id,
            "created_at": _now_iso(),
            "finished_at": None,
            "status": "in_progress",
            "total_rounds": total_rounds,
            "rules": dict(self.rules),
            "opponent_type": opponent,
            "scores": [0, 0],
            "winner": None,
            "rounds": [],
        }

        # Per-round mutable state — the "in-flight" round entry we append
        # to kifu["rounds"] at start and fill in as play proceeds.
        self._round_entry = None
        self._round_decisions = []

        self._last_transitions = []
        self._round_fresh = True
        self._deal_snapshot = None

        self._start_round()

    # ------------------------------------------------------------------
    # Round lifecycle
    # ------------------------------------------------------------------

    def _start_round(self):
        seed = None
        redeals = 0
        while True:
            seed = self._session_rng.randint(0, 2**31 - 1)
            info = self.engine.reset(oya=self.oya, seed=seed)
            special = info.get("special")
            if special == "redeal":
                redeals += 1
                continue
            break

        self._round_decisions = []
        self._round_fresh = True
        self._round_entry = {
            "round": self.current_round,
            "oya": self.oya,
            "seed": seed,
            "redeals": redeals,
            "started_at": _now_iso(),
            "finished_at": None,
            "special": special if special else None,
            "initial_deal": {
                "player_hand": cards_info(self.engine.players_hand[0]),
                "opponent_hand": cards_info(self.engine.players_hand[1]),
                "field": cards_info(self.engine.field),
                "deck_order": cards_info(self.engine.deck),
            },
            "decisions": self._round_decisions,
            "winner": None,
            "score": 0,
            "end_reason": None,
            "yaku_at_end": {"player": [], "opponent": []},
        }
        self.kifu["rounds"].append(self._round_entry)

        # Capture the freshly-dealt snapshot so the client can animate
        # a deal from the deck before any opponent-oya moves are played.
        self._deal_snapshot = self._snapshot()

        if self.engine.done:
            # teshi / kuttsuki — round already decided at deal time
            self._finish_round(end_reason="special")
            self._last_transitions = []
            self._auto_save()
            return

        # If the opponent is the oya, their first turn is computed now
        # but delivered in transitions so the client plays them after
        # the deal animation finishes.
        opening_transitions: list = []
        if not self.engine.done:
            self._play_opponent_if_needed(opening_transitions)
        self._last_transitions = opening_transitions

        if self.engine.done:
            self._finish_round(end_reason=self._infer_end_reason())

        self._auto_save()

    def _snapshot(self):
        e = self.engine
        pending = e._pending_played.id if e._pending_played is not None else None
        return {
            "hand": sorted([c.id for c in e.players_hand[0]]),
            "field": sorted([c.id for c in e.field], key=lambda i: e.card_by_id(i).month),
            "player_captured": sorted([c.id for c in e.players_captured[0]]),
            "opponent_captured": sorted([c.id for c in e.players_captured[1]]),
            "opponent_hand_count": len(e.players_hand[1]),
            "deck_remaining": len(e.deck),
            "phase": e.phase.name,
            "current_player": e.current_player,
            "pending_card": pending,
            "done": e.done,
        }

    @staticmethod
    def _serialize_events(raw_events):
        out = []
        for ev in raw_events:
            kind = ev[0]
            rest = ev[1:]
            if kind in ("hand_no_match", "draw"):
                out.append({"type": kind, "card": rest[0]})
            elif kind in ("hand_match", "draw_match"):
                out.append({"type": kind, "card": rest[0], "matched": rest[1]})
            elif kind in ("hand_match_all", "draw_match_all"):
                out.append({"type": kind, "card": rest[0], "matched": list(rest[1])})
            elif kind in ("hand_choose", "draw_choose"):
                out.append({"type": kind, "card": rest[0], "candidates": list(rest[1])})
            elif kind == "yaku_formed":
                out.append({
                    "type": kind,
                    "player": rest[0],
                    "yaku": [list(y) for y in rest[1]],
                    "points": rest[2],
                })
            elif kind == "koikoi":
                out.append({"type": kind, "player": rest[0]})
            elif kind == "showdown":
                out.append({"type": kind, "player": rest[0], "points": rest[1]})
            elif kind == "round_end":
                out.append({"type": kind, "winner": rest[0], "points": rest[1]})
            elif kind == "exhausted":
                out.append({"type": kind})
            elif kind == "bonus_7plus":
                out.append({"type": kind})
            elif kind == "bonus_opponent_koikoi":
                out.append({"type": kind})
            else:
                out.append({"type": kind, "args": list(rest)})
        return out

    def _decision_view(self, actor):
        """Snapshot of what `actor` sees at decision time (pre-step)."""
        e = self.engine
        opp = 1 - actor
        pending = None
        if e._pending_played is not None:
            pending = card_ref(e._pending_played)
        return {
            "self_hand": cards_ref(e.players_hand[actor]),
            "field": cards_ref(e.field),
            "self_captured": cards_ref(e.players_captured[actor]),
            "opponent_captured": cards_ref(e.players_captured[opp]),
            "opponent_hand_count": len(e.players_hand[opp]),
            "deck_remaining": len(e.deck),
            "self_yaku": [[n, p] for n, p in check_yaku(e.players_captured[actor], self.rules)],
            "opponent_yaku": [[n, p] for n, p in check_yaku(e.players_captured[opp], self.rules)],
            "self_koikoi": bool(e.players_koikoi[actor]),
            "opponent_koikoi": bool(e.players_koikoi[opp]),
            "pending_card": pending,
        }

    def _decision_hidden(self, actor):
        """Ground truth the actor cannot see — for oracle-guided analysis."""
        e = self.engine
        opp = 1 - actor
        return {
            "opponent_hand": cards_ref(e.players_hand[opp]),
        }

    def _action_info(self, phase_before: str, action: int) -> dict:
        if action == ACTION_KOIKOI:
            return {"kind": "koikoi"}
        if action == ACTION_SHOWDOWN:
            return {"kind": "showdown"}
        card = self.engine.card_by_id(action)
        if phase_before in ("HAND_MATCH", "DRAW_MATCH"):
            kind = "match_pick"
        else:
            kind = "play_card"
        return {"kind": kind, "id": card.id, "name": card.name}

    def _do_step(self, actor, action, transitions):
        phase_before = self.engine.phase.name

        # Capture decision context BEFORE stepping.
        visible = self._decision_view(actor)
        hidden = self._decision_hidden(actor)
        legal = list(self.engine.get_legal_actions())
        act_info = self._action_info(phase_before, action)

        # Step
        info = self.engine.step(action)
        events = self._serialize_events(info.get("events", []))

        # Record decision in kifu
        self._round_decisions.append({
            "index": len(self._round_decisions),
            "player": actor,
            "phase": phase_before,
            "visible": visible,
            "hidden": hidden,
            "legal_actions": legal,
            "action": act_info,
            "events": events,
        })

        # Record transition for the client animation layer
        card_id = action if action < NUM_CARDS else None
        if action < NUM_CARDS:
            card_name = self.engine.card_by_id(action).name
        elif action == ACTION_KOIKOI:
            card_name = "こいこい"
        elif action == ACTION_SHOWDOWN:
            card_name = "勝負"
        else:
            card_name = None
        transitions.append({
            "actor": actor,
            "phase_before": phase_before,
            "action": action,
            "card_id": card_id,
            "card_name": card_name,
            "events": events,
            "snapshot": self._snapshot(),
        })

    def _play_opponent_if_needed(self, transitions):
        while (not self.engine.done and
               self.engine.current_player == 1):
            action = self._get_opponent_action()
            self._do_step(1, action, transitions)

    def _get_opponent_action(self):
        return rule_based_policy(self.engine, 1)

    def do_action(self, action):
        transitions = []
        self._do_step(0, action, transitions)

        if not self.engine.done:
            self._play_opponent_if_needed(transitions)

        if self.engine.done:
            self._finish_round(end_reason=self._infer_end_reason())

        self._last_transitions = transitions
        self._round_fresh = False
        self._auto_save()
        return transitions

    def _infer_end_reason(self) -> str:
        """Infer end reason from the last events on the final decision."""
        if not self._round_decisions:
            return "special"
        last_events = self._round_decisions[-1].get("events", [])
        for ev in last_events:
            if ev.get("type") == "showdown":
                return "showdown"
            if ev.get("type") == "exhausted":
                # Distinguish 流局 (no yaku at all) from a koikoi-wins-by-exhaust.
                return "ryuukyoku" if getattr(self.engine, "ryuukyoku", False) else "exhausted"
        return "unknown"

    def _finish_round(self, end_reason: str):
        winner = self.engine.winner
        score = self.engine.win_score
        if winner is not None:
            self.scores[winner] += score

        p0_yaku = check_yaku(self.engine.players_captured[0], self.rules)
        p1_yaku = check_yaku(self.engine.players_captured[1], self.rules)

        self._round_entry["winner"] = winner
        self._round_entry["score"] = score
        self._round_entry["end_reason"] = end_reason
        self._round_entry["finished_at"] = _now_iso()
        self._round_entry["yaku_at_end"] = {
            "player": [[n, p] for n, p in p0_yaku],
            "opponent": [[n, p] for n, p in p1_yaku],
        }

        self.kifu["scores"] = list(self.scores)

        if self.current_round >= self.total_rounds:
            self._finalize_session()

    def _finalize_session(self):
        self.kifu["status"] = "completed"
        self.kifu["finished_at"] = _now_iso()
        self.kifu["scores"] = list(self.scores)
        s0, s1 = self.scores
        if s0 > s1:
            self.kifu["winner"] = 0
        elif s1 > s0:
            self.kifu["winner"] = 1
        else:
            self.kifu["winner"] = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _auto_save(self):
        KIFU_DIR.mkdir(exist_ok=True)
        tmp = self.kifu_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.kifu, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.kifu_path)

    def next_round(self):
        if self.current_round >= self.total_rounds:
            return False
        if self.engine.winner is not None:
            self.oya = self.engine.winner
        elif getattr(self.engine, "ryuukyoku_oya_swap", False):
            # 流局 "change" rule: no winner but 親 rotates.
            self.oya = 1 - self.oya
        # else: winner=None without swap → 親 unchanged
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
            "current_player": e.current_player,
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
            "transitions": getattr(self, "_last_transitions", []),
            "round_fresh": getattr(self, "_round_fresh", False),
            "deal_snapshot": getattr(self, "_deal_snapshot", None),
        }

    def save_kifu(self):
        # The kifu is continuously auto-saved; this endpoint just
        # confirms the current on-disk path for the user's session.
        self._auto_save()
        return str(self.kifu_path)


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
        suffix = path.suffix.lower()
        is_text = True
        if suffix == ".css":
            ct = "text/css"
        elif suffix == ".js":
            ct = "application/javascript"
        elif suffix == ".json":
            ct = "application/json"
        elif suffix == ".webmanifest":
            ct = "application/manifest+json"
        elif suffix == ".svg":
            ct = "image/svg+xml"
        elif suffix == ".png":
            ct = "image/png"; is_text = False
        elif suffix == ".ico":
            ct = "image/x-icon"; is_text = False
        else:
            ct = "text/html"
        if is_text:
            self.send_header("Content-Type", f"{ct}; charset=utf-8")
        else:
            self.send_header("Content-Type", ct)
        self.send_header("Content-Length", len(content))
        if suffix in (".svg", ".png", ".ico"):
            self.send_header("Cache-Control", "public, max-age=86400")
        elif suffix == ".webmanifest":
            self.send_header("Cache-Control", "public, max-age=3600")
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
