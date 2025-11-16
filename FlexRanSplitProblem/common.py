import numpy as np
import networkx as nx
import pickle as pkl
import gzip as gz
import uuid
import pulp
from typing import Any, List, Dict, Tuple

class FlexRanSplitProblem:
    def __init__(
        self,
        physical_network: nx.DiGraph,
        flow_set: List[List[nx.DiGraph]], 
        name: str = None
    ):
        self.name = "FlexRanSplitProblem-" + str(uuid.uuid4()) if name is None else name
        # input attributes
        self.physical_network = physical_network
        self.flow_set = flow_set
        # solution attributes
        self.solution: Dict[str, Any] = None
        self.status: int = -1 # -1: not solved, 0: infeasible, 1: solved
        self.solution_status = None # solver specific status code
        self.solver_time = None # time taken by the solver
    
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
    
