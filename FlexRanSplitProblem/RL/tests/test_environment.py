from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from RL.environment import FlexRanSplitEnv


class _AttributeView:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)

    def __getitem__(self, key):
        return self.values[key]


class _Graph:
    def __init__(self, ru_cpu=5.0, bandwidth=10.0):
        self.nodes = _AttributeView({0: {"cpu": 0.0}, 1: {"cpu": ru_cpu}})
        self.edges = _AttributeView({(0, 1): {"capacity": bandwidth}})


class _Problem:
    def __init__(
        self,
        ru_cpu=5.0,
        bandwidth=10.0,
        destination=1,
        delay=0.1,
        num_rus=1,
    ):
        self.PHY = _Graph(ru_cpu=ru_cpu, bandwidth=bandwidth)
        self.core = 0
        self.flow_set = list(range(1, num_rus + 1))
        self.Ks = [7]
        self.paths = [
            SimpleNamespace(
                id=11,
                nodes=[0, destination],
                edges_BH=[],
                edges_MH=[],
                edges_FH=[(0, 1)],
                delay_BH=0.0,
                delay_MH=0.0,
                delay_FH=delay,
            )
        ]

    def ru_location(self, ru_id):
        return 1

    def node_req(self, ru_id, drc_id, vnf):
        return {"vcu": 0.0, "vdu": 0.0, "vru": 2.0}[vnf]

    def link_req(self, ru_id, drc_id, segment):
        return {"BH": 0.0, "MH": 0.0, "FH": 3.0}[segment]

    def delay_req(self, ru_id, drc_id, segment):
        return {"BH": 0.0, "MH": 0.0, "FH": 1.0}[segment]


class EnvironmentTests(unittest.TestCase):
    def test_accept_consumes_resources_and_terminates(self):
        env = FlexRanSplitEnv(_Problem())
        observation, info = env.reset(seed=3)

        self.assertEqual(observation.shape, (6,))
        self.assertEqual(info["current_ru"], 1)
        np.testing.assert_array_equal(env.action_masks(), [True, True])

        _, reward, terminated, truncated, info = env.step(1)
        self.assertEqual(reward, 1.0)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["episode"]["admitted"], 1)
        np.testing.assert_allclose(env.remaining_cpu, [0.0, 3.0])
        np.testing.assert_allclose(env.remaining_bandwidth, [7.0])

    def test_capacity_mask_leaves_only_reject(self):
        env = FlexRanSplitEnv(_Problem(ru_cpu=1.0))
        env.reset()
        np.testing.assert_array_equal(env.action_masks(), [True, False])
        with self.assertRaises(ValueError):
            env.step(1)

    def test_wrong_destination_is_masked(self):
        env = FlexRanSplitEnv(_Problem(destination=2))
        env.reset()
        np.testing.assert_array_equal(env.action_masks(), [True, False])

    def test_delay_violation_is_masked(self):
        env = FlexRanSplitEnv(_Problem(delay=2.0))
        env.reset()
        np.testing.assert_array_equal(env.action_masks(), [True, False])

    def test_reject_does_not_consume_resources(self):
        env = FlexRanSplitEnv(_Problem())
        env.reset()
        before_cpu = env.remaining_cpu
        before_bandwidth = env.remaining_bandwidth
        _, reward, terminated, _, _ = env.step(0)
        self.assertEqual(reward, 0.0)
        self.assertTrue(terminated)
        np.testing.assert_array_equal(env.remaining_cpu, before_cpu)
        np.testing.assert_array_equal(env.remaining_bandwidth, before_bandwidth)

    def test_next_ru_observes_resources_left_by_previous_ru(self):
        env = FlexRanSplitEnv(_Problem(ru_cpu=3.0, num_rus=2))
        env.reset()
        _, _, terminated, _, info = env.step(1)
        self.assertFalse(terminated)
        self.assertEqual(info["current_ru"], 2)
        np.testing.assert_array_equal(env.action_masks(), [True, False])


if __name__ == "__main__":
    unittest.main()
