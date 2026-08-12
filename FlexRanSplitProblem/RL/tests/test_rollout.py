from __future__ import annotations

import unittest

import numpy as np

from RL.rollout import RolloutBuffer


class RolloutTests(unittest.TestCase):
    def test_terminal_return_is_discounted_reward(self):
        buffer = RolloutBuffer(size=2, observation_dim=1, action_dim=1)
        buffer.add(np.array([0.0]), np.array([True]), 0, 0.0, 0.0, 1.0, False)
        buffer.add(np.array([1.0]), np.array([True]), 0, 0.0, 0.0, 1.0, True)
        buffer.compute_returns_and_advantages(last_value=0.0, gamma=1.0, gae_lambda=1.0)
        np.testing.assert_allclose(buffer.returns, [2.0, 1.0])


if __name__ == "__main__":
    unittest.main()
