"""MaskableRecurrentPPO - RecurrentPPO + action masking

RecurrentPPO (LSTM) と MaskablePPO (アクションマスキング) を組み合わせた
カスタム実装。花札のような不完全情報ゲームに最適。
"""

from copy import deepcopy
from typing import NamedTuple, Optional

import numpy as np
import torch as th
from gymnasium import spaces

from stable_baselines3.common.buffers import RolloutBuffer
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.utils import obs_as_tensor
from stable_baselines3.common.vec_env import VecEnv

from sb3_contrib import RecurrentPPO
from sb3_contrib.common.maskable.distributions import make_masked_proba_distribution
from sb3_contrib.common.maskable.utils import get_action_masks, is_masking_supported
from sb3_contrib.common.recurrent.buffers import RecurrentRolloutBuffer
from sb3_contrib.common.recurrent.type_aliases import RNNStates
from sb3_contrib.ppo_recurrent.policies import RecurrentActorCriticPolicy


class MaskableRecurrentSamples(NamedTuple):
    observations: th.Tensor
    actions: th.Tensor
    old_values: th.Tensor
    old_log_prob: th.Tensor
    advantages: th.Tensor
    returns: th.Tensor
    lstm_states: RNNStates
    episode_starts: th.Tensor
    mask: th.Tensor
    action_masks: th.Tensor


class MaskableRecurrentRolloutBuffer(RecurrentRolloutBuffer):
    """RecurrentRolloutBuffer + action mask storage"""

    def __init__(self, *args, mask_dims: int = 0, **kwargs):
        self.mask_dims = mask_dims
        super().__init__(*args, **kwargs)

    def reset(self):
        super().reset()
        self.action_masks = np.zeros(
            (self.buffer_size, self.n_envs, self.mask_dims), dtype=np.float32
        )

    def add(self, *args, action_masks=None, **kwargs):
        if action_masks is not None:
            self.action_masks[self.pos] = action_masks.reshape(self.n_envs, self.mask_dims)
        super().add(*args, **kwargs)

    def get(self, batch_size=None):
        assert self.full
        if not self.generator_ready:
            self.action_masks = self.swap_and_flatten(self.action_masks)
        yield from super().get(batch_size)

    def _get_samples(self, batch_inds, env_change, env=None):
        base = super()._get_samples(batch_inds, env_change, env)
        padded_masks = self.pad(self.action_masks[batch_inds])
        n_seq = len(self.seq_start_indices)
        max_length = padded_masks.shape[1]
        padded_masks = padded_masks.reshape(n_seq * max_length, self.mask_dims)
        return MaskableRecurrentSamples(
            observations=base.observations,
            actions=base.actions,
            old_values=base.old_values,
            old_log_prob=base.old_log_prob,
            advantages=base.advantages,
            returns=base.returns,
            lstm_states=base.lstm_states,
            episode_starts=base.episode_starts,
            mask=base.mask,
            action_masks=self.to_torch(padded_masks),
        )


class MaskableRecurrentPolicy(RecurrentActorCriticPolicy):
    """RecurrentActorCriticPolicy with action masking support"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.action_dist = make_masked_proba_distribution(self.action_space)

    def _get_action_dist_from_latent(self, latent_pi):
        mean_actions = self.action_net(latent_pi)
        return self.action_dist.proba_distribution(action_logits=mean_actions)

    def forward(self, obs, lstm_states, episode_starts, deterministic=False, action_masks=None):
        features = self.extract_features(obs)
        if self.share_features_extractor:
            pi_features = vf_features = features
        else:
            pi_features, vf_features = features

        latent_pi, lstm_states_pi = self._process_sequence(
            pi_features, lstm_states.pi, episode_starts, self.lstm_actor
        )
        if self.lstm_critic is not None:
            latent_vf, lstm_states_vf = self._process_sequence(
                vf_features, lstm_states.vf, episode_starts, self.lstm_critic
            )
        elif self.shared_lstm:
            latent_vf = latent_pi.detach()
            lstm_states_vf = (lstm_states_pi[0].detach(), lstm_states_pi[1].detach())
        else:
            latent_vf = self.critic(vf_features)
            lstm_states_vf = lstm_states_pi

        latent_pi = self.mlp_extractor.forward_actor(latent_pi)
        latent_vf = self.mlp_extractor.forward_critic(latent_vf)

        values = self.value_net(latent_vf)
        distribution = self._get_action_dist_from_latent(latent_pi)
        if action_masks is not None:
            distribution.apply_masking(action_masks)
        actions = distribution.get_actions(deterministic=deterministic)
        log_prob = distribution.log_prob(actions)
        return actions, values, log_prob, RNNStates(lstm_states_pi, lstm_states_vf)

    def evaluate_actions(self, obs, actions, lstm_states, episode_starts, action_masks=None):
        features = self.extract_features(obs)
        if self.share_features_extractor:
            pi_features = vf_features = features
        else:
            pi_features, vf_features = features

        latent_pi, _ = self._process_sequence(
            pi_features, lstm_states.pi, episode_starts, self.lstm_actor
        )
        if self.lstm_critic is not None:
            latent_vf, _ = self._process_sequence(
                vf_features, lstm_states.vf, episode_starts, self.lstm_critic
            )
        elif self.shared_lstm:
            latent_vf = latent_pi.detach()
        else:
            latent_vf = self.critic(vf_features)

        latent_pi = self.mlp_extractor.forward_actor(latent_pi)
        latent_vf = self.mlp_extractor.forward_critic(latent_vf)

        distribution = self._get_action_dist_from_latent(latent_pi)
        if action_masks is not None:
            distribution.apply_masking(action_masks)
        log_prob = distribution.log_prob(actions)
        values = self.value_net(latent_vf)
        return values, log_prob, distribution.entropy()

    def predict(self, observation, state=None, episode_start=None, deterministic=False,
                action_masks=None):
        self.set_training_mode(False)
        obs, vectorized_env = self.obs_to_tensor(observation)

        if isinstance(obs, dict):
            n_envs = obs[next(iter(obs.keys()))].shape[0]
        else:
            n_envs = obs.shape[0]

        if state is None:
            state = self._get_default_lstm_states(n_envs)

        if episode_start is None:
            episode_start = np.array([False] * n_envs)

        episode_start = th.tensor(episode_start, dtype=th.float32, device=self.device)

        with th.no_grad():
            lstm_states = RNNStates(
                (th.tensor(state[0][0], device=self.device), th.tensor(state[0][1], device=self.device)),
                (th.tensor(state[1][0], device=self.device), th.tensor(state[1][1], device=self.device)),
            )
            actions, _, _, new_lstm_states = self.forward(
                obs, lstm_states, episode_start,
                deterministic=deterministic, action_masks=action_masks,
            )

        new_state = (
            (new_lstm_states.pi[0].cpu().numpy(), new_lstm_states.pi[1].cpu().numpy()),
            (new_lstm_states.vf[0].cpu().numpy(), new_lstm_states.vf[1].cpu().numpy()),
        )

        actions = actions.cpu().numpy()
        if not vectorized_env:
            actions = actions.squeeze(axis=0)

        return actions, new_state

    def _get_default_lstm_states(self, n_envs):
        hsz = self.lstm_output_dim
        h_pi = th.zeros(self.lstm_actor.num_layers, n_envs, hsz, device=self.device)
        c_pi = th.zeros_like(h_pi)
        if self.lstm_critic is not None:
            h_vf = th.zeros(self.lstm_critic.num_layers, n_envs, hsz, device=self.device)
            c_vf = th.zeros_like(h_vf)
        elif self.shared_lstm:
            h_vf, c_vf = h_pi.clone(), c_pi.clone()
        else:
            h_vf = th.zeros(1, n_envs, hsz, device=self.device)
            c_vf = th.zeros_like(h_vf)

        return (
            (h_pi.cpu().numpy(), c_pi.cpu().numpy()),
            (h_vf.cpu().numpy(), c_vf.cpu().numpy()),
        )


class MaskableRecurrentPPO(RecurrentPPO):
    """RecurrentPPO with action masking support"""

    policy_aliases = {"MlpLstmPolicy": MaskableRecurrentPolicy}

    def predict(self, observation, state=None, episode_start=None,
                deterministic=False, action_masks=None):
        return self.policy.predict(
            observation, state, episode_start, deterministic,
            action_masks=action_masks,
        )

    def __init__(self, policy, env, **kwargs):
        if isinstance(policy, str):
            policy = self.policy_aliases.get(policy, policy)
        super().__init__(policy, env, **kwargs)

    def _setup_model(self):
        super()._setup_model()
        mask_dims = self.action_space.n if isinstance(self.action_space, spaces.Discrete) else 0
        lstm = self.policy.lstm_actor
        hidden_state_buffer_shape = (self.n_steps, lstm.num_layers, self.n_envs, lstm.hidden_size)
        self.rollout_buffer = MaskableRecurrentRolloutBuffer(
            self.n_steps,
            self.observation_space,
            self.action_space,
            hidden_state_buffer_shape,
            self.device,
            gamma=self.gamma,
            gae_lambda=self.gae_lambda,
            n_envs=self.n_envs,
            mask_dims=mask_dims,
        )

    def collect_rollouts(self, env, callback, rollout_buffer, n_rollout_steps):
        assert self._last_obs is not None
        self.policy.set_training_mode(False)

        n_steps = 0
        rollout_buffer.reset()

        if self.use_sde:
            self.policy.reset_noise(env.num_envs)

        callback.on_rollout_start()
        lstm_states = deepcopy(self._last_lstm_states)

        while n_steps < n_rollout_steps:
            if self.use_sde and self.sde_sample_freq > 0 and n_steps % self.sde_sample_freq == 0:
                self.policy.reset_noise(env.num_envs)

            action_masks = get_action_masks(env)

            with th.no_grad():
                obs_tensor = obs_as_tensor(self._last_obs, self.device)
                episode_starts = th.tensor(
                    self._last_episode_starts, dtype=th.float32, device=self.device
                )
                actions, values, log_probs, lstm_states = self.policy.forward(
                    obs_tensor, lstm_states, episode_starts, action_masks=action_masks,
                )

            actions_np = actions.cpu().numpy()
            clipped_actions = actions_np
            if isinstance(self.action_space, spaces.Box):
                clipped_actions = np.clip(actions_np, self.action_space.low, self.action_space.high)

            new_obs, rewards, dones, infos = env.step(clipped_actions)
            self.num_timesteps += env.num_envs

            callback.update_locals(locals())
            if not callback.on_step():
                return False

            self._update_info_buffer(infos, dones)
            n_steps += 1

            if isinstance(self.action_space, spaces.Discrete):
                actions_np = actions_np.reshape(-1, 1)

            for idx, done_ in enumerate(dones):
                if (
                    done_
                    and infos[idx].get("terminal_observation") is not None
                    and infos[idx].get("TimeLimit.truncated", False)
                ):
                    terminal_obs = self.policy.obs_to_tensor(infos[idx]["terminal_observation"])[0]
                    with th.no_grad():
                        terminal_lstm_state = (
                            lstm_states.vf[0][:, idx:idx + 1, :].contiguous(),
                            lstm_states.vf[1][:, idx:idx + 1, :].contiguous(),
                        )
                        ep_starts = th.tensor([False], dtype=th.float32, device=self.device)
                        terminal_value = self.policy.predict_values(
                            terminal_obs, terminal_lstm_state, ep_starts
                        )[0]
                    rewards[idx] += self.gamma * terminal_value

            rollout_buffer.add(
                self._last_obs,
                actions_np,
                rewards,
                self._last_episode_starts,
                values,
                log_probs,
                lstm_states=self._last_lstm_states,
                action_masks=action_masks,
            )

            self._last_obs = new_obs
            self._last_episode_starts = dones
            self._last_lstm_states = lstm_states

        with th.no_grad():
            episode_starts = th.tensor(dones, dtype=th.float32, device=self.device)
            values = self.policy.predict_values(
                obs_as_tensor(new_obs, self.device), lstm_states.vf, episode_starts
            )

        rollout_buffer.compute_returns_and_advantage(last_values=values, dones=dones)
        callback.on_rollout_end()
        return True

    def train(self):
        self.policy.set_training_mode(True)
        self._update_learning_rate(self.policy.optimizer)
        clip_range = self.clip_range(self._current_progress_remaining)
        if self.clip_range_vf is not None:
            clip_range_vf = self.clip_range_vf(self._current_progress_remaining)

        entropy_losses, pg_losses, value_losses = [], [], []
        clip_fractions = []
        continue_training = True

        for epoch in range(self.n_epochs):
            approx_kl_divs = []
            for rollout_data in self.rollout_buffer.get(self.batch_size):
                actions = rollout_data.actions
                if isinstance(self.action_space, spaces.Discrete):
                    actions = rollout_data.actions.long().flatten()

                seq_mask = rollout_data.mask > 1e-8

                values, log_prob, entropy = self.policy.evaluate_actions(
                    rollout_data.observations,
                    actions,
                    rollout_data.lstm_states,
                    rollout_data.episode_starts,
                    action_masks=rollout_data.action_masks,
                )

                values = values.flatten()
                advantages = rollout_data.advantages
                if self.normalize_advantage:
                    advantages = (advantages - advantages[seq_mask].mean()) / (
                        advantages[seq_mask].std() + 1e-8
                    )

                ratio = th.exp(log_prob - rollout_data.old_log_prob)
                policy_loss_1 = advantages * ratio
                policy_loss_2 = advantages * th.clamp(ratio, 1 - clip_range, 1 + clip_range)
                policy_loss = -th.mean(th.min(policy_loss_1, policy_loss_2)[seq_mask])

                pg_losses.append(policy_loss.item())
                clip_fraction = th.mean((th.abs(ratio - 1) > clip_range).float()[seq_mask]).item()
                clip_fractions.append(clip_fraction)

                if self.clip_range_vf is None:
                    values_pred = values
                else:
                    values_pred = rollout_data.old_values + th.clamp(
                        values - rollout_data.old_values, -clip_range_vf, clip_range_vf
                    )

                value_loss = th.mean(((rollout_data.returns - values_pred) ** 2)[seq_mask])
                value_losses.append(value_loss.item())

                if entropy is None:
                    entropy_loss = -th.mean(-log_prob[seq_mask])
                else:
                    entropy_loss = -th.mean(entropy[seq_mask])
                entropy_losses.append(entropy_loss.item())

                loss = policy_loss + self.ent_coef * entropy_loss + self.vf_coef * value_loss

                with th.no_grad():
                    log_ratio = log_prob - rollout_data.old_log_prob
                    approx_kl_div = th.mean(
                        ((th.exp(log_ratio) - 1) - log_ratio)[seq_mask]
                    ).cpu().numpy()
                    approx_kl_divs.append(approx_kl_div)

                if self.target_kl is not None and approx_kl_div > 1.5 * self.target_kl:
                    continue_training = False
                    if self.verbose >= 1:
                        print(f"Early stopping at step {epoch} due to reaching max kl: {approx_kl_div:.2f}")
                    break

                self.policy.optimizer.zero_grad()
                loss.backward()
                th.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
                self.policy.optimizer.step()

            if not continue_training:
                break

        self._n_updates += self.n_epochs
        from stable_baselines3.common.utils import explained_variance
        explained_var = explained_variance(
            self.rollout_buffer.values.flatten(), self.rollout_buffer.returns.flatten()
        )

        self.logger.record("train/entropy_loss", np.mean(entropy_losses))
        self.logger.record("train/policy_gradient_loss", np.mean(pg_losses))
        self.logger.record("train/value_loss", np.mean(value_losses))
        self.logger.record("train/approx_kl", np.mean(approx_kl_divs))
        self.logger.record("train/clip_fraction", np.mean(clip_fractions))
        self.logger.record("train/loss", loss.item())
        self.logger.record("train/explained_variance", explained_var)
        self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        self.logger.record("train/clip_range", clip_range)
        if self.clip_range_vf is not None:
            self.logger.record("train/clip_range_vf", clip_range_vf)
