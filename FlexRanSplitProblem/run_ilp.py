"""Command-line runner for the flexible RAN placement ILP."""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime
from pathlib import Path

import pulp

from .common import FlexRanSplitProblem
from .lp_formulation import DEFAULT_BETA, extract_solution, formulateLp
from .phy.ran_model import DRC_structure_T2, build_rus_from_nodes_json_T2


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_NODES = PACKAGE_DIR / "model_files" / "T2_files" / "F1_8_CRs_nodes_LC.json"
DEFAULT_PATHS = PACKAGE_DIR / "phy" / "paths.pkl"
DEFAULT_PHY = PACKAGE_DIR / "phy" / "phy.pkl"
DEFAULT_RESULTS = PACKAGE_DIR / "results"


def save_sol(lp: pulp.LpProblem, filepath: Path) -> None:
    """Save nonzero raw decision-variable values in a readable text format."""
    with filepath.open("w", encoding="utf-8") as stream:
        stream.write(f"# Solution for model {lp.name}\n")
        stream.write(f"# Objective value = {pulp.value(lp.objective)}\n")
        for variable in lp.variables():
            if variable.varValue is not None and abs(variable.varValue) > 1e-6:
                stream.write(f"{variable.name} {variable.varValue}\n")


def build_solver(name: str, msg: bool) -> pulp.LpSolver:
    if name == "cbc":
        return pulp.PULP_CBC_CMD(msg=msg)
    if name == "gurobi":
        return pulp.GUROBI_CMD(msg=msg)

    available = set(pulp.listSolvers(onlyAvailable=True))
    if "GUROBI_CMD" in available:
        return pulp.GUROBI_CMD(msg=msg)
    return pulp.PULP_CBC_CMD(msg=msg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solve the flexible RAN placement ILP")
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--paths", type=Path, default=DEFAULT_PATHS)
    parser.add_argument("--phy", type=Path, default=DEFAULT_PHY)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--core", type=int, default=0)
    parser.add_argument("--beta", type=float, default=DEFAULT_BETA)
    parser.add_argument("--solver", choices=("auto", "cbc", "gurobi"), default="auto")
    parser.add_argument("--solver-log", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.results.mkdir(parents=True, exist_ok=True)

    with args.phy.open("rb") as stream:
        physical_network = pickle.load(stream)
    with args.paths.open("rb") as stream:
        paths = pickle.load(stream)

    problem = FlexRanSplitProblem(
        physical_network=physical_network,
        paths=paths,
        rus=build_rus_from_nodes_json_T2(str(args.nodes)),
        drcs=DRC_structure_T2(),
        core_id=args.core,
        name="Flexible_RAN_Placement",
    )

    model = formulateLp(problem, beta=args.beta)
    solver = build_solver(args.solver, args.solver_log)

    started = time.perf_counter()
    model.solve(solver)
    problem.solver_time = time.perf_counter() - started
    problem.solution_status = model.status

    status = pulp.LpStatus[model.status]
    print(f"Solver status: {status}")
    print(f"Solve time: {problem.solver_time:.3f} s")
    if status != "Optimal":
        raise RuntimeError(f"The ILP did not reach an optimal solution: {status}")

    solution = extract_solution(problem, model)
    problem.solution = {
        "objective": pulp.value(model.objective),
        "beta": args.beta,
        "slices": solution,
    }
    problem.status = 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    semantic_path = args.results / f"solution_{timestamp}.json"
    raw_path = args.results / f"solution_{timestamp}.sol"
    snapshot_path = args.results / f"problem_{timestamp}.pkl.gz"

    with semantic_path.open("w", encoding="utf-8") as stream:
        json.dump(problem.solution, stream, indent=2)
    save_sol(model, raw_path)
    FlexRanSplitProblem.saveToFile(str(snapshot_path), problem)

    print(f"Objective: {pulp.value(model.objective):.6f}")
    print(f"Semantic solution: {semantic_path}")
    print(f"Raw variables: {raw_path}")
    print(f"Problem snapshot: {snapshot_path}")
    for item in solution:
        print(
            f"NSC {item['slice']}: DRC={item['drc']}, path={item['path']}, "
            f"placement={item['vnf_placement']}"
        )


if __name__ == "__main__":
    main()
