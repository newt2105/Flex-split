from __future__ import annotations

import networkx as nx
import pulp

from FlexRanSplitProblem.common import FlexRanSplitProblem
from FlexRanSplitProblem.lp_formulation import extract_solution, formulateLp
from FlexRanSplitProblem.phy.path_model import Path
from FlexRanSplitProblem.phy.ran_model import DRC, RU, DRC_structure_T1


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


def make_reduced_drc(
    drc_id: int,
    *,
    cpu_cu: float,
    cpu_du: float,
) -> DRC:
    return DRC(
        id=drc_id,
        cpu_CU=cpu_cu,
        cpu_DU=cpu_du,
        cpu_RU=1.0,
        ram_CU=0.0,
        ram_DU=0.0,
        ram_RU=0.0,
        Fs_CU=[] if cpu_cu == 0 else ["f8"],
        Fs_DU=[] if cpu_du == 0 else ["f7"],
        Fs_RU=["f6"],
        delay_BH=0.0 if cpu_cu == 0 else 10.0,
        delay_MH=0.0 if cpu_du == 0 else 10.0,
        delay_FH=10.0,
        bw_BH=0.0 if cpu_cu == 0 else 1.0,
        bw_MH=0.0 if cpu_du == 0 else 1.0,
        bw_FH=1.0,
    )


def add_bidirectional_edge(graph: nx.DiGraph, u: int, v: int, delay: float) -> None:
    graph.add_edge(u, v, capacity=10.0, delay=delay)
    graph.add_edge(v, u, capacity=10.0, delay=delay)


def build_single_slice_problem() -> FlexRanSplitProblem:
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


def test_zero_cpu_cu_is_not_mapped_and_three_node_path_is_feasible() -> None:
    graph = nx.DiGraph()
    for node in (0, 1, 4):
        graph.add_node(node, cpu=0.0 if node == 0 else 10.0)
    add_bidirectional_edge(graph, 0, 1, 1.0)
    add_bidirectional_edge(graph, 1, 4, 1.0)

    problem = FlexRanSplitProblem(
        physical_network=graph,
        paths=[Path(id=1, nodes=[0, 1, 4], latency=2.0)],
        rus={1: RU(id=1, cr=4)},
        drcs={6: make_reduced_drc(6, cpu_cu=0.0, cpu_du=1.0)},
        core_id=0,
        name="three_node_reduced_chain",
    )
    model = formulateLp(problem)
    solve(model)

    assert not any(key[-1] == "vcu" for key in model._vars["x_node"])
    item = extract_solution(problem, model)[0]
    assert item["vnf_placement"] == {"vupf": 0, "vdu": 1, "vru": 4}
    assert item["virtual_link_mapping"] == {
        "vupf->vdu": [[0, 1]],
        "vdu->vru": [[1, 4]],
    }


def test_real_drcs_produce_the_expected_active_chains() -> None:
    problem = build_single_slice_problem()
    problem.drcs = DRC_structure_T1()

    assert problem.active_vnfs(1) == ("vupf", "vcu", "vdu", "vru")
    assert problem.active_vnfs(6) == ("vupf", "vdu", "vru")
    assert problem.active_virtual_links(6) == (
        ("vupf", "vdu", "MH"),
        ("vdu", "vru", "FH"),
    )
    assert problem.active_vnfs(8) == ("vupf", "vru")
    assert problem.active_virtual_links(8) == (("vupf", "vru", "FH"),)


def test_zero_cpu_cu_and_du_are_not_mapped_on_two_node_path() -> None:
    graph = nx.DiGraph()
    graph.add_node(0, cpu=0.0)
    graph.add_node(4, cpu=10.0)
    add_bidirectional_edge(graph, 0, 4, 1.0)

    problem = FlexRanSplitProblem(
        physical_network=graph,
        paths=[Path(id=1, nodes=[0, 4], latency=1.0)],
        rus={1: RU(id=1, cr=4)},
        drcs={8: make_reduced_drc(8, cpu_cu=0.0, cpu_du=0.0)},
        core_id=0,
        name="two_node_ru_only_chain",
    )
    model = formulateLp(problem)
    solve(model)

    assert not any(
        key[-1] in {"vcu", "vdu"}
        for key in model._vars["x_node"]
    )
    item = extract_solution(problem, model)[0]
    assert item["vnf_placement"] == {"vupf": 0, "vru": 4}
    assert item["virtual_link_mapping"] == {"vupf->vru": [[0, 4]]}
