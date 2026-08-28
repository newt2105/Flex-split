from __future__ import annotations

import json
from pathlib import Path

import pytest

from FlexRanSplitProblem.phy.ran_model import DRC_structure_T2
from FlexRanSplitProblem.phy.resource_tuning import (
    PROFILE_A_ACCESS_BW,
    PROFILE_A_CPU,
    PROFILE_B_ACCESS_BW,
    PROFILE_B_CPU,
    tune_t2_resources,
)


PACKAGE_DIR = Path(__file__).resolve().parents[1]
T2_DIR = PACKAGE_DIR / "model_files" / "T2_files"


def load_documents(network: int) -> tuple[dict, dict]:
    nodes = json.loads(
        (T2_DIR / f"F1_{network}_CRs_nodes_LC.json").read_text(encoding="utf-8")
    )
    links = json.loads(
        (T2_DIR / f"{network}_CRs_links_LC.json").read_text(encoding="utf-8")
    )
    return nodes, links


def endpoint_feasible_drcs(cpu: float, bandwidth: float) -> set[int]:
    return {
        drc_id
        for drc_id, drc in DRC_structure_T2().items()
        if drc.cpu_RU <= cpu and drc.bw_FH <= bandwidth
    }


def test_profiles_separate_all_drcs_using_implementation_values() -> None:
    assert endpoint_feasible_drcs(PROFILE_A_CPU, PROFILE_A_ACCESS_BW) == {
        4,
        5,
        10,
    }
    assert endpoint_feasible_drcs(PROFILE_B_CPU, PROFILE_B_ACCESS_BW) == {8}
    assert not (
        endpoint_feasible_drcs(PROFILE_A_CPU, PROFILE_A_ACCESS_BW)
        & endpoint_feasible_drcs(PROFILE_B_CPU, PROFILE_B_ACCESS_BW)
    )


@pytest.mark.parametrize(
    ("network", "expected_a", "expected_b"),
    ((8, 3, 6), (16, 3, 8), (32, 3, 9), (64, 3, 11), (128, 3, 23), (256, 3, 23)),
)
def test_tuning_preserves_topology_delays_and_unselected_cpus(
    network: int, expected_a: int, expected_b: int
) -> None:
    original_nodes, original_links = load_documents(network)
    tuned_nodes, tuned_links, summary = tune_t2_resources(
        original_nodes, original_links, network=network
    )

    assert summary.profile_a_node == expected_a
    assert summary.profile_b_node == expected_b
    assert [
        (link["fromNode"], link["toNode"], link["delay"])
        for link in tuned_links["links"]
    ] == [
        (link["fromNode"], link["toNode"], link["delay"])
        for link in original_links["links"]
    ]

    original_cpu = {
        int(node["nodeNumber"]): float(node["cpu"])
        for node in original_nodes["nodes"]
    }
    tuned_cpu = {
        int(node["nodeNumber"]): float(node["cpu"])
        for node in tuned_nodes["nodes"]
    }
    assert tuned_cpu[expected_a] == PROFILE_A_CPU
    assert tuned_cpu[expected_b] == PROFILE_B_CPU
    assert {
        node: cpu
        for node, cpu in tuned_cpu.items()
        if node not in {expected_a, expected_b}
    } == {
        node: cpu
        for node, cpu in original_cpu.items()
        if node not in {expected_a, expected_b}
    }

    for link in tuned_links["links"]:
        endpoints = {int(link["fromNode"]), int(link["toNode"])}
        if expected_b in endpoints:
            assert float(link["capacity"]) == PROFILE_B_ACCESS_BW
        elif expected_a in endpoints:
            assert float(link["capacity"]) == PROFILE_A_ACCESS_BW

