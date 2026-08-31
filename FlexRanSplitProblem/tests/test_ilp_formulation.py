from __future__ import annotations

from pathlib import Path

import networkx as nx
import pulp

from FlexRanSplitProblem.common import FlexRanSplitProblem, SliceProfile
from FlexRanSplitProblem.lp_formulation import extract_solution, formulateLp
from FlexRanSplitProblem.phy.path_model import Path
from FlexRanSplitProblem.phy.ran_model import DRC, RU
from FlexRanSplitProblem.run_ilp import load_slice_profiles


def make_drc(drc_id: int) -> DRC:
    return DRC(
        id=drc_id,
        cpu_CU=1.0,
        cpu_DU=1.0,
        cpu_RU=1.0,
        ram_CU=0.0,
        ram_DU=0.0,
        ram_RU=0.0,
        Fs_CU=["f8"],
        Fs_DU=["f7"],
        Fs_RU=["f6"],
        delay_BH=10.0,
        delay_MH=10.0,
        delay_FH=10.0,
        bw_BH=1.0,
        bw_MH=1.0,
        bw_FH=1.0,
    )


def add_bidirectional_edge(graph: nx.DiGraph, u: int, v: int, delay: float) -> None:
    graph.add_edge(u, v, capacity=10.0, delay=delay)
    graph.add_edge(v, u, capacity=10.0, delay=delay)


def build_single_slice_problem(
    slice_profile: SliceProfile | None = None,
) -> FlexRanSplitProblem:
    graph = nx.DiGraph()
    for node in range(8):
        graph.add_node(node, cpu=0.0 if node == 0 else 10.0)

    # Short path: 0-1-2-4 (latency 3). Long path: 0-5-6-4 (latency 6).
    add_bidirectional_edge(graph, 0, 1, 1.0)
    add_bidirectional_edge(graph, 1, 2, 1.0)
    add_bidirectional_edge(graph, 2, 4, 1.0)
    add_bidirectional_edge(graph, 0, 5, 2.0)
    add_bidirectional_edge(graph, 5, 6, 2.0)
    add_bidirectional_edge(graph, 6, 4, 2.0)

    return FlexRanSplitProblem(
        physical_network=graph,
        paths=[
            Path(id=1, nodes=[0, 1, 2, 4], latency=3.0),
            Path(id=2, nodes=[0, 5, 6, 4], latency=6.0),
        ],
        rus={1: RU(id=1, cr=4)},
        drcs={1: make_drc(1), 2: make_drc(2)},
        core_id=0,
        name="unit_test_model",
        slice_profiles={1: slice_profile} if slice_profile else None,
    )


def solve(model: pulp.LpProblem) -> None:
    status = model.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[status] == "Optimal"


def test_shortest_path_and_ordered_vnf_mapping() -> None:
    problem = build_single_slice_problem()
    model = formulateLp(problem, beta=0.0)
    solve(model)

    item = extract_solution(problem, model)[0]
    assert item["path"] == 1
    assert item["path_nodes"] == [0, 1, 2, 4]
    assert item["vnf_placement"] == {
        "vupf": 0,
        "vcu": 1,
        "vdu": 2,
        "vru": 4,
    }
    assert item["virtual_link_mapping"] == {
        "vupf->vcu": [[0, 1]],
        "vcu->vdu": [[1, 2]],
        "vdu->vru": [[2, 4]],
    }


def test_drc_path_consistency_and_used_drc_indicator() -> None:
    problem = build_single_slice_problem()
    model = formulateLp(problem, beta=1.0)
    solve(model)

    variables = model._vars
    selected_drcs = [
        k for k in problem.K if (pulp.value(variables["pi"][(1, k)]) or 0) > 0.5
    ]
    selected_pairs = [
        (k, path.id)
        for k in problem.K
        for path in problem.paths_for_slice(1)
        if (pulp.value(variables["y"][(1, k, path.id)]) or 0) > 0.5
    ]
    used_drcs = [
        k for k in problem.K if (pulp.value(variables["pi_tilde"][k]) or 0) > 0.5
    ]

    assert len(selected_drcs) == 1
    assert len(selected_pairs) == 1
    assert selected_pairs[0][0] == selected_drcs[0]
    assert used_drcs == selected_drcs
    assert any(name.startswith("C2b_drc_path_consistency") for name in model.constraints)


def test_legacy_placement_paths_are_deduplicated_by_node_sequence() -> None:
    problem = build_single_slice_problem()
    duplicate = Path(
        id=3,
        nodes=[0, 1, 2, 4],
        edges_BH=[(0, 1)],
        edges_MH=[(1, 2)],
        edges_FH=[(2, 4)],
        delay_BH=1.0,
        delay_MH=1.0,
        delay_FH=1.0,
    )
    problem.paths.append(duplicate)

    assert [path.id for path in problem.paths_for_slice(1)] == [1, 2]
    model = formulateLp(problem)
    assert all(key[2] != 3 for key in model._vars["y"])


def test_slice_profile_scales_resources_and_is_extracted() -> None:
    profile = SliceProfile(
        service="eMBB",
        cpu_scale=2.0,
        bw_scale=3.0,
        max_latency=3.0,
    )
    problem = build_single_slice_problem(profile)

    assert problem.node_req(1, 1, "vcu") == 2.0
    assert problem.link_req(1, 1, "FH") == 3.0

    model = formulateLp(problem, beta=1.0)
    solve(model)
    item = extract_solution(problem, model)[0]

    assert item["service"] == "eMBB"
    assert item["path"] == 1
    assert "C10_slice_latency_1" in model.constraints


def test_missing_slice_profile_preserves_original_resource_values() -> None:
    problem = build_single_slice_problem()

    assert problem.service_type(1) == "default"
    assert problem.node_req(1, 1, "vdu") == 1.0
    assert problem.link_req(1, 1, "MH") == 1.0
    assert problem.max_latency(1) is None


def test_network_16_slice_profile_file_is_complete() -> None:
    profile_path = (
        Path(__file__).resolve().parents[1]
        / "model_files"
        / "slice_profiles"
        / "network_16.json"
    )
    profiles = load_slice_profiles(profile_path)

    assert set(profiles) == set(range(1, 15))
    assert profiles[1].service == "eMBB"
    assert profiles[6].service == "URLLC"
    assert profiles[7].service == "mMTC"
