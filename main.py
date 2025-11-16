from FlexRanSplitProblem import FlexRanSplitProblem as FRP
from Optimizers import Optimizer as Opt
import argparse
import os
import time
import networkx as nx
import numpy as np
import sys
from utilities.platform import checkEnv

def main():
    args = argparse.ArgumentParser(description="FlexRan Split Problem Simulator")
    args.add_argument("task", type=str, choices=["placeran", "generate", "optimize", "evaluate", "visualize"], help="Task to perform")
    args.add_argument("-c", "--config", type=str, required=False, help="Path to configuration file")
    args.add_argument("-o", "--output", type=str, required=False, help="Path to output results")
    args = args.parse_args()
    os.makedirs("data", exist_ok=True)
    time_st = time.time()
    print(f">>> Task={args.task} Config={args.config} Output={args.output}")
    if args.task == "placeran":
        os.system(f"cd PlaceRAN && python run_model.py")
    if args.task == "generate":
        raise NotImplementedError("Task is not implemented yet.")
    if args.task == "optimize":
        raise NotImplementedError("Task is not implemented yet.")
    if args.task == "evaluate":
        raise NotImplementedError("Task is not implemented yet.")
    if args.task == "visualize":
        raise NotImplementedError("Task is not implemented yet.")
    time_ed = time.time()
    print(f">>> Total time taken: {time_ed - time_st:.2f} seconds")

if __name__ == "__main__":
    print("================================")
    print("=    FlexRANSplit Simulator    =")
    print("================================")
    checkEnv()
    print("================================")
    main()