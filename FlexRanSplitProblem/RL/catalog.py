"""Build the fixed action catalog and resource demands for each RU."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np


SEGMENTS: Tuple[str, ...] = ("BH", "MH", "FH")


@dataclass(frozen=True)
class CandidateAction:
    """A statically feasible ``(DRC, path)`` choice for one RU.

    CPU and bandwidth usages are sparse ``(array_index, amount)`` tuples. Static
    feasibility covers the RU destination and delay constraints. Residual
    capacity is checked dynamically by the environment.
    """

    action_id: int
    ru_id: Any
    drc_id: Any
    path_id: Any
    cpu_usage: Tuple[Tuple[int, float], ...]
    bandwidth_usage: Tuple[Tuple[int, float], ...]
    latency: float


def _node_capacity(graph: Any, node_id: Any) -> float:
    attrs = graph.nodes[node_id]
    if "cpu" in attrs:
        return float(attrs["cpu"])
    if "cap" in attrs:
        return float(attrs["cap"])
    raise KeyError(f"Node {node_id!r} has neither 'cpu' nor 'cap'.")


def _edge_capacity(graph: Any, edge: Tuple[Any, Any]) -> float:
    attrs = graph.edges[edge]
    if "capacity" in attrs:
        return float(attrs["capacity"])
    if "cap" in attrs:
        return float(attrs["cap"])
    raise KeyError(f"Edge {edge!r} has neither 'capacity' nor 'cap'.")


def _segment_edges(path: Any, segment: str) -> Sequence[Tuple[Any, Any]]:
    return tuple(getattr(path, f"edges_{segment}"))


def _segment_delay(path: Any, segment: str) -> float:
    return float(getattr(path, f"delay_{segment}"))


def _path_latency(path: Any) -> float:
    return sum(_segment_delay(path, segment) for segment in SEGMENTS)


def _path_destination(path: Any) -> Optional[Any]:
    nodes = getattr(path, "nodes", None)
    if nodes:
        return nodes[-1]

    # Compatibility fallback for older path objects without ``nodes``.
    for segment in reversed(SEGMENTS):
        edges = _segment_edges(path, segment)
        if edges:
            return edges[-1][1]
    return None


def _placement_nodes(path: Any, core_id: Any, ru_node: Any) -> Tuple[Any, Any]:
    bh_edges = _segment_edges(path, "BH")
    mh_edges = _segment_edges(path, "MH")
    cu_node = core_id if not bh_edges else bh_edges[-1][1]
    du_node = cu_node if not mh_edges else mh_edges[-1][1]
    return cu_node, du_node


def _add_sparse(target: Dict[int, float], index: int, amount: float) -> None:
    amount = float(amount)
    if amount:
        target[index] = target.get(index, 0.0) + amount


class ActionCatalog:
    """Map fixed action ids to DRC/path pairs and precompute RU candidates.

    Action zero is always ``reject``. Remaining actions use the stable mapping

    ``1 + drc_index * number_of_paths + path_index``.
    """

    reject_action = 0

    def __init__(self, problem: Any) -> None:
        self.problem = problem
        self.graph = problem.PHY
        self.ru_ids = tuple(problem.flow_set)
        self.drc_ids = tuple(problem.Ks)
        self.paths = tuple(problem.paths)
        self.path_ids = tuple(path.id for path in self.paths)
        self.core_id = getattr(problem, "core", 0)

        self.node_ids = tuple(self.graph.nodes)
        self.edge_ids = tuple(tuple(edge) for edge in self.graph.edges)
        self.node_index = {node_id: idx for idx, node_id in enumerate(self.node_ids)}
        self.edge_index = {edge: idx for idx, edge in enumerate(self.edge_ids)}

        self.node_capacities = np.asarray(
            [_node_capacity(self.graph, node_id) for node_id in self.node_ids],
            dtype=np.float32,
        )
        self.edge_capacities = np.asarray(
            [_edge_capacity(self.graph, edge) for edge in self.edge_ids],
            dtype=np.float32,
        )

        self.action_count = 1 + len(self.drc_ids) * len(self.paths)
        self._action_pairs: Dict[int, Tuple[Any, Any]] = {}
        self._candidates: Dict[Any, Dict[int, CandidateAction]] = {
            ru_id: {} for ru_id in self.ru_ids
        }

        for drc_index, drc_id in enumerate(self.drc_ids):
            for path_index, path in enumerate(self.paths):
                action_id = 1 + drc_index * len(self.paths) + path_index
                self._action_pairs[action_id] = (drc_id, path.id)

        self._build_candidates()

    def pair_for_action(self, action_id: int) -> Optional[Tuple[Any, Any]]:
        """Return ``(drc_id, path_id)`` or ``None`` for reject."""

        if action_id == self.reject_action:
            return None
        try:
            return self._action_pairs[int(action_id)]
        except KeyError as exc:
            raise IndexError(f"Action {action_id} is outside the action catalog.") from exc

    def candidate(self, ru_id: Any, action_id: int) -> Optional[CandidateAction]:
        """Return a statically feasible candidate for this RU, if one exists."""

        return self._candidates[ru_id].get(int(action_id))

    def candidates_for_ru(self, ru_id: Any) -> Mapping[int, CandidateAction]:
        return self._candidates[ru_id]

    def statically_feasible_actions(self, ru_id: Any) -> Iterable[int]:
        return self._candidates[ru_id].keys()

    def _build_candidates(self) -> None:
        for ru_id in self.ru_ids:
            ru_node = self.problem.ru_location(ru_id)
            if ru_node not in self.node_index:
                raise ValueError(f"RU {ru_id!r} is attached to unknown node {ru_node!r}.")

            for drc_index, drc_id in enumerate(self.drc_ids):
                for path_index, path in enumerate(self.paths):
                    action_id = 1 + drc_index * len(self.paths) + path_index
                    candidate = self._make_candidate(
                        action_id=action_id,
                        ru_id=ru_id,
                        ru_node=ru_node,
                        drc_id=drc_id,
                        path=path,
                    )
                    if candidate is not None:
                        self._candidates[ru_id][action_id] = candidate

    def _make_candidate(
        self,
        action_id: int,
        ru_id: Any,
        ru_node: Any,
        drc_id: Any,
        path: Any,
    ) -> Optional[CandidateAction]:
        # A path generated for a different RU must never be selected.
        if _path_destination(path) != ru_node:
            return None

        for segment in SEGMENTS:
            if _segment_delay(path, segment) > float(
                self.problem.delay_req(ru_id, drc_id, segment)
            ) + 1e-9:
                return None

        cu_node, du_node = _placement_nodes(path, self.core_id, ru_node)
        placement = (
            (cu_node, "vcu"),
            (du_node, "vdu"),
            (ru_node, "vru"),
        )
        cpu: Dict[int, float] = {}
        for node_id, vnf in placement:
            if node_id not in self.node_index:
                return None
            _add_sparse(
                cpu,
                self.node_index[node_id],
                self.problem.node_req(ru_id, drc_id, vnf),
            )

        bandwidth: Dict[int, float] = {}
        for segment in SEGMENTS:
            amount = self.problem.link_req(ru_id, drc_id, segment)
            for raw_edge in _segment_edges(path, segment):
                edge = tuple(raw_edge)
                edge_index = self.edge_index.get(edge)
                if edge_index is None:
                    return None
                _add_sparse(bandwidth, edge_index, amount)

        return CandidateAction(
            action_id=action_id,
            ru_id=ru_id,
            drc_id=drc_id,
            path_id=path.id,
            cpu_usage=tuple(sorted(cpu.items())),
            bandwidth_usage=tuple(sorted(bandwidth.items())),
            latency=_path_latency(path),
        )
