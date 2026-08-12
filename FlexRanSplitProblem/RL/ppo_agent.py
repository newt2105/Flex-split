"""A small, dependency-light implementation of action-masked PPO."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np

try:
    import torch
    from torch import nn
except ImportError as exc:  # pragma: no cover - clear message for end users.
    raise ImportError(
        "PyTorch is required for the PPO agent. Install RL/requirements.txt."
    ) from exc

from .model import MaskedActorCritic
from .rollout import RolloutBuffer


@dataclass
class PPOConfig:
    learning_rate: float = 3e-4
    rollout_steps: int = 512
    batch_size: int = 64
    update_epochs: int = 10
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    entropy_coefficient: float = 0.01
    value_coefficient: float = 0.5
    max_grad_norm: float = 0.5
    hidden_sizes: Tuple[int, ...] = (128, 128)
    seed: int = 0
    device: str = "auto"


class MaskedPPOAgent:
    """PPO agent whose categorical policy assigns zero mass to invalid actions."""

    def __init__(
        self,
        observation_dim: int,
        action_dim: int,
        config: Optional[PPOConfig] = None,
    ) -> None:
        self.observation_dim = int(observation_dim)
        self.action_dim = int(action_dim)
        self.config = config or PPOConfig()
        self.device = self._resolve_device(self.config.device)
        self._set_seed(self.config.seed)
        self._rng = np.random.default_rng(self.config.seed)

        self.model = MaskedActorCritic(
            observation_dim=self.observation_dim,
            action_dim=self.action_dim,
            hidden_sizes=self.config.hidden_sizes,
        ).to(self.device)
        self.optimizer = torch.optim.Adam(
            self.model.parameters(), lr=self.config.learning_rate
        )
        self.checkpoint_metadata: Dict[str, Any] = {}

    def select_action(
        self,
        observation: np.ndarray,
        action_mask: np.ndarray,
        deterministic: bool = False,
    ) -> Tuple[int, float, float]:
        observations = self._tensor(observation).unsqueeze(0)
        masks = self._tensor(action_mask, dtype=torch.bool).unsqueeze(0)
        with torch.no_grad():
            distribution, value = self.model.distribution_and_value(observations, masks)
            action = (
                torch.argmax(distribution.logits, dim=-1)
                if deterministic
                else distribution.sample()
            )
            log_probability = distribution.log_prob(action)
        return int(action.item()), float(log_probability.item()), float(value.item())

    def predict_value(self, observation: np.ndarray) -> float:
        observations = self._tensor(observation).unsqueeze(0)
        with torch.no_grad():
            _, value = self.model(observations)
        return float(value.item())

    def train(
        self,
        env: Any,
        total_timesteps: int,
        callback: Optional[Callable[[Dict[str, float]], None]] = None,
    ) -> Dict[str, float]:
        """Train on a single environment and return the final update metrics."""

        if env.observation_dim != self.observation_dim:
            raise ValueError("Environment and agent observation dimensions differ.")
        if env.action_dim != self.action_dim:
            raise ValueError("Environment and agent action dimensions differ.")
        if total_timesteps <= 0:
            raise ValueError("total_timesteps must be positive.")

        observation, _ = env.reset(seed=self.config.seed)
        timesteps = 0
        episodes = 0
        final_metrics: Dict[str, float] = {}

        while timesteps < total_timesteps:
            rollout_size = min(self.config.rollout_steps, total_timesteps - timesteps)
            buffer = RolloutBuffer(
                rollout_size,
                observation_dim=self.observation_dim,
                action_dim=self.action_dim,
            )
            last_done = False

            for _ in range(rollout_size):
                action_mask = env.action_masks()
                action, log_probability, value = self.select_action(
                    observation, action_mask, deterministic=False
                )
                next_observation, reward, terminated, truncated, info = env.step(action)
                done = bool(terminated or truncated)
                buffer.add(
                    observation=observation,
                    action_mask=action_mask,
                    action=action,
                    log_probability=log_probability,
                    value=value,
                    reward=reward,
                    done=done,
                )
                observation = next_observation
                timesteps += 1
                last_done = done

                if done:
                    episodes += 1
                    observation, _ = env.reset()

            last_value = 0.0 if last_done else self.predict_value(observation)
            buffer.compute_returns_and_advantages(
                last_value=last_value,
                gamma=self.config.gamma,
                gae_lambda=self.config.gae_lambda,
            )
            final_metrics = self._update(buffer)
            final_metrics.update(
                {
                    "timesteps": float(timesteps),
                    "episodes": float(episodes),
                }
            )
            if callback is not None:
                callback(dict(final_metrics))

        return final_metrics

    def save(self, path: str | Path, metadata: Optional[Dict[str, Any]] = None) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "observation_dim": self.observation_dim,
            "action_dim": self.action_dim,
            "config": asdict(self.config),
            "model_state": self.model.state_dict(),
            "optimizer_state": self.optimizer.state_dict(),
            "metadata": metadata or {},
        }
        torch.save(payload, destination)

    @classmethod
    def load(
        cls,
        path: str | Path,
        device: Optional[str] = None,
        load_optimizer: bool = False,
    ) -> "MaskedPPOAgent":
        map_location = cls._resolve_device(device or "auto")
        payload = torch.load(Path(path), map_location=map_location)
        config_data = dict(payload["config"])
        config_data["hidden_sizes"] = tuple(config_data["hidden_sizes"])
        config_data["device"] = str(map_location)
        agent = cls(
            observation_dim=int(payload["observation_dim"]),
            action_dim=int(payload["action_dim"]),
            config=PPOConfig(**config_data),
        )
        agent.model.load_state_dict(payload["model_state"])
        if load_optimizer and "optimizer_state" in payload:
            agent.optimizer.load_state_dict(payload["optimizer_state"])
        agent.checkpoint_metadata = dict(payload.get("metadata", {}))
        return agent

    def _update(self, buffer: RolloutBuffer) -> Dict[str, float]:
        advantages = buffer.advantages
        buffer.advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        totals = {
            "policy_loss": 0.0,
            "value_loss": 0.0,
            "entropy": 0.0,
            "approx_kl": 0.0,
            "clip_fraction": 0.0,
        }
        updates = 0

        for _ in range(self.config.update_epochs):
            for batch in buffer.batches(self.config.batch_size, self._rng):
                observations = self._tensor(batch["observations"])
                action_masks = self._tensor(batch["action_masks"], dtype=torch.bool)
                actions = self._tensor(batch["actions"], dtype=torch.long)
                old_log_probabilities = self._tensor(batch["old_log_probabilities"])
                batch_advantages = self._tensor(batch["advantages"])
                returns = self._tensor(batch["returns"])

                distribution, values = self.model.distribution_and_value(
                    observations, action_masks
                )
                new_log_probabilities = distribution.log_prob(actions)
                entropy = distribution.entropy().mean()
                log_ratio = new_log_probabilities - old_log_probabilities
                ratio = torch.exp(log_ratio)

                unclipped = ratio * batch_advantages
                clipped = torch.clamp(
                    ratio,
                    1.0 - self.config.clip_range,
                    1.0 + self.config.clip_range,
                ) * batch_advantages
                policy_loss = -torch.min(unclipped, clipped).mean()
                value_loss = 0.5 * torch.mean((returns - values) ** 2)
                loss = (
                    policy_loss
                    + self.config.value_coefficient * value_loss
                    - self.config.entropy_coefficient * entropy
                )

                self.optimizer.zero_grad(set_to_none=True)
                loss.backward()
                nn.utils.clip_grad_norm_(
                    self.model.parameters(), self.config.max_grad_norm
                )
                self.optimizer.step()

                with torch.no_grad():
                    approx_kl = torch.mean((ratio - 1.0) - log_ratio)
                    clip_fraction = torch.mean(
                        (torch.abs(ratio - 1.0) > self.config.clip_range).float()
                    )

                totals["policy_loss"] += float(policy_loss.item())
                totals["value_loss"] += float(value_loss.item())
                totals["entropy"] += float(entropy.item())
                totals["approx_kl"] += float(approx_kl.item())
                totals["clip_fraction"] += float(clip_fraction.item())
                updates += 1

        return {key: value / max(1, updates) for key, value in totals.items()}

    def _tensor(
        self,
        value: Any,
        dtype: Optional[torch.dtype] = torch.float32,
    ) -> torch.Tensor:
        return torch.as_tensor(value, dtype=dtype, device=self.device)

    @staticmethod
    def _resolve_device(device: str) -> torch.device:
        if device == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.device(device)

    @staticmethod
    def _set_seed(seed: int) -> None:
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
