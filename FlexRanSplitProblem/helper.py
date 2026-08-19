"""Small adapters between the mathematical notation and repository objects."""

from __future__ import annotations

from typing import Any, Iterable, List, Tuple

import networkx as nx


def node_cpu_cap(PHY: nx.Graph, i: Any) -> float:
    """Available resource :math:`A_i` of physical node ``i``."""
    attributes = PHY.nodes[i]
    for key in ("cpu", "cap", "capacity"):
        if key in attributes:
            return float(attributes[key])
    raise KeyError(f"Physical node {i} has no resource capacity")


def edge_bw_cap(PHY: nx.Graph, e: Tuple[Any, Any]) -> float:
    """Available bandwidth :math:`A_ij` of physical link ``e``."""
    attributes = PHY.edges[e]
    for key in ("capacity", "cap", "bandwidth"):
        if key in attributes:
            return float(attributes[key])
    raise KeyError(f"Physical link {e} has no bandwidth capacity")


def path_nodes(path) -> List[Any]:
    """Ordered physical-node set :math:`N_p` of a path."""
    nodes = list(getattr(path, "nodes", ()))
    if len(nodes) < 2:
        raise ValueError(f"Path {getattr(path, 'id', '?')} has no valid node sequence")
    return nodes


def path_edges(path) -> List[Tuple[Any, Any]]:
    """Directed path arcs in core-to-RU order."""
    nodes = path_nodes(path)
    return list(zip(nodes, nodes[1:]))


def path_latency(path) -> float:
    """Total path latency :math:`L_p`."""
    total_latency = getattr(path, "total_latency", None)
    if total_latency is not None:
        return float(total_latency)

    latency = getattr(path, "latency", None)
    if latency is not None:
        return float(latency)

    return float(
        getattr(path, "delay_BH", 0.0)
        + getattr(path, "delay_MH", 0.0)
        + getattr(path, "delay_FH", 0.0)
    )


# ----------------------------------------------------------------------
# Legacy segmented-path helpers retained for the RL catalog and old data.
# ----------------------------------------------------------------------
def seg_edges(path, segment: str) -> Iterable[Tuple[Any, Any]]:
    if segment == "BH":
        return path.edges_BH
    if segment == "MH":
        return path.edges_MH
    if segment == "FH":
        return path.edges_FH
    raise ValueError(f"Unknown segment {segment}")


def seg_delay(path, segment: str) -> float:
    if segment == "BH":
        return float(path.delay_BH)
    if segment == "MH":
        return float(path.delay_MH)
    if segment == "FH":
        return float(path.delay_FH)
    raise ValueError(f"Unknown segment {segment}")


def end_node_of_seg(path, segment: str, core_id: int, ru_node: int) -> int:
    if segment == "BH":
        return core_id if not path.edges_BH else int(path.edges_BH[-1][1])
    if segment == "MH":
        if not path.edges_MH:
            return end_node_of_seg(path, "BH", core_id, ru_node)
        return int(path.edges_MH[-1][1])
    if segment == "FH":
        return int(ru_node)
    raise ValueError(f"Unknown segment {segment}")
