# ran_model.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Iterable, Literal, Optional
import json
import networkx as nx

Seg = Literal["BH", "MH", "FH"]
VNF = Literal["vupf", "vcu", "vdu", "vru"]


# =========================
# Core data structures
# =========================

@dataclass(frozen=True)
class CR:
    """Compute Resource node (physical compute node)."""
    id: int
    cpu: float
    num_ru: int = 0


@dataclass(frozen=True)
class RU:
    """Radio Unit (a demand endpoint) attached to a CR node."""
    id: int
    cr: int  # CR id where this RU is located


@dataclass(frozen=True)
class FS:
    """Functional Split function block (legacy f0..f8)."""
    id: str
    f_cpu: float
    f_ram: float


@dataclass(frozen=True)
class DRC:
    """
    Deployment / RAN split configuration (legacy DRC).
    Keeps the same fields as the old code for compatibility.
    """
    id: int

    cpu_CU: float
    cpu_DU: float
    cpu_RU: float

    ram_CU: float
    ram_DU: float
    ram_RU: float

    Fs_CU: List[str]
    Fs_DU: List[str]
    Fs_RU: List[str]

    delay_BH: float
    delay_MH: float
    delay_FH: float

    bw_BH: float
    bw_MH: float
    bw_FH: float

    # ---------- Convenience getters for new ILP ----------
    def vnf_cpu(self, v: VNF) -> float:
        if v == "vcu":
            return self.cpu_CU
        if v == "vdu":
            return self.cpu_DU
        if v == "vru":
            return self.cpu_RU
        # vupf not modeled as consuming CR CPU in legacy; return 0 by default
        return 0.0

    def seg_bw(self, seg: Seg) -> float:
        return {"BH": self.bw_BH, "MH": self.bw_MH, "FH": self.bw_FH}[seg]

    def seg_delay(self, seg: Seg) -> float:
        return {"BH": self.delay_BH, "MH": self.delay_MH, "FH": self.delay_FH}[seg]


# =========================
# Builders (DRC sets)
# =========================

def DRC_structure_T1() -> Dict[int, DRC]:
    """
    Same numeric values as legacy DRC_structure_T1().
    """
    DRC1 = DRC(1, 0.49, 2.058, 2.352, 0.01, 0.01, 0.01, ['f8'], ['f7','f6','f5','f4','f3','f2'], ['f1','f0'], 10, 10, 0.25, 3, 5.4, 17.4)
    DRC2 = DRC(2, 0.98, 1.568, 2.352, 0.01, 0.01, 0.01, ['f8','f7'], ['f6','f5','f4','f3','f2'], ['f1','f0'], 10, 10, 0.25, 3, 5.4, 17.4)
    DRC4 = DRC(4, 0.49, 1.225, 3.185, 0.01, 0.01, 0.01, ['f8'], ['f7','f6','f5','f4','f3'], ['f2','f1','f0'], 10, 10, 0.25, 3, 5.4, 5.6)
    DRC5 = DRC(5, 0.98, 0.735, 3.185, 0.01, 0.01, 0.01, ['f8','f7'], ['f6','f5','f4','f3'], ['f2','f1','f0'], 10, 10, 0.25, 3, 5.4, 5.6)
    DRC6 = DRC(6, 0, 0.49, 4.41, 0, 0.01, 0.01, [0], ['f8'], ['f7','f6','f5','f4','f3','f2','f1','f0'], 0, 10, 10, 0, 3, 5.4)
    DRC7 = DRC(7, 0, 3, 3.92, 0, 0.01, 0.01, [0], ['f8','f7'], ['f6','f5','f4','f3','f2','f1','f0'], 0, 10, 10, 0, 3, 5.4)
    DRC8 = DRC(8, 0, 0, 4.9, 0, 0, 0.01, [0], [0], ['f8','f7','f6','f5','f4','f3','f2','f1','f0'], 0, 0, 10, 0, 0, 3)
    DRC9 = DRC(9, 0, 2.54, 2.354, 0, 0.01, 0.01, [0], ['f8','f7','f6','f5','f4','f3','f2'], ['f1','f0'], 0, 10, 0.25, 0, 3, 17.4)
    DRC10 = DRC(10, 0, 1.71, 3.185, 0, 0.01, 0.01, [0], ['f8','f7','f6','f5','f4','f3'], ['f2','f1','f0'], 0, 10, 0.25, 0, 3, 5.6)

    return {1: DRC1, 2: DRC2, 4: DRC4, 5: DRC5, 6: DRC6, 7: DRC7, 8: DRC8, 9: DRC9, 10: DRC10}


def DRC_structure_T2() -> Dict[int, DRC]:
    """
    Same numeric values as legacy DRC_structure_T2().
    """
    DRC1 = DRC(1, 0.49, 2.058, 2.352, 0.01, 0.01, 0.01, ['f8'], ['f7','f6','f5','f4','f3','f2'], ['f1','f0'], 10, 10, 0.25, 9.9, 13.2, 42.6)
    DRC2 = DRC(2, 0.98, 1.568, 2.352, 0.01, 0.01, 0.01, ['f8','f7'], ['f6','f5','f4','f3','f2'], ['f1','f0'], 10, 10, 0.25, 9.9, 13.2, 42.6)
    DRC4 = DRC(4, 0.49, 1.225, 3.185, 0.01, 0.01, 0.01, ['f8'], ['f7','f6','f5','f4','f3'], ['f2','f1','f0'], 10, 10, 0.25, 9.9, 13.2, 13.6)
    DRC5 = DRC(5, 0.98, 0.735, 3.185, 0.01, 0.01, 0.01, ['f8','f7'], ['f6','f5','f4','f3'], ['f2','f1','f0'], 10, 10, 0.25, 9.9, 13.2, 13.6)
    DRC6 = DRC(6, 0, 0.49, 4.41, 0, 0.01, 0.01, [0], ['f8'], ['f7','f6','f5','f4','f3','f2','f1','f0'], 0, 10, 10, 0, 9.9, 13.2)
    DRC7 = DRC(7, 0, 3, 3.92, 0, 0.01, 0.01, [0], ['f8','f7'], ['f6','f5','f4','f3','f2','f1','f0'], 0, 10, 10, 0, 9.9, 13.2)
    DRC8 = DRC(8, 0, 0, 4.9, 0, 0, 0.01, [0], [0], ['f8','f7','f6','f5','f4','f3','f2','f1','f0'], 0, 0, 10, 0, 0, 9.9)
    DRC9 = DRC(9, 0, 2.54, 2.354, 0, 0.01, 0.01, [0], ['f8','f7','f6','f5','f4','f3','f2'], ['f1','f0'], 0, 10, 0.25, 0, 9.9, 42.6)
    DRC10 = DRC(10, 0, 1.71, 3.185, 0, 0.01, 0.01, [0], ['f8','f7','f6','f5','f4','f3'], ['f2','f1','f0'], 0, 10, 0.25, 0, 3, 13.6)

    return {1: DRC1, 2: DRC2, 4: DRC4, 5: DRC5, 6: DRC6, 7: DRC7, 8: DRC8, 9: DRC9, 10: DRC10}


# =========================
# RU placement (from JSON)
# =========================

def build_rus_from_nodes_json_T2(nodes_json_path: str) -> Dict[int, RU]:
    """
    Same idea as RU_location_T2(): read RU counts and attach each RU to a CR.
    Expected format: model_files/T2_files/F1_8_CRs_nodes_LC.json
    where data["nodes"] is a list and each item has "nodeNumber" and "RU".
    """
    rus: Dict[int, RU] = {}
    count = 1
    with open(nodes_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for node in data["nodes"]:
        cr_id = int(node["nodeNumber"])
        num_rus = int(node["RU"])
        for _ in range(num_rus):
            rus[count] = RU(count, cr_id)
            count += 1
    return rus


def build_rus_from_nodes_json_T1(nodes_json_path: str) -> Dict[int, RU]:
    """
    Same idea as RU_location_T1(): read RU counts and attach each RU to a CR.
    Expected format: model_files/T1_files/R1_51_CRs_nodes_LC.json
    where data["nodes"] is a dict and each entry has "RU".
    """
    rus: Dict[int, RU] = {}
    count = 1
    with open(nodes_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for key, node in data["nodes"].items():
        # key looks like "...-<CR_id>"
        cr_id = int(str(key).split("-", 1)[1])
        num_rus = int(node["RU"])
        for _ in range(num_rus):
            rus[count] = RU(count, cr_id)
            count += 1
    return rus


# =========================
# CR extraction from PHY (networkx)
# =========================

def build_crs_from_phy(PHY: nx.DiGraph, ru_count_by_cr: Optional[Dict[int, int]] = None) -> Dict[int, CR]:
    """
    Build CR dict from a networkx physical graph.
    Convention: PHY.nodes[i]["cpu"] exists.
    If your PHY uses other attribute names, adjust here only.
    """
    crs: Dict[int, CR] = {}
    for i in PHY.nodes:
        cpu = float(PHY.nodes[i].get("cpu", 0.0))
        num_ru = int(ru_count_by_cr.get(i, 0)) if ru_count_by_cr else 0
        crs[int(i)] = CR(int(i), cpu, num_ru)
    # ensure core exists
    if 0 not in crs:
        crs[0] = CR(0, 0.0, 0)
    return crs


# =========================
# Minimal “virtual RAN” helper API for ILP
# =========================

VNFS: Tuple[VNF, ...] = ("vupf", "vcu", "vdu", "vru")
VLINKS: Tuple[Tuple[VNF, VNF, Seg], ...] = (
    ("vupf", "vcu", "BH"),
    ("vcu", "vdu", "MH"),
    ("vdu", "vru", "FH"),
)

def node_req(drc: DRC, v: VNF) -> float:
    """CPU requirement of VNF v under DRC (for ILP)."""
    return drc.vnf_cpu(v)

def link_req(drc: DRC, seg: Seg) -> float:
    """Bandwidth requirement for BH/MH/FH under DRC (for ILP)."""
    return drc.seg_bw(seg)

def delay_req(drc: DRC, seg: Seg) -> float:
    """Delay constraint for BH/MH/FH under DRC (for ILP)."""
    return drc.seg_delay(seg)
