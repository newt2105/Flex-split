"""Problem data and notation shared by the ILP and learning environments."""

from __future__ import annotations

import gzip
import pickle
import uuid
from typing import Any, Dict, List, Sequence, Tuple

import networkx as nx

from .phy.ran_model import (
    DRC,
    RU,
    VNFS,
    VLINKS,
    delay_req as _delay_req,
    link_req as _link_req,
    node_req as _node_req,
)


class FlexRanSplitProblem:
    """Container for the physical network and the NSCs to be embedded.

    Public set names mirror the paper: ``N``, ``E``, ``S``, ``K``, ``V``,
    ``virtual_links``, and ``paths_for_slice(s)`` (the set :math:`P_s`).
    ``active_vnfs(k)`` and ``active_virtual_links(k)`` provide the actual
    service chain of DRC ``k`` after zero-resource CU/DU stages are removed.
    The older attribute names remain as aliases for the RL code.
    """

    def __init__(
        self,
        physical_network: nx.Graph,
        paths: Sequence[Any],
        rus: Dict[int, RU],
        drcs: Dict[int, DRC],
        core_id: int = 0,
        name: str | None = None,
    ) -> None:
        self.name = name or f"FlexRanSplitProblem-{uuid.uuid4()}"

        # Physical network G = (N, E).
        self.PHY = physical_network
        self.core = core_id
        self.N = tuple(physical_network.nodes)
        self.E = tuple(physical_network.edges)

        # Physical paths P and endpoint demands/NSCs S.
        self.paths = list(paths)
        self.rus = dict(rus)
        self.S = tuple(rus.keys())

        # DRC configurations K, VNF set N_s, and virtual-link set E_s.
        self.drcs = dict(drcs)
        self.K = tuple(drcs.keys())
        self.V = tuple(VNFS)
        self.virtual_links = tuple(VLINKS)

        # Backward-compatible aliases used by the existing RL implementation.
        self.flow_set = list(self.S)
        self.Ks = list(self.K)
        self.vnfs = self.V
        self.vlinks = self.virtual_links

        self.solution: Dict[str, Any] | None = None
        self.status = -1
        self.solution_status = None
        self.solver_time = None

    # ------------------------------------------------------------------
    # Resource parameters R_{s,k,v} and R_{s,k,vw}.
    # ------------------------------------------------------------------
    def node_req(self, slice_id: int, drc_id: int, vnf: str) -> float:
        """Return node resource required by VNF ``vnf`` under DRC ``drc_id``."""
        del slice_id  # Requirements are currently identical across NSCs.
        return float(_node_req(self.drcs[drc_id], vnf))

    def link_req(self, slice_id: int, drc_id: int, segment: str) -> float:
        """Return bandwidth required by a virtual link under a DRC."""
        del slice_id
        return float(_link_req(self.drcs[drc_id], segment))

    def delay_req(self, slice_id: int, drc_id: int, segment: str) -> float:
        """Legacy per-segment delay bound retained for RL compatibility."""
        del slice_id
        return float(_delay_req(self.drcs[drc_id], segment))

    def active_vnfs(self, drc_id: int) -> Tuple[str, ...]:
        """Return only the VNF stages that exist for one DRC.

        ``vupf`` is retained as the fixed transport anchor at the core and
        ``vru`` as the RU endpoint.  A CU or DU with zero CPU requirement is
        absent from the service chain and therefore has no placement variable.
        """
        drc = self.drcs[drc_id]
        active = ["vupf"]
        if float(drc.cpu_CU) > 0.0:
            active.append("vcu")
        if float(drc.cpu_DU) > 0.0:
            active.append("vdu")
        active.append("vru")
        return tuple(active)

    def active_virtual_links(
        self,
        drc_id: int,
    ) -> Tuple[Tuple[str, str, str], ...]:
        """Return the DRC-specific chain and its BH/MH/FH resource labels."""
        active = self.active_vnfs(drc_id)
        links = []
        previous = "vupf"
        if "vcu" in active:
            links.append((previous, "vcu", "BH"))
            previous = "vcu"
        if "vdu" in active:
            links.append((previous, "vdu", "MH"))
            previous = "vdu"
        links.append((previous, "vru", "FH"))
        return tuple(links)

    # ------------------------------------------------------------------
    # Physical path helpers.
    # ------------------------------------------------------------------
    def ru_location(self, slice_id: int) -> int:
        """Return the physical endpoint of NSC ``slice_id`` (its RU node)."""
        return self.rus[slice_id].cr

    def paths_for_slice(self, slice_id: int) -> List[Any]:
        """Return the deduplicated path set :math:`P_s` for one NSC.

        Old path files contain one record per preselected CU/DU placement.  The
        new ILP makes placement a decision, so paths with the same physical
        node sequence are intentionally collapsed here.
        """
        terminal = self.ru_location(slice_id)
        unique_paths = []
        seen_node_sequences = set()
        for path in self.paths:
            nodes = tuple(getattr(path, "nodes", ()))
            if not nodes or nodes[0] != self.core or nodes[-1] != terminal:
                continue
            if nodes in seen_node_sequences:
                continue
            seen_node_sequences.add(nodes)
            unique_paths.append(path)
        return unique_paths

    def path_by_id(self, path_id: Any) -> Any:
        for path in self.paths:
            if path.id == path_id:
                return path
        raise KeyError(f"Path {path_id} not found")

    def phy_nodes(self) -> List[Any]:
        return list(self.N)

    def phy_edges(self) -> List[Tuple[Any, Any]]:
        return list(self.E)

    # ------------------------------------------------------------------
    # Input validation.
    # ------------------------------------------------------------------
    def sanity_check(self) -> None:
        if self.core not in self.PHY:
            raise ValueError(f"Core node {self.core} is not in the physical graph")
        if not self.S:
            raise ValueError("At least one NSC/RU is required")
        if not self.K:
            raise ValueError("At least one DRC is required")

        for slice_id, ru in self.rus.items():
            if ru.cr not in self.PHY:
                raise ValueError(
                    f"RU {slice_id} is attached to missing physical node {ru.cr}"
                )

        for i, attributes in self.PHY.nodes(data=True):
            if not any(key in attributes for key in ("cpu", "cap", "capacity")):
                raise ValueError(f"Physical node {i} has no resource capacity")

        for i, j, attributes in self.PHY.edges(data=True):
            if not any(key in attributes for key in ("capacity", "cap", "bandwidth")):
                raise ValueError(f"Physical link {(i, j)} has no bandwidth capacity")

        path_ids = [path.id for path in self.paths]
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("Physical path IDs must be unique")

        for path in self.paths:
            nodes = tuple(getattr(path, "nodes", ()))
            if len(nodes) < 2:
                raise ValueError(f"Path {path.id} must contain at least two nodes")
            if nodes[0] != self.core:
                raise ValueError(f"Path {path.id} does not originate at core {self.core}")
            if len(nodes) != len(set(nodes)):
                raise ValueError(f"Path {path.id} is not a simple physical path")
            for u, v in zip(nodes, nodes[1:]):
                if not self.PHY.has_edge(u, v) and not (
                    not self.PHY.is_directed() and self.PHY.has_edge(v, u)
                ):
                    raise ValueError(
                        f"Path {path.id} contains missing physical link {(u, v)}"
                    )

        for slice_id in self.S:
            if not self.paths_for_slice(slice_id):
                raise ValueError(f"NSC {slice_id} has no path from the core to its RU")

        for slice_id in self.S:
            for drc_id in self.K:
                for vnf in self.V:
                    if self.node_req(slice_id, drc_id, vnf) < 0:
                        raise ValueError("VNF resource requirements must be non-negative")
                for _v, _w, segment in self.virtual_links:
                    if self.link_req(slice_id, drc_id, segment) < 0:
                        raise ValueError("Virtual-link requirements must be non-negative")

    @staticmethod
    def saveToFile(filename: str, problem: "FlexRanSplitProblem") -> None:
        with gzip.open(filename, "wb") as stream:
            pickle.dump(problem, stream)

    @staticmethod
    def loadFromFile(filename: str) -> "FlexRanSplitProblem":
        with gzip.open(filename, "rb") as stream:
            return pickle.load(stream)

    def __repr__(self) -> str:
        return (
            f"FlexRanSplitProblem(name={self.name!r}, "
            f"physical_nodes={self.PHY.number_of_nodes()}, "
            f"physical_edges={self.PHY.number_of_edges()}, "
            f"num_slices={len(self.S)}, num_drcs={len(self.K)})"
        )
