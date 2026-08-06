from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class Path:
    id: int
    nodes: List[int]
    edges_BH: List[Tuple[int, int]]
    edges_MH: List[Tuple[int, int]]
    edges_FH: List[Tuple[int, int]]
    delay_BH: float
    delay_MH: float
    delay_FH: float
