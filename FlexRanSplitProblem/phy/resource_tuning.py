"""Deterministic physical-resource tuning for heterogeneous T2 regions.

The topology, RU placement, and link delays are copied verbatim.  Only the
CPU of two RU-bearing CRs and capacities of their incident links are changed:

* profile A is CPU-constrained but bandwidth-rich enough for DRC4/5/10;
* profile B is bandwidth-constrained and admits only DRC8 at its endpoint.

All other physical resources retain the PlaceRAN values.
"""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Tuple


PROFILE_A_CPU = 3.4
PROFILE_A_ACCESS_BW = 15.0
PROFILE_B_CPU = 5.2
PROFILE_B_ACCESS_BW = 10.5


@dataclass(frozen=True)
class TuningSummary:
    network: int
    profile_a_node: int
    profile_b_node: int
    profile_a_hops: int
    profile_b_hops: int
    profile_a_cpu: float = PROFILE_A_CPU
    profile_a_access_bw: float = PROFILE_A_ACCESS_BW
    profile_b_cpu: float = PROFILE_B_CPU
    profile_b_access_bw: float = PROFILE_B_ACCESS_BW

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _adjacency(links: Iterable[Dict[str, Any]]) -> Dict[int, set[int]]:
    adjacency: Dict[int, set[int]] = defaultdict(set)
    for link in links:
        source = int(link["fromNode"])
        target = int(link["toNode"])
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency


def _hop_distances(
    links: Iterable[Dict[str, Any]], core_id: int
) -> Dict[int, int]:
    adjacency = _adjacency(links)
    distances = {core_id: 0}
    queue = deque([core_id])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency[node]:
            if neighbor in distances:
                continue
            distances[neighbor] = distances[node] + 1
            queue.append(neighbor)
    return distances


def choose_heterogeneous_regions(
    nodes: Iterable[Dict[str, Any]],
    links: Iterable[Dict[str, Any]],
    *,
    core_id: int = 0,
) -> Tuple[int, int, Dict[int, int]]:
    """Choose one aggregation RU and one outer-tier RU deterministically."""
    distances = _hop_distances(links, core_id)
    ru_nodes = sorted(
        int(node["nodeNumber"])
        for node in nodes
        if int(node["RU"]) > 0
    )
    missing = [node for node in ru_nodes if node not in distances]
    if missing:
        raise ValueError(f"RU nodes are disconnected from core {core_id}: {missing}")

    aggregation = [node for node in ru_nodes if distances[node] == 2]
    outer = [node for node in ru_nodes if distances[node] > 2]
    if not aggregation or not outer:
        raise ValueError(
            "T2 heterogeneous tuning requires RU-bearing CRs in both "
            "the two-hop aggregation tier and an outer tier"
        )
    return min(aggregation), min(outer), distances


def tune_t2_resources(
    nodes_document: Dict[str, Any],
    links_document: Dict[str, Any],
    *,
    network: int,
    core_id: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any], TuningSummary]:
    """Return HET copies without mutating the PlaceRAN source documents."""
    tuned_nodes = deepcopy(nodes_document)
    tuned_links = deepcopy(links_document)
    nodes = tuned_nodes["nodes"]
    links = tuned_links["links"]

    profile_a, profile_b, distances = choose_heterogeneous_regions(
        nodes, links, core_id=core_id
    )

    found = set()
    for node in nodes:
        node_id = int(node["nodeNumber"])
        if node_id == profile_a:
            node["cpu"] = PROFILE_A_CPU
            found.add(node_id)
        elif node_id == profile_b:
            node["cpu"] = PROFILE_B_CPU
            found.add(node_id)
    if found != {profile_a, profile_b}:
        raise ValueError("Selected profile node is missing from the node document")

    # Profile B takes precedence if the two selected regions share a link.
    for link in links:
        endpoints = {int(link["fromNode"]), int(link["toNode"])}
        if profile_b in endpoints:
            link["capacity"] = PROFILE_B_ACCESS_BW
        elif profile_a in endpoints:
            link["capacity"] = PROFILE_A_ACCESS_BW

    summary = TuningSummary(
        network=network,
        profile_a_node=profile_a,
        profile_b_node=profile_b,
        profile_a_hops=distances[profile_a],
        profile_b_hops=distances[profile_b],
    )
    return tuned_nodes, tuned_links, summary

