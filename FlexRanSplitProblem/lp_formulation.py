"""ILP for flexible RAN-function placement.

The notation follows Section IV of the supplied paper:

* ``pi_tilde[k]``: DRC ``k`` is used by at least one NSC;
* ``pi[s, k]``: NSC ``s`` selects DRC ``k``;
* ``y[s, k, p]``: NSC ``s`` selects physical path ``p`` with DRC ``k``;
* ``x_node[s, k, p, i, v]``: VNF ``v`` is mapped to node ``i``;
* ``x_link[s, k, p, i, j, v, w]``: virtual link ``vw`` uses link ``ij``.

All variables are binary.  Constraint names retain the numbering used in the
paper.  ``C2b`` is an explicit DRC/path consistency constraint: it is required
for a valid model but is missing from the draft between equations (4) and (5).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pulp

from .common import FlexRanSplitProblem
from .helper import edge_bw_cap, node_cpu_cap, path_edges, path_latency, path_nodes


DEFAULT_BETA = 0.5


def _capacity_edge(PHY, u: Any, v: Any) -> Tuple[Any, Any]:
    """Return the physical edge whose capacity is consumed by arc ``u -> v``."""
    if PHY.is_directed():
        if not PHY.has_edge(u, v):
            raise ValueError(f"Path arc {(u, v)} is not present in the physical graph")
        return (u, v)

    if not PHY.has_edge(u, v):
        raise ValueError(f"Path edge {(u, v)} is not present in the physical graph")
    return tuple(sorted((u, v), key=lambda node: (type(node).__name__, repr(node))))


def formulateLp(
    problem: FlexRanSplitProblem,
    beta: float = DEFAULT_BETA,
) -> pulp.LpProblem:
    """Build the paper's binary linear placement model.

    Parameters
    ----------
    problem:
        Physical network, physical paths, NSCs/RUs, DRCs, and resource data.
    beta:
        Weight in equation (14a).  ``beta=1`` minimizes only the number of
        used DRCs; ``beta=0`` minimizes only total normalized path latency.
    """
    if not 0.0 <= beta <= 1.0:
        raise ValueError("beta must be in [0, 1]")

    problem.sanity_check()
    PHY = problem.PHY

    # Paper notation: S (NSCs), K (DRCs), P_s (paths for NSC s), N_s and E_s.
    S = tuple(problem.S)
    K = tuple(problem.K)
    V = tuple(problem.V)
    virtual_links = tuple(problem.virtual_links)
    paths_by_slice = {s: tuple(problem.paths_for_slice(s)) for s in S}
    path_by_key = {
        (s, p.id): p
        for s in S
        for p in paths_by_slice[s]
    }
    nodes_by_path = {
        key: tuple(path_nodes(path))
        for key, path in path_by_key.items()
    }
    arcs_by_path = {
        key: tuple(path_edges(path))
        for key, path in path_by_key.items()
    }

    lp = pulp.LpProblem(
        name=getattr(problem, "name", "Flexible_RAN_Placement"),
        sense=pulp.LpMinimize,
    )

    # ------------------------------------------------------------------
    # Binary variables, equations (3a)-(3c) and the additional pi_tilde.
    # ------------------------------------------------------------------
    # Do not pass tuple(K) directly to LpVariable.dicts(): PuLP interprets a
    # tuple as a declaration of nested index dimensions.  With integer DRC
    # IDs that makes it try to iterate over K[0], raising
    # ``TypeError: 'int' object is not iterable``.
    pi_tilde = {
        k: pulp.LpVariable(f"pi_tilde_{k}", cat=pulp.LpBinary)
        for k in K
    }

    pi_keys = [(s, k) for s in S for k in K]
    pi = pulp.LpVariable.dicts("pi", pi_keys, cat=pulp.LpBinary)

    y_keys = [
        (s, k, p.id)
        for s in S
        for k in K
        for p in paths_by_slice[s]
    ]
    y = pulp.LpVariable.dicts("y", y_keys, cat=pulp.LpBinary)

    x_node_keys = [
        (s, k, p.id, i, v)
        for s in S
        for k in K
        for p in paths_by_slice[s]
        for i in nodes_by_path[(s, p.id)]
        for v in V
    ]
    x_node = pulp.LpVariable.dicts("x_node", x_node_keys, cat=pulp.LpBinary)

    x_link_keys = [
        (s, k, p.id, i, j, v, w)
        for s in S
        for k in K
        for p in paths_by_slice[s]
        for i, j in arcs_by_path[(s, p.id)]
        for v, w, _segment in virtual_links
    ]
    x_link = pulp.LpVariable.dicts("x_link", x_link_keys, cat=pulp.LpBinary)

    # C1 / (4): exactly one DRC for every NSC.
    for s in S:
        lp += (
            pulp.lpSum(pi[(s, k)] for k in K) == 1,
            f"C1_drc_selection_{s}",
        )

    # C2 / (5): exactly one (DRC, physical path) pair for every NSC.
    for s in S:
        lp += (
            pulp.lpSum(
                y[(s, k, p.id)]
                for k in K
                for p in paths_by_slice[s]
            )
            == 1,
            f"C2_path_selection_{s}",
        )

    # C2b: selected path and selected DRC must describe the same configuration.
    # This link is required even though it is omitted from the PDF draft.
    for s in S:
        for k in K:
            lp += (
                pulp.lpSum(y[(s, k, p.id)] for p in paths_by_slice[s])
                == pi[(s, k)],
                f"C2b_drc_path_consistency_{s}_{k}",
            )

    # C3 / (6): the UPF and RU are fixed at the path endpoints.
    for s in S:
        ru_node = problem.ru_location(s)
        for k in K:
            for p in paths_by_slice[s]:
                key = (s, k, p.id)
                lp += (
                    x_node[(s, k, p.id, problem.core, "vupf")] == y[key],
                    f"C3_upf_endpoint_{s}_{k}_{p.id}",
                )
                lp += (
                    x_node[(s, k, p.id, ru_node, "vru")] == y[key],
                    f"C3_ru_endpoint_{s}_{k}_{p.id}",
                )

    # C4 / (7): each VNF is mapped to one node of the selected path.
    for s in S:
        for k in K:
            for p in paths_by_slice[s]:
                selected = y[(s, k, p.id)]
                for v in V:
                    lp += (
                        pulp.lpSum(
                            x_node[(s, k, p.id, i, v)]
                            for i in nodes_by_path[(s, p.id)]
                        )
                        == selected,
                        f"C4_one_node_{s}_{k}_{p.id}_{v}",
                    )

    # C5 / (8): two VNFs of one NSC cannot share a physical node.
    for s in S:
        for k in K:
            for p in paths_by_slice[s]:
                selected = y[(s, k, p.id)]
                for i in nodes_by_path[(s, p.id)]:
                    lp += (
                        pulp.lpSum(
                            x_node[(s, k, p.id, i, v)]
                            for v in V
                        )
                        <= selected,
                        f"C5_one_vnf_{s}_{k}_{p.id}_{i}",
                    )

    # C6a / (9a): physical-node resource capacities.
    for i in problem.N:
        terms = []
        for s in S:
            for k in K:
                for p in paths_by_slice[s]:
                    if i not in nodes_by_path[(s, p.id)]:
                        continue
                    for v in V:
                        requirement = problem.node_req(s, k, v)
                        if requirement:
                            terms.append(
                                requirement * x_node[(s, k, p.id, i, v)]
                            )
        lp += (
            pulp.lpSum(terms) <= node_cpu_cap(PHY, i),
            f"C6a_node_capacity_{i}",
        )

    # Group path arcs by the physical edge whose capacity they consume.
    arcs_using_edge: Dict[Tuple[Any, Any], List[Tuple[Any, int, Any, Any]]] = {}
    for s in S:
        for p in paths_by_slice[s]:
            for i, j in arcs_by_path[(s, p.id)]:
                edge = _capacity_edge(PHY, i, j)
                arcs_using_edge.setdefault(edge, []).append((s, p.id, i, j))

    # C6b / (9b): physical-link bandwidth capacities.
    physical_capacity_edges = (
        [tuple(edge) for edge in PHY.edges]
        if PHY.is_directed()
        else [_capacity_edge(PHY, *edge) for edge in PHY.edges]
    )
    for edge in physical_capacity_edges:
        terms = []
        for s, pid, i, j in arcs_using_edge.get(edge, []):
            for k in K:
                for v, w, segment in virtual_links:
                    requirement = problem.link_req(s, k, segment)
                    if requirement:
                        terms.append(
                            requirement * x_link[(s, k, pid, i, j, v, w)]
                        )
        lp += (
            pulp.lpSum(terms) <= edge_bw_cap(PHY, edge),
            f"C6b_link_capacity_{edge[0]}_{edge[1]}",
        )

    # C7 / (10): flow conservation for every virtual link on its chosen path.
    for s in S:
        for k in K:
            for p in paths_by_slice[s]:
                pid = p.id
                arcs = arcs_by_path[(s, pid)]
                for v, w, _segment in virtual_links:
                    for i in nodes_by_path[(s, pid)]:
                        outgoing = pulp.lpSum(
                            x_link[(s, k, pid, a, b, v, w)]
                            for a, b in arcs
                            if a == i
                        )
                        incoming = pulp.lpSum(
                            x_link[(s, k, pid, a, b, v, w)]
                            for a, b in arcs
                            if b == i
                        )
                        lp += (
                            outgoing - incoming
                            == x_node[(s, k, pid, i, v)]
                            - x_node[(s, k, pid, i, w)],
                            f"C7_flow_{s}_{k}_{pid}_{v}_{w}_{i}",
                        )

    # C8 / (11): suppress link variables belonging to an unselected path.
    for s, k, pid, i, j, v, w in x_link_keys:
        lp += (
            x_link[(s, k, pid, i, j, v, w)] <= y[(s, k, pid)],
            f"C8_remove_redundant_{s}_{k}_{pid}_{i}_{j}_{v}_{w}",
        )

    # C9 / (12)-(13): pi_tilde[k] is the logical OR of pi[s, k].
    # This integer-scaled formulation is equivalent to (13), but stronger and
    # avoids a tiny epsilon that can be swallowed by a solver tolerance.
    for k in K:
        use_count = pulp.lpSum(pi[(s, k)] for s in S)
        lp += (
            use_count <= len(S) * pi_tilde[k],
            f"C9_drc_used_lower_{k}",
        )
        lp += (
            pi_tilde[k] <= use_count,
            f"C9_drc_used_upper_{k}",
        )

    # C10: optional end-to-end latency SLA assigned by the slice profile.
    for s in S:
        latency_limit = problem.max_latency(s)
        if latency_limit is None:
            continue
        lp += (
            pulp.lpSum(
                path_latency(p) * y[(s, k, p.id)]
                for k in K
                for p in paths_by_slice[s]
            )
            <= latency_limit,
            f"C10_slice_latency_{s}",
        )

    # Objective / (14)-(15): used DRC count and normalized total path latency.
    max_path_latency = max(
        path_latency(p)
        for s in S
        for p in paths_by_slice[s]
    )
    latency_normalizer = max_path_latency if max_path_latency > 0.0 else 1.0
    used_drc_count = pulp.lpSum(pi_tilde[k] for k in K)
    normalized_latency = (
        pulp.lpSum(
            y[(s, k, p.id)] * path_latency(p)
            for s in S
            for k in K
            for p in paths_by_slice[s]
        )
        / latency_normalizer
    )
    lp += (
        beta * used_drc_count + (1.0 - beta) * normalized_latency,
        "OBJ_used_drcs_and_latency",
    )

    # Keep semantic handles for solution extraction, diagnostics, and tests.
    lp._vars = {
        "pi_tilde": pi_tilde,
        "pi": pi,
        "y": y,
        "x_node": x_node,
        "x_link": x_link,
    }
    lp._sets = {
        "S": S,
        "K": K,
        "V": V,
        "virtual_links": virtual_links,
        "paths_by_slice": paths_by_slice,
        "path_by_key": path_by_key,
        "nodes_by_path": nodes_by_path,
        "arcs_by_path": arcs_by_path,
    }
    lp._objective_terms = {
        "beta": beta,
        "latency_normalizer": latency_normalizer,
    }
    return lp


def extract_solution(
    problem: FlexRanSplitProblem,
    lp: pulp.LpProblem,
) -> List[Dict[str, Any]]:
    """Return DRC, path, VNF placement, and virtual-link mapping per NSC."""
    variables = getattr(lp, "_vars", None)
    sets = getattr(lp, "_sets", None)
    if variables is None or sets is None:
        raise ValueError("LP has no semantic metadata; build it with formulateLp()")

    y = variables["y"]
    x_node = variables["x_node"]
    x_link = variables["x_link"]
    paths_by_slice = sets["paths_by_slice"]
    nodes_by_path = sets["nodes_by_path"]
    arcs_by_path = sets["arcs_by_path"]

    solution: List[Dict[str, Any]] = []
    for s in sets["S"]:
        chosen = None
        for k in sets["K"]:
            for p in paths_by_slice[s]:
                if (pulp.value(y[(s, k, p.id)]) or 0.0) > 0.5:
                    chosen = (k, p)
                    break
            if chosen is not None:
                break

        if chosen is None:
            solution.append(
                {
                    "slice": s,
                    "ru": s,
                    "service": problem.service_type(s),
                    "deployed": 0,
                    "admitted": 0,
                    "drc": None,
                    "path": None,
                    "path_nodes": [],
                    "latency": None,
                    "vnf_placement": {},
                    "virtual_link_mapping": {},
                }
            )
            continue

        k, p = chosen
        pid = p.id
        placement = {}
        for v in sets["V"]:
            placement[v] = next(
                i
                for i in nodes_by_path[(s, pid)]
                if (pulp.value(x_node[(s, k, pid, i, v)]) or 0.0) > 0.5
            )

        link_mapping = {}
        for v, w, _segment in sets["virtual_links"]:
            link_mapping[f"{v}->{w}"] = [
                [i, j]
                for i, j in arcs_by_path[(s, pid)]
                if (pulp.value(x_link[(s, k, pid, i, j, v, w)]) or 0.0) > 0.5
            ]

        solution.append(
            {
                "slice": s,
                "ru": s,
                "service": problem.service_type(s),
                "deployed": 1,
                "admitted": 1,
                "drc": k,
                "path": pid,
                "path_nodes": list(nodes_by_path[(s, pid)]),
                "latency": path_latency(p),
                "vnf_placement": placement,
                "virtual_link_mapping": link_mapping,
            }
        )

    return solution
