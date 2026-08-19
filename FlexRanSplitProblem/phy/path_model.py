"""Physical path representation used by the ILP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Path:
    """A core-to-RU physical path.

    ``nodes`` and ``latency`` are the fields used by the new formulation.  The
    BH/MH/FH fields are retained so existing pickles and the RL catalog remain
    readable; placement is no longer encoded by those segments in the ILP.
    """

    id: int
    nodes: List[int]
    edges_BH: List[Tuple[int, int]] = field(default_factory=list)
    edges_MH: List[Tuple[int, int]] = field(default_factory=list)
    edges_FH: List[Tuple[int, int]] = field(default_factory=list)
    delay_BH: float = 0.0
    delay_MH: float = 0.0
    delay_FH: float = 0.0
    latency: Optional[float] = None

    @property
    def edges(self) -> List[Tuple[int, int]]:
        return list(zip(self.nodes, self.nodes[1:]))

    @property
    def total_latency(self) -> float:
        # ``__dict__.get`` also works for legacy pickles created before the
        # latency field existed.
        latency = self.__dict__.get("latency")
        if latency is not None:
            return float(latency)
        return float(self.delay_BH + self.delay_MH + self.delay_FH)
