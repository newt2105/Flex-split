# ilp_helpers.py
from __future__ import annotations
from typing import Iterable, Tuple
import networkx as nx


# =====================================================
# PHY helpers
# =====================================================

def node_cpu_cap(PHY: nx.DiGraph, i: int) -> float:
    """
    CPU capacity của node i.
    """
    return float(PHY.nodes[i]["cpu"])


def edge_bw_cap(PHY: nx.DiGraph, e: Tuple[int, int]) -> float:
    """
    Bandwidth capacity của edge e.
    """
    return float(PHY.edges[e]["capacity"])


# =====================================================
# Path helpers (BH / MH / FH)
# =====================================================

def seg_edges(p, seg: str) -> Iterable[Tuple[int, int]]:
    """
    Trả về danh sách edges của segment.
    """
    if seg == "BH":
        return p.edges_BH
    if seg == "MH":
        return p.edges_MH
    if seg == "FH":
        return p.edges_FH
    raise ValueError(f"Unknown segment {seg}")


def seg_delay(p, seg: str) -> float:
    """
    Delay của segment.
    """
    if seg == "BH":
        return float(p.delay_BH)
    if seg == "MH":
        return float(p.delay_MH)
    if seg == "FH":
        return float(p.delay_FH)
    raise ValueError(f"Unknown segment {seg}")


def path_latency(p) -> float:
    """
    Tổng delay của path.
    """
    return p.delay_BH + p.delay_MH + p.delay_FH


# =====================================================
# Placement helpers (CU / DU / RU)
# =====================================================

def end_node_of_seg(
    p,
    seg: str,
    core_id: int,
    ru_node: int,
) -> int:
    """
    Suy ra node vật lý đặt VNF.
    """
    if seg == "BH":
        return core_id if len(p.edges_BH) == 0 else int(p.edges_BH[-1][1])

    if seg == "MH":
        if len(p.edges_MH) == 0:
            return end_node_of_seg(p, "BH", core_id, ru_node)
        return int(p.edges_MH[-1][1])

    if seg == "FH":
        return int(ru_node)

    raise ValueError(f"Unknown segment {seg}")
