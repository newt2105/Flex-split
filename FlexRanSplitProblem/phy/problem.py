# problem.py
from __future__ import annotations
from typing import Dict, List, Tuple

import networkx as nx

from ran_model import (
    RU,
    DRC,
    VNFS,
    VLINKS,
    node_req as _node_req,
    link_req as _link_req,
    delay_req as _delay_req,
)

# -----------------------------
# FlexRanSplitProblem
# -----------------------------
class FlexRanSplitProblem:
    """
    Wrapper trung tâm cho bài toán Flexible RAN Split.

    ILP chỉ được phép nhìn thấy class này,
    KHÔNG import trực tiếp genphy / paths_gen / ran_model.
    """

    def __init__(
        self,
        PHY: nx.DiGraph,
        paths: List,
        rus: Dict[int, RU],
        drcs: Dict[int, DRC],
        core_id: int = 0,
    ) -> None:
        # -------- physical layer --------
        self.PHY: nx.DiGraph = PHY
        self.core: int = core_id

        # -------- paths --------
        # mỗi path p phải có:
        #   p.id
        #   p.nodes
        #   p.edges
        #   p.delay_BH, p.delay_MH, p.delay_FH
        #   p.edges_BH, p.edges_MH, p.edges_FH
        self.paths = paths

        # -------- RAN model --------
        self.rus: Dict[int, RU] = rus
        self.drcs: Dict[int, DRC] = drcs

        # -------- static sets for ILP --------
        self.flow_set = list(rus.keys())        # sb
        self.Ks = list(drcs.keys())              # DRC ids
        self.vnfs = VNFS                         # ("vupf","vcu","vdu","vru")
        self.vlinks = VLINKS                     # (vupf,vcu,BH), ...

    # ======================================================
    # API CHO ILP
    # ======================================================

    # ---------- Node (CPU) requirement ----------
    def node_req(self, ru_id: int, drc_id: int, vnf: str) -> float:
        """
        CPU requirement của vnf khi RU ru_id chọn DRC drc_id
        """
        drc = self.drcs[drc_id]
        return _node_req(drc, vnf)

    # ---------- Link (BW) requirement ----------
    def link_req(self, ru_id: int, drc_id: int, seg: str) -> float:
        """
        BW requirement cho segment BH/MH/FH
        """
        drc = self.drcs[drc_id]
        return _link_req(drc, seg)

    # ---------- Delay constraint ----------
    def delay_req(self, ru_id: int, drc_id: int, seg: str) -> float:
        """
        Delay upper bound cho segment BH/MH/FH
        """
        drc = self.drcs[drc_id]
        return _delay_req(drc, seg)

    # ======================================================
    # HELPER FUNCTIONS (ILP rất hay dùng)
    # ======================================================

    def ru_location(self, ru_id: int) -> int:
        """
        Trả về CR node id nơi RU ru_id gắn vào
        """
        return self.rus[ru_id].cr

    def path_by_id(self, pid):
        for p in self.paths:
            if p.id == pid:
                return p
        raise KeyError(f"Path {pid} not found")

    def phy_nodes(self):
        return list(self.PHY.nodes)

    def phy_edges(self):
        return list(self.PHY.edges)

    # ======================================================
    # VALIDATION (nên gọi 1 lần trước khi solve)
    # ======================================================
    def sanity_check(self) -> None:
        # check RU locations exist
        for ru in self.rus.values():
            if ru.cr not in self.PHY.nodes:
                raise ValueError(f"RU {ru.id} attached to non-existing CR {ru.cr}")

        # check PHY attributes
        for i in self.PHY.nodes:
            if "cpu" not in self.PHY.nodes[i] and "cap" not in self.PHY.nodes[i]:
                raise ValueError(f"Node {i} has no cpu/cap attribute")

        for (i, j) in self.PHY.edges:
            if "capacity" not in self.PHY.edges[(i, j)] and "cap" not in self.PHY.edges[(i, j)]:
                raise ValueError(f"Edge {(i,j)} has no capacity/cap attribute")

        # check path format
        for p in self.paths:
            for attr in ["delay_BH", "delay_MH", "delay_FH"]:
                if not hasattr(p, attr):
                    raise ValueError(f"Path {p.id} missing {attr}")
