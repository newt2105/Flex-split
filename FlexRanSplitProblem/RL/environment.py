"""Sequential, action-masked environment for Flexible RAN Split."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .catalog import ActionCatalog, CandidateAction

try:  # Gymnasium is convenient but not required by the custom PPO agent.
    import gymnasium as gym
    from gymnasium import spaces

    _EnvBase = gym.Env
except ImportError:  # pragma: no cover - exercised only without Gymnasium.
    gym = None
    spaces = None

    class _EnvBase:  # type: ignore[no-redef]
        pass


@dataclass(frozen=True)
class RewardConfig:
    """Reward weights.

    The default exactly counts admitted RUs. A small ``latency_weight`` can be
    enabled as a tie-breaker after the admission-only policy works well.
    """

    admission_reward: float = 1.0
    rejection_reward: float = 0.0
    latency_weight: float = 0.0


class FlexRanSplitEnv(_EnvBase):
    """Allocate one RU per step using a DRC/path action.

    Observation layout::

        [progress,
         one_hot(current_RU_node),
         remaining_CPU / initial_CPU,
         remaining_BW / initial_BW]

    The observation therefore contains the current RU and residual resources,
    matching the simple state definition used in the project discussion.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        problem: Any,
        reward_config: Optional[RewardConfig] = None,
        shuffle_rus: bool = False,
        capacity_tolerance: float = 1e-6,
    ) -> None:
        super().__init__()
        self.problem = problem
        self.catalog = ActionCatalog(problem)
        self.reward_config = reward_config or RewardConfig()
        self.shuffle_rus = bool(shuffle_rus)
        self.capacity_tolerance = float(capacity_tolerance)

        self.observation_dim = (
            1 + 2 * len(self.catalog.node_ids) + len(self.catalog.edge_ids)
        )
        self.action_dim = self.catalog.action_count

        if spaces is not None:
            self.observation_space = spaces.Box(
                low=0.0,
                high=1.0,
                shape=(self.observation_dim,),
                dtype=np.float32,
            )
            self.action_space = spaces.Discrete(self.action_dim)

        self._rng = np.random.default_rng()
        self._ru_order: List[Any] = []
        self._position = 0
        self._remaining_cpu = self.catalog.node_capacities.copy()
        self._remaining_bandwidth = self.catalog.edge_capacities.copy()
        self._allocations: List[Dict[str, Any]] = []
        self._episode_reward = 0.0
        self._terminated = False
        self._max_latency = max(
            (candidate.latency for ru_id in self.catalog.ru_ids
             for candidate in self.catalog.candidates_for_ru(ru_id).values()),
            default=1.0,
        )

    @property
    def current_ru(self) -> Optional[Any]:
        if self._terminated or self._position >= len(self._ru_order):
            return None
        return self._ru_order[self._position]

    @property
    def allocations(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._allocations]

    @property
    def remaining_cpu(self) -> np.ndarray:
        return self._remaining_cpu.copy()

    @property
    def remaining_bandwidth(self) -> np.ndarray:
        return self._remaining_bandwidth.copy()

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        if gym is not None:
            super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(seed)

        self._ru_order = list(self.catalog.ru_ids)
        should_shuffle = self.shuffle_rus
        if options and "shuffle_rus" in options:
            should_shuffle = bool(options["shuffle_rus"])
        if should_shuffle:
            self._rng.shuffle(self._ru_order)

        self._position = 0
        self._remaining_cpu = self.catalog.node_capacities.copy()
        self._remaining_bandwidth = self.catalog.edge_capacities.copy()
        self._allocations = []
        self._episode_reward = 0.0
        self._terminated = len(self._ru_order) == 0

        return self._observation(), self._info()

    def action_masks(self) -> np.ndarray:
        """Return a boolean mask over the fixed action space."""

        mask = np.zeros(self.action_dim, dtype=np.bool_)
        mask[self.catalog.reject_action] = True
        ru_id = self.current_ru
        if ru_id is None:
            return mask

        for action_id, candidate in self.catalog.candidates_for_ru(ru_id).items():
            if self._has_capacity(candidate):
                mask[action_id] = True
        return mask

    # Alias used by some action-masking integrations.
    action_mask = action_masks

    def step(
        self,
        action: int,
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        if self._terminated:
            raise RuntimeError("step() called after the episode terminated; call reset().")

        action = int(action)
        if action < 0 or action >= self.action_dim:
            raise IndexError(f"Action {action} is outside [0, {self.action_dim}).")

        valid_actions = self.action_masks()
        if not valid_actions[action]:
            pair = self.catalog.pair_for_action(action)
            raise ValueError(
                f"Invalid action {action} ({pair}) for RU {self.current_ru!r}. "
                "Use action_masks() before selecting an action."
            )

        ru_id = self.current_ru
        assert ru_id is not None
        if action == self.catalog.reject_action:
            allocation = {
                "ru": ru_id,
                "admitted": 0,
                "drc": None,
                "path": None,
                "action": action,
            }
            reward = float(self.reward_config.rejection_reward)
        else:
            candidate = self.catalog.candidate(ru_id, action)
            assert candidate is not None  # Guaranteed by the action mask.
            self._consume(candidate)
            latency_penalty = (
                self.reward_config.latency_weight
                * candidate.latency
                / max(self._max_latency, 1e-12)
            )
            reward = float(self.reward_config.admission_reward - latency_penalty)
            allocation = {
                "ru": ru_id,
                "admitted": 1,
                "drc": candidate.drc_id,
                "path": candidate.path_id,
                "action": action,
                "latency": candidate.latency,
            }

        self._allocations.append(allocation)
        self._episode_reward += reward
        self._position += 1
        self._terminated = self._position >= len(self._ru_order)

        info = self._info()
        info["last_allocation"] = dict(allocation)
        if self._terminated:
            info["episode"] = {
                "reward": self._episode_reward,
                "admitted": sum(item["admitted"] for item in self._allocations),
                "total_rus": len(self._allocations),
            }
            info["solution"] = self.allocations

        return self._observation(), reward, self._terminated, False, info

    def render(self) -> None:
        admitted = sum(item["admitted"] for item in self._allocations)
        print(
            f"RU step {self._position}/{len(self._ru_order)} | "
            f"admitted={admitted} | reward={self._episode_reward:.3f}"
        )

    def checkpoint_metadata(self) -> Dict[str, Any]:
        """Describe the fixed dimensions and action ordering used by a model."""

        return {
            "observation_dim": self.observation_dim,
            "action_dim": self.action_dim,
            "ru_ids": [str(value) for value in self.catalog.ru_ids],
            "drc_ids": [str(value) for value in self.catalog.drc_ids],
            "path_ids": [str(value) for value in self.catalog.path_ids],
            "node_ids": [str(value) for value in self.catalog.node_ids],
            "edge_ids": [list(map(str, edge)) for edge in self.catalog.edge_ids],
        }

    def _has_capacity(self, candidate: CandidateAction) -> bool:
        tolerance = self.capacity_tolerance
        for index, amount in candidate.cpu_usage:
            if amount > float(self._remaining_cpu[index]) + tolerance:
                return False
        for index, amount in candidate.bandwidth_usage:
            if amount > float(self._remaining_bandwidth[index]) + tolerance:
                return False
        return True

    def _consume(self, candidate: CandidateAction) -> None:
        for index, amount in candidate.cpu_usage:
            self._remaining_cpu[index] -= amount
        for index, amount in candidate.bandwidth_usage:
            self._remaining_bandwidth[index] -= amount

        # Remove harmless floating-point dust and fail loudly on real violations.
        self._remaining_cpu[np.abs(self._remaining_cpu) < self.capacity_tolerance] = 0.0
        self._remaining_bandwidth[
            np.abs(self._remaining_bandwidth) < self.capacity_tolerance
        ] = 0.0
        if np.any(self._remaining_cpu < -self.capacity_tolerance):
            raise RuntimeError("CPU capacity became negative after a masked action.")
        if np.any(self._remaining_bandwidth < -self.capacity_tolerance):
            raise RuntimeError("Bandwidth capacity became negative after a masked action.")

    def _observation(self) -> np.ndarray:
        node_count = len(self.catalog.node_ids)
        current_location = np.zeros(node_count, dtype=np.float32)
        ru_id = self.current_ru
        if ru_id is not None:
            ru_node = self.problem.ru_location(ru_id)
            current_location[self.catalog.node_index[ru_node]] = 1.0

        total_rus = max(1, len(self._ru_order))
        progress = np.asarray([self._position / total_rus], dtype=np.float32)
        cpu_ratio = np.divide(
            self._remaining_cpu,
            self.catalog.node_capacities,
            out=np.zeros_like(self._remaining_cpu),
            where=self.catalog.node_capacities > 0,
        )
        bandwidth_ratio = np.divide(
            self._remaining_bandwidth,
            self.catalog.edge_capacities,
            out=np.zeros_like(self._remaining_bandwidth),
            where=self.catalog.edge_capacities > 0,
        )
        observation = np.concatenate(
            (progress, current_location, cpu_ratio, bandwidth_ratio)
        ).astype(np.float32, copy=False)
        return np.clip(observation, 0.0, 1.0)

    def _info(self) -> Dict[str, Any]:
        return {
            "current_ru": self.current_ru,
            "step": self._position,
            "admitted": sum(item["admitted"] for item in self._allocations),
            "total_rus": len(self._ru_order),
        }
