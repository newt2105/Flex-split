import numpy as np
import networkx as nx
import pickle as pkl
import gzip as gz
import uuid
import pulp
from typing import Any, List, Dict, Tuple

from .phy.ran_model import (
    RU,
    DRC,
    VNFS,
    VLINKS,
    node_req as _node_req,
    link_req as _link_req,
    delay_req as _delay_req,
)

class FlexRanSplitProblem:
    def __init__(
        self,
        physical_network: nx.DiGraph,
        paths: List,
        rus: Dict[int, RU],
        drcs: Dict[int, DRC],
        core_id: int = 0,
        name: str = None
    ):
        self.name = "FlexRanSplitProblem-" + str(uuid.uuid4()) if name is None else name
        # input attributes
        self.PHY  = physical_network
        self.paths = paths
        self.core: int = core_id
        self.rus = rus
        self.drcs = drcs
        
        self.flow_set = list(rus.keys())        # sb
        self.Ks = list(drcs.keys())              # DRC ids
        self.vnfs = VNFS                         # ("vupf","vcu","vdu","vru")
        self.vlinks = VLINKS 
        # solution attributes
        self.solution: Dict[str, Any] = None
        self.status: int = -1 # -1: not solved, 0: infeasible, 1: solved
        self.solution_status = None # solver specific status code
        self.solver_time = None # time taken by the solver

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
    
    @staticmethod
    def saveToFile(filename: str, problem: 'FlexRanSplitProblem') -> None:
        with gz.open(filename, 'wb') as f:
            pkl.dump(problem, f)
    
    @staticmethod
    def loadFromFile(filename: str) -> 'FlexRanSplitProblem':
        with gz.open(filename, 'rb') as f:
            return pkl.load(f)
        
    def __repr__(self) -> str:
        return f"FlexRanSplitProblem(name={self.name}, physical_network_nodes={self.physical_network.number_of_nodes()}, physical_network_edges={self.physical_network.number_of_edges()}, num_flows={len(self.flow_set)})"
    
