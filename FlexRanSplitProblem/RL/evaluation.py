"""Reusable policy evaluation helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def validate_checkpoint_environment(agent: Any, env: Any) -> None:
    if agent.observation_dim != env.observation_dim:
        raise ValueError(
            f"Observation mismatch: checkpoint={agent.observation_dim}, "
            f"environment={env.observation_dim}."
        )
    if agent.action_dim != env.action_dim:
        raise ValueError(
            f"Action mismatch: checkpoint={agent.action_dim}, "
            f"environment={env.action_dim}."
        )

    expected = agent.checkpoint_metadata.get("environment")
    if expected is not None and expected != env.checkpoint_metadata():
        raise ValueError(
            "The checkpoint action ordering does not match this problem. "
            "Train a checkpoint for this DRC/path catalog."
        )


def evaluate_agent(
    agent: Any,
    env: Any,
    episodes: int = 1,
    deterministic: bool = True,
    seed: int = 0,
) -> List[Dict[str, Any]]:
    if episodes <= 0:
        raise ValueError("episodes must be positive.")
    validate_checkpoint_environment(agent, env)

    results: List[Dict[str, Any]] = []
    for episode in range(episodes):
        observation, _ = env.reset(seed=seed + episode)
        terminated = False
        truncated = False
        total_reward = 0.0
        while not (terminated or truncated):
            action, _, _ = agent.select_action(
                observation,
                env.action_masks(),
                deterministic=deterministic,
            )
            observation, reward, terminated, truncated, _ = env.step(action)
            total_reward += reward

        allocations = env.allocations
        results.append(
            {
                "episode": episode + 1,
                "reward": total_reward,
                "admitted": sum(item["admitted"] for item in allocations),
                "total_rus": len(allocations),
                "allocations": allocations,
            }
        )
    return results
