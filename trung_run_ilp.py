"""ILP runner using an in-memory heterogeneous physical network."""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime
from pathlib import Path

import pulp

from .common import FlexRanSplitProblem
from .lp_formulation import extract_solution, formulateLp
from .phy.ran_model import DRC_structure_T2, build_rus_from_nodes_json_T2
from .run_ilp import (
    DEFAULT_SETTINGS,
    REPO_DIR,
    build_solver,
    load_settings,
    save_sol,
    save_solution_csv,
)

# Deterministic heterogeneous scaling. Core CPU is kept unchanged.
# NODE_CPU_FACTORS = (0.55, 0.75, 0.95)
# LINK_BW_FACTORS = (0.40, 0.55, 0.70, 0.85)


# NODE_CPU_FACTORS = (0.5, 0.7, 0.9)
# LINK_BW_FACTORS = (0.4, 0.5, 0.7, 0.8)

NODE_CPU_FACTORS = (0.55, 0.75, 0.95)
LINK_BW_FACTORS = (0.40, 0.55, 0.70, 0.85)


def make_heterogeneous(physical_network, *, core_id: int = 0, verbose: bool = True):
    """Modify all non-core node CPU capacities and all link capacities in memory.

    Topology and delays are unchanged. For each physical link, both directions
    receive the same new bandwidth, matching the way genphy.py constructs T2.
    """
    nodes = sorted(n for n in physical_network.nodes if n != core_id)

    if verbose:
        print("\n=== Heterogeneous PHY: node CPU ===")

    for idx, node in enumerate(nodes):
        factor = NODE_CPU_FACTORS[idx % len(NODE_CPU_FACTORS)]
        old_cpu = float(physical_network.nodes[node].get("cpu", 0.0))
        new_cpu = old_cpu * factor
        physical_network.nodes[node]["cpu"] = new_cpu
        if verbose:
            print(f"node {node:>4}: CPU {old_cpu:>8.3f} x {factor:.2f} -> {new_cpu:>8.3f}")

    # genphy.py stores each physical link in both directions. Process each
    # unordered pair once, then write the same capacity in both directions.
    pairs = sorted({tuple(sorted((u, v))) for u, v in physical_network.edges if u != v})

    if verbose:
        print("\n=== Heterogeneous PHY: link bandwidth ===")

    for idx, (u, v) in enumerate(pairs):
        factor = LINK_BW_FACTORS[idx % len(LINK_BW_FACTORS)]
        capacities = []
        if physical_network.has_edge(u, v):
            capacities.append(float(physical_network[u][v]["capacity"]))
        if physical_network.has_edge(v, u):
            capacities.append(float(physical_network[v][u]["capacity"]))
        if not capacities:
            continue

        old_bw = min(capacities)
        new_bw = old_bw * factor

        if physical_network.has_edge(u, v):
            physical_network[u][v]["capacity"] = new_bw
        if physical_network.has_edge(v, u):
            physical_network[v][u]["capacity"] = new_bw

        if verbose:
            print(f"link {u:>4}<->{v:<4}: BW {old_bw:>8.3f} x {factor:.2f} -> {new_bw:>8.3f}")

    if verbose:
        print("========================================\n")
    return physical_network


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_DIR / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solve Flex-split on a heterogeneous PHY")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--nodes", type=Path)
    parser.add_argument("--paths", type=Path)
    parser.add_argument("--phy", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--core", type=int)
    parser.add_argument("--beta", type=float)
    parser.add_argument("--solver", choices=("auto", "cbc", "gurobi"))
    parser.add_argument("--solver-log", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--quiet-hetero", action="store_true")
    args = parser.parse_args()

    settings = load_settings(args.settings)

    for key in ("nodes", "paths", "phy"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = _resolve_repo_path(value)

    for key in ("core", "beta", "solver", "solver_log"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value

    network = settings["network"]
    settings["results"] = (
        _resolve_repo_path(args.results)
        if args.results is not None
        else REPO_DIR / "results_hetero" / f"network_{network}"
    )
    settings["csv"] = (
        _resolve_repo_path(args.csv)
        if args.csv is not None
        else REPO_DIR / "results_hetero" / f"network_{network}" / "solution.csv"
    )
    settings["quiet_hetero"] = args.quiet_hetero

    if not 0.0 <= settings["beta"] <= 1.0:
        parser.error("beta must be between 0 and 1")

    return argparse.Namespace(**settings)


def main() -> None:
    args = parse_args()
    args.results.mkdir(parents=True, exist_ok=True)

    print(f"Settings: {args.settings.resolve()}")
    print(f"PHY     : {args.phy.resolve()}")
    print(f"Paths   : {args.paths.resolve()}")
    print(f"Nodes   : {args.nodes.resolve()}")
    print(f"Results : {args.results.resolve()}")

    with args.phy.open("rb") as stream:
        physical_network = pickle.load(stream)

    physical_network = make_heterogeneous(
        physical_network,
        core_id=args.core,
        verbose=not args.quiet_hetero,
    )

    with args.paths.open("rb") as stream:
        paths = pickle.load(stream)

    rus = build_rus_from_nodes_json_T2(str(args.nodes))

    problem = FlexRanSplitProblem(
        physical_network=physical_network,
        paths=paths,
        rus=rus,
        drcs=DRC_structure_T2(),
        core_id=args.core,
        name="Flexible_RAN_Placement_Heterogeneous",
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
        raise RuntimeError(f"The heterogeneous ILP did not reach an optimal solution: {status}")

    solution = extract_solution(problem, model)
    problem.solution = {
        "objective": pulp.value(model.objective),
        "beta": args.beta,
        "heterogeneous": True,
        "node_cpu_factors": NODE_CPU_FACTORS,
        "link_bw_factors": LINK_BW_FACTORS,
        "slices": solution,
    }
    problem.status = 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    objective = float(pulp.value(model.objective))
    csv_path = save_solution_csv(
        args.csv,
        solution,
        runtime=problem.solver_time,
        append=args.csv_append,
    )

    semantic_path = args.results / f"solution_{timestamp}.json"
    raw_path = args.results / f"solution_{timestamp}.sol"
    snapshot_path = args.results / f"problem_{timestamp}.pkl.gz"

    if args.save_json:
        with semantic_path.open("w", encoding="utf-8") as stream:
            json.dump(problem.solution, stream, indent=2)
    if args.save_sol:
        save_sol(model, raw_path)
    if args.save_snapshot:
        FlexRanSplitProblem.saveToFile(str(snapshot_path), problem)

    print(f"Objective: {objective:.6f}")
    print(f"CSV result: {csv_path.resolve()}")
    drcs_used = sorted({item["drc"] for item in solution})
    print(f"Distinct DRCs: {len(drcs_used)} -> {drcs_used}")

    for item in solution:
        latency = item.get("latency")
        latency_text = "None" if latency is None else f"{latency:.3f}"
        print(
            f"NSC {item['slice']}: DRC={item['drc']}, path={item['path']}, "
            f"L={latency_text}, placement={item['vnf_placement']}"
        )


if __name__ == "__main__":
    main()
