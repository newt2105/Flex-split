"""Rollout storage and generalized advantage estimation for PPO."""

from __future__ import annotations

from typing import Dict, Iterator

import numpy as np


class RolloutBuffer:
    def __init__(self, size: int, observation_dim: int, action_dim: int) -> None:
        self.size = int(size)
        self.observations = np.zeros((size, observation_dim), dtype=np.float32)
        self.action_masks = np.zeros((size, action_dim), dtype=np.bool_)
        self.actions = np.zeros(size, dtype=np.int64)
        self.log_probabilities = np.zeros(size, dtype=np.float32)
        self.values = np.zeros(size, dtype=np.float32)
        self.rewards = np.zeros(size, dtype=np.float32)
        self.dones = np.zeros(size, dtype=np.float32)
        self.advantages = np.zeros(size, dtype=np.float32)
        self.returns = np.zeros(size, dtype=np.float32)
        self.position = 0

    def add(
        self,
        observation: np.ndarray,
        action_mask: np.ndarray,
        action: int,
        log_probability: float,
        value: float,
        reward: float,
        done: bool,
    ) -> None:
        if self.position >= self.size:
            raise IndexError("The rollout buffer is already full.")
        idx = self.position
        self.observations[idx] = observation
        self.action_masks[idx] = action_mask
        self.actions[idx] = action
        self.log_probabilities[idx] = log_probability
        self.values[idx] = value
        self.rewards[idx] = reward
        self.dones[idx] = float(done)
        self.position += 1

    def compute_returns_and_advantages(
        self,
        last_value: float,
        gamma: float,
        gae_lambda: float,
    ) -> None:
        if self.position != self.size:
            raise RuntimeError("Compute advantages only after filling the rollout buffer.")

        last_advantage = 0.0
        for step in reversed(range(self.size)):
            next_non_terminal = 1.0 - self.dones[step]
            next_value = last_value if step == self.size - 1 else self.values[step + 1]
            delta = (
                self.rewards[step]
                + gamma * next_value * next_non_terminal
                - self.values[step]
            )
            last_advantage = (
                delta + gamma * gae_lambda * next_non_terminal * last_advantage
            )
            self.advantages[step] = last_advantage
        self.returns = self.advantages + self.values

    def batches(
        self,
        batch_size: int,
        rng: np.random.Generator,
    ) -> Iterator[Dict[str, np.ndarray]]:
        indices = rng.permutation(self.size)
        for start in range(0, self.size, batch_size):
            selected = indices[start : start + batch_size]
            yield {
                "observations": self.observations[selected],
                "action_masks": self.action_masks[selected],
                "actions": self.actions[selected],
                "old_log_probabilities": self.log_probabilities[selected],
                "old_values": self.values[selected],
                "advantages": self.advantages[selected],
                "returns": self.returns[selected],
            }
