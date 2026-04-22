"""花札こいこい - Gymnasium環境

MaskablePPO (sb3-contrib) と組み合わせて使う。
エージェントはplayer 0を操作し、相手はopponent_policyで制御される。

使い方:
    from env import KoikoiEnv

    env = KoikoiEnv(opponent_policy="rule")
    obs, info = env.reset()

    while True:
        mask = env.action_masks()
        action = your_policy(obs, mask)
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated:
            break
"""

from typing import Callable, Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from engine import (
    ACTION_KOIKOI,
    ACTION_SHOWDOWN,
    NUM_ACTIONS,
    OBS_SIZE,
    KoikoiEngine,
    Phase,
    rule_based_policy,
)


class KoikoiEnv(gym.Env):
    """花札こいこい1ラウンドの強化学習環境

    Observation: float32 (340,) - エンジンのget_observation参照
    Action: Discrete(50) - カードID 0-47 / 48=こいこい / 49=勝負
    Action masking: action_masks() で合法手マスクを取得
    """

    metadata = {"render_modes": ["ansi"]}

    def __init__(
        self,
        opponent_policy: str = "random",
        render_mode: Optional[str] = None,
    ):
        super().__init__()
        self.engine = KoikoiEngine()
        self.agent_idx = 0
        self.render_mode = render_mode

        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(OBS_SIZE,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(NUM_ACTIONS)

        self._opponent_fn: Callable = self._random_opponent
        self.set_opponent(opponent_policy)

    def set_opponent(self, policy) -> None:
        """対戦相手を設定する。

        policy: "random" / "rule" / callable(engine, player_idx) -> action
        """
        if policy == "random":
            self._opponent_fn = self._random_opponent
        elif policy == "rule":
            self._opponent_fn = self._rule_opponent
        elif callable(policy):
            self._opponent_fn = policy
        else:
            raise ValueError(f"Unknown opponent policy: {policy}")

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        rng_seed = int(self.np_random.integers(0, 2**31))

        while True:
            oya = int(self.np_random.integers(0, 2))
            info = self.engine.reset(oya=oya, seed=rng_seed)
            rng_seed += 1
            special = info.get("special")
            if special == "redeal" or self.engine.done:
                continue
            self._play_opponent_turns()
            if not self.engine.done:
                break

        obs = self.engine.get_observation(self.agent_idx)
        return obs, self._make_info()

    def step(self, action):
        action = int(action)
        if self.engine.done or self.engine.current_player != self.agent_idx:
            obs = self.engine.get_observation(self.agent_idx)
            return obs, 0.0, True, False, self._make_info()

        self.engine.step(action)

        if not self.engine.done:
            self._play_opponent_turns()

        obs = self.engine.get_observation(self.agent_idx)
        reward = self._compute_reward()
        terminated = self.engine.done

        return obs, reward, terminated, False, self._make_info()

    def action_masks(self) -> np.ndarray:
        if self.engine.done or self.engine.current_player != self.agent_idx:
            return np.ones(NUM_ACTIONS, dtype=bool)
        return self.engine.get_action_mask()

    def render(self):
        if self.render_mode == "ansi":
            return self._render_ansi()
        return None

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _play_opponent_turns(self):
        opp = 1 - self.agent_idx
        while not self.engine.done and self.engine.current_player == opp:
            action = self._opponent_fn(self.engine, opp)
            self.engine.step(action)

    def _compute_reward(self) -> float:
        if not self.engine.done:
            return 0.0
        if self.engine.winner is None:
            return 0.0
        score = self.engine.win_score / 30.0
        if self.engine.winner == self.agent_idx:
            return score
        else:
            return -score

    def _make_info(self) -> dict:
        return {
            "phase": self.engine.phase.name,
            "legal_actions": self.engine.get_legal_actions(),
            "winner": self.engine.winner,
            "win_score": self.engine.win_score,
        }

    def _render_ansi(self) -> str:
        e = self.engine
        lines = [f"Phase: {e.phase.name}  Player: {e.current_player}"]
        lines.append(f"Field ({len(e.field)}): " + " ".join(str(c) for c in e.field))
        for pi in range(2):
            tag = "Agent" if pi == self.agent_idx else "Opp"
            lines.append(f"{tag} hand ({len(e.players_hand[pi])}): " +
                         " ".join(str(c) for c in e.players_hand[pi]))
            lines.append(f"{tag} captured ({len(e.players_captured[pi])}): " +
                         " ".join(str(c) for c in e.players_captured[pi]))
        return "\n".join(lines)

    @staticmethod
    def _random_opponent(engine: KoikoiEngine, player_idx: int) -> int:
        import random as _rnd
        return _rnd.choice(engine.get_legal_actions())

    @staticmethod
    def _rule_opponent(engine: KoikoiEngine, player_idx: int) -> int:
        return rule_based_policy(engine, player_idx)
