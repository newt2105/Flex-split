import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from FlexRanSplitProblem import FlexRanSplitProblem

class Optimizer:
    def __init__(self):
        pass
    
    def optimize(self, problem: 'FlexRanSplitProblem') -> 'FlexRanSplitProblem':
        raise NotImplementedError("This method should be overridden by subclasses.")