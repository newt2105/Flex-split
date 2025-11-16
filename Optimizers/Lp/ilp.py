from ..common import Optimizer

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from FlexRanSplitProblem import FlexRanSplitProblem, formulateLp

import pulp

class ILPOptimizer(Optimizer):
    def __init__(self):
        super().__init__()
        self.solver: pulp.LpSolver|pulp.LpSolver_CMD = pulp.GUROBI_CMD() # replace and tweeks LpSolvers here
    
    def optimize(self, problem: FlexRanSplitProblem) -> FlexRanSplitProblem:
        _lp_problem = formulateLp(problem)
        _lp_problem.solve(self.solver)
        raise NotImplementedError("This is abtraction class. Please use solver-specific class (gurobi, cplex, ...).")
    
