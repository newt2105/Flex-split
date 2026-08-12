"""Reinforcement-learning tools for the Flexible RAN Split problem."""

from .catalog import ActionCatalog, CandidateAction
from .environment import FlexRanSplitEnv, RewardConfig

__all__ = [
    "ActionCatalog",
    "CandidateAction",
    "FlexRanSplitEnv",
    "RewardConfig",
    "MaskedPPOAgent",
    "PPOConfig",
]


def __getattr__(name: str):
    """Import PyTorch components lazily so the environment works without Torch."""

    if name in {"MaskedPPOAgent", "PPOConfig"}:
        from .ppo_agent import MaskedPPOAgent, PPOConfig

        return {"MaskedPPOAgent": MaskedPPOAgent, "PPOConfig": PPOConfig}[name]
    raise AttributeError(name)
