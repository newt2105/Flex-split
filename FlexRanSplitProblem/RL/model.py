"""Masked actor-critic neural network used by PPO."""

from __future__ import annotations

from typing import Sequence, Tuple

try:
    import torch
    from torch import nn
    from torch.distributions import Categorical
except ImportError as exc:  # pragma: no cover - clear message for end users.
    raise ImportError(
        "PyTorch is required for the PPO agent. Install RL/requirements.txt."
    ) from exc


def _mlp(input_dim: int, hidden_sizes: Sequence[int]) -> Tuple[nn.Sequential, int]:
    layers = []
    previous = input_dim
    for hidden in hidden_sizes:
        layers.extend((nn.Linear(previous, int(hidden)), nn.Tanh()))
        previous = int(hidden)
    return nn.Sequential(*layers), previous


class MaskedActorCritic(nn.Module):
    """Shared MLP encoder with categorical actor and scalar critic heads."""

    def __init__(
        self,
        observation_dim: int,
        action_dim: int,
        hidden_sizes: Sequence[int] = (128, 128),
    ) -> None:
        super().__init__()
        self.observation_dim = int(observation_dim)
        self.action_dim = int(action_dim)
        self.hidden_sizes = tuple(int(size) for size in hidden_sizes)

        self.encoder, encoded_dim = _mlp(self.observation_dim, self.hidden_sizes)
        self.policy_head = nn.Linear(encoded_dim, self.action_dim)
        self.value_head = nn.Linear(encoded_dim, 1)
        self._initialize()

    def forward(self, observations: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        encoded = self.encoder(observations)
        return self.policy_head(encoded), self.value_head(encoded).squeeze(-1)

    def distribution_and_value(
        self,
        observations: torch.Tensor,
        action_masks: torch.Tensor,
    ) -> Tuple[Categorical, torch.Tensor]:
        logits, values = self(observations)
        masks = action_masks.to(dtype=torch.bool)
        if masks.shape != logits.shape:
            raise ValueError(
                f"Action mask shape {tuple(masks.shape)} does not match logits "
                f"shape {tuple(logits.shape)}."
            )
        if not torch.all(torch.any(masks, dim=-1)):
            raise ValueError("Every state must have at least one valid action.")

        masked_logits = logits.masked_fill(~masks, torch.finfo(logits.dtype).min)
        return Categorical(logits=masked_logits), values

    def _initialize(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.orthogonal_(module.weight, gain=2**0.5)
                nn.init.zeros_(module.bias)
        nn.init.orthogonal_(self.policy_head.weight, gain=0.01)
        nn.init.orthogonal_(self.value_head.weight, gain=1.0)
