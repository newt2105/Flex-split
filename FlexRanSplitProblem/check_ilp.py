"""Small inspection harness for the flexible RAN placement ILP.

Run this file directly from ``FlexRanSplitProblem``::

    python check_ilp.py data
    python check_ilp.py model
    python check_ilp.py variables --family y --limit 30
    python check_ilp.py constraints --prefix C7 --limit 20
    python check_ilp.py solve --solver cbc --beta 0.5
    python check_ilp.py all --solver cbc

You can also import and call only the functions you need::

    from FlexRanSplitProblem.check_ilp import load_problem, build_model

    problem = load_problem()
    model = build_model(problem, beta=0.5)
"""

from __future__ import annotations

import argparse
import pickle
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import pulp


# Support both ``python check_ilp.py`` and
# ``python -m FlexRanSplitProblem.check_ilp``.
try:
    from .common import FlexRanSplitProblem
    from .helper import path_latency
    from .lp_formulation import DEFAULT_BETA, extract_solution, formulateLp
    from .phy.ran_model import DRC_structure_T2, build_rus_from_nodes_json_T2
    from .run_ilp import (
        DEFAULT_NODES,
        DEFAULT_PATHS,
        DEFAULT_PHY,
        build_solver,
    )
except ImportError:  # pragma: no cover - used only in direct-script mode
    PACKAGE_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(PACKAGE_DIR.parent))
    from FlexRanSplitProblem.common import FlexRanSplitProblem
    from FlexRanSplitProblem.helper import path_latency
    from FlexRanSplitProblem.lp_formulation import (
        DEFAULT_BETA,
        extract_solution,
        formulateLp,
    )
    from FlexRanSplitProblem.phy.ran_model import (
        DRC_structure_T2,
        build_rus_from_nodes_json_T2,
    )
    from FlexRanSplitProblem.run_ilp import (
        DEFAULT_NODES,
        DEFAULT_PATHS,
        DEFAULT_PHY,
        build_solver,
    )


def load_problem(
    phy_path: str | Path = DEFAULT_PHY,
    paths_path: str | Path = DEFAULT_PATHS,
    nodes_path: str | Path = DEFAULT_NODES,
    core_id: int = 0,
) -> FlexRanSplitProblem:
    """Load the default T2 topology, physical paths, RUs, and DRCs."""
    phy_path = Path(phy_path)
    paths_path = Path(paths_path)
    nodes_path = Path(nodes_path)

    with phy_path.open("rb") as stream:
        physical_network = pickle.load(stream)
    with paths_path.open("rb") as stream:
        paths = pickle.load(stream)

    return FlexRanSplitProblem(
        physical_network=physical_network,
        paths=paths,
        rus=build_rus_from_nodes_json_T2(str(nodes_path)),
        drcs=DRC_structure_T2(),
        core_id=core_id,
        name="Flexible_RAN_Placement_Check",
    )


def check_data(problem: FlexRanSplitProblem, verbose: bool = True) -> Dict[str, Any]:
    """Validate input data and return a compact summary."""
    problem.sanity_check()
    paths_per_slice = {
        slice_id: len(problem.paths_for_slice(slice_id))
        for slice_id in problem.S
    }
    summary = {
        "physical_nodes": len(problem.N),
        "physical_links": len(problem.E),
        "slices": len(problem.S),
        "drcs": len(problem.K),
        "raw_path_records": len(problem.paths),
        "unique_paths_per_slice": paths_per_slice,
    }

    if verbose:
        print("[OK] Input data passed sanity_check()")
        print(f"Physical graph : |N|={summary['physical_nodes']}, |E|={summary['physical_links']}")
        print(f"NSCs / slices  : {list(problem.S)}")
        print(f"DRCs           : {list(problem.K)}")
        print(f"Raw path rows  : {summary['raw_path_records']}")
        for slice_id in problem.S:
            ru_node = problem.ru_location(slice_id)
            paths = problem.paths_for_slice(slice_id)
            details = ", ".join(
                f"p{path.id}:L={path_latency(path):.3f}"
                for path in paths
            )
            print(f"P_{slice_id} -> RU node {ru_node}: {len(paths)} path(s) [{details}]")

    return summary


def print_drc_parameters(problem: FlexRanSplitProblem) -> None:
    """Print node and link requirements for every DRC in K."""
    first_slice = problem.S[0]
    header = (
        "DRC | CPU(vcu,vdu,vru) | BW(vupf-vcu,vcu-vdu,vdu-vru)"
    )
    print(header)
    print("-" * len(header))
    for drc_id in problem.K:
        cpu = [
            problem.node_req(first_slice, drc_id, vnf)
            for vnf in ("vcu", "vdu", "vru")
        ]
        bandwidth = [
            problem.link_req(first_slice, drc_id, segment)
            for segment in ("BH", "MH", "FH")
        ]
        print(f"{drc_id:>3} | {cpu!s:<16} | {bandwidth}")


def build_model(
    problem: FlexRanSplitProblem,
    beta: float = DEFAULT_BETA,
    verbose: bool = True,
) -> pulp.LpProblem:
    """Build the ILP and optionally print its structural summary."""
    model = formulateLp(problem, beta=beta)
    if verbose:
        print_model_summary(model)
    return model


def _constraint_family(name: str) -> str:
    match = re.match(r"^(C\d+[a-z]?)_", name)
    return match.group(1) if match else "other"


def print_model_summary(model: pulp.LpProblem) -> Dict[str, Any]:
    """Print and return variable/constraint counts by paper notation."""
    variable_counts = {
        family: len(variables)
        for family, variables in model._vars.items()
    }
    constraint_counts = Counter(
        _constraint_family(name)
        for name in model.constraints
    )
    expected_c2b = len(model._sets["S"]) * len(model._sets["K"])
    actual_c2b = constraint_counts.get("C2b", 0)
    if actual_c2b != expected_c2b:
        raise AssertionError(
            "Model is missing DRC/path consistency constraints: "
            f"expected {expected_c2b} C2b constraints, found {actual_c2b}"
        )
    summary = {
        "name": model.name,
        "variables": len(model.variables()),
        "constraints": len(model.constraints),
        "variable_families": variable_counts,
        "constraint_families": dict(sorted(constraint_counts.items())),
        "beta": model._objective_terms["beta"],
        "latency_normalizer": model._objective_terms["latency_normalizer"],
    }

    print("[OK] ILP built successfully")
    print(f"Model           : {summary['name']}")
    print(f"Variables       : {summary['variables']} {variable_counts}")
    print(f"Constraints     : {summary['constraints']} {summary['constraint_families']}")
    print(f"beta            : {summary['beta']}")
    print(f"Latency scale   : {summary['latency_normalizer']}")
    return summary


def print_variables(
    model: pulp.LpProblem,
    family: str | None = None,
    limit: int = 20,
    nonzero_only: bool = False,
) -> None:
    """Print variables from one notation family, optionally after solving."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if family is not None and family not in model._vars:
        raise ValueError(
            f"Unknown family {family!r}; choose from {list(model._vars)}"
        )

    families = [family] if family else list(model._vars)
    printed = 0
    for family_name in families:
        print(f"\n[{family_name}]")
        for key, variable in model._vars[family_name].items():
            value = pulp.value(variable)
            if nonzero_only and (value is None or abs(value) <= 1e-9):
                continue
            print(f"{key}: name={variable.name}, value={value}")
            printed += 1
            if printed >= limit:
                print(f"... stopped at limit={limit}")
                return


def print_constraints(
    model: pulp.LpProblem,
    prefix: str | None = None,
    limit: int = 20,
) -> None:
    """Print constraints, filtered by names such as C1, C2b, or C7."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    printed = 0
    for name, constraint in model.constraints.items():
        if prefix and not name.startswith(prefix):
            continue
        print(f"{name}: {constraint}")
        printed += 1
        if printed >= limit:
            print(f"... stopped at limit={limit}")
            return
    if printed == 0:
        print("No matching constraints")


def export_lp(model: pulp.LpProblem, destination: str | Path) -> Path:
    """Export the generated algebraic model to an LP text file."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model.writeLP(str(destination))
    print(f"[OK] LP file written to {destination.resolve()}")
    return destination


def solve_model(
    model: pulp.LpProblem,
    solver_name: str = "auto",
    solver_log: bool = False,
) -> str:
    """Solve a built model and return its PuLP status string."""
    solver = build_solver(solver_name, solver_log)
    started = time.perf_counter()
    status_code = model.solve(solver)
    elapsed = time.perf_counter() - started
    status = pulp.LpStatus[status_code]
    print(f"Solver status   : {status}")
    print(f"Objective       : {pulp.value(model.objective)}")
    print(f"Elapsed         : {elapsed:.3f} s")
    return status


def check_solution(
    problem: FlexRanSplitProblem,
    model: pulp.LpProblem,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """Check selected DRC/path consistency and VNF/link ordering."""
    status = pulp.LpStatus[model.status]
    if status != "Optimal":
        raise ValueError(f"Cannot check a non-optimal model (status={status})")

    solution = extract_solution(problem, model)
    errors: List[str] = []
    selected_drcs = set()

    for item in solution:
        slice_id = item["slice"]
        if not item["deployed"]:
            errors.append(f"NSC {slice_id} has no selected DRC/path")
            continue

        selected_drcs.add(item["drc"])
        nodes = item["path_nodes"]
        placement = item["vnf_placement"]
        positions = [
            nodes.index(placement[vnf])
            for vnf in ("vupf", "vcu", "vdu", "vru")
        ]

        if placement["vupf"] != problem.core:
            errors.append(f"NSC {slice_id}: vupf is not at the core")
        if placement["vru"] != problem.ru_location(slice_id):
            errors.append(f"NSC {slice_id}: vru is not at the RU endpoint")
        if positions != sorted(positions) or len(set(positions)) != 4:
            errors.append(f"NSC {slice_id}: VNF placement order is invalid")

        for source, target, _segment in problem.virtual_links:
            start = positions[("vupf", "vcu", "vdu", "vru").index(source)]
            end = positions[("vupf", "vcu", "vdu", "vru").index(target)]
            expected = [list(edge) for edge in zip(nodes[start:end], nodes[start + 1:end + 1])]
            actual = item["virtual_link_mapping"][f"{source}->{target}"]
            if actual != expected:
                errors.append(
                    f"NSC {slice_id}: invalid flow for {source}->{target}; "
                    f"expected {expected}, got {actual}"
                )

    used_by_indicator = {
        drc_id
        for drc_id, variable in model._vars["pi_tilde"].items()
        if (pulp.value(variable) or 0.0) > 0.5
    }
    if used_by_indicator != selected_drcs:
        errors.append(
            f"pi_tilde mismatch: indicators={used_by_indicator}, "
            f"selected={selected_drcs}"
        )

    if errors:
        raise AssertionError("Solution check failed:\n- " + "\n- ".join(errors))

    if verbose:
        print("[OK] Solution is consistent with DRC/path/placement/flow constraints")
        for item in solution:
            print(
                f"NSC {item['slice']}: DRC={item['drc']}, path={item['path']}, "
                f"L={item['latency']:.3f}, placement={item['vnf_placement']}"
            )
        print(f"Used DRCs: {sorted(selected_drcs)}")

    return solution


def run_all(
    beta: float = DEFAULT_BETA,
    solver_name: str = "auto",
    solver_log: bool = False,
) -> List[Dict[str, Any]]:
    """Run data, model, solve, and semantic-solution checks in sequence."""
    problem = load_problem()
    check_data(problem)
    print_drc_parameters(problem)
    model = build_model(problem, beta=beta)
    status = solve_model(model, solver_name=solver_name, solver_log=solver_log)
    if status != "Optimal":
        raise RuntimeError(f"Solver did not return an optimal solution: {status}")
    return check_solution(problem, model)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect or solve the placement ILP")
    parser.add_argument(
        "action",
        nargs="?",
        default="data",
        choices=("data", "drcs", "model", "variables", "constraints", "solve", "all"),
    )
    parser.add_argument("--phy", type=Path, default=DEFAULT_PHY)
    parser.add_argument("--paths", type=Path, default=DEFAULT_PATHS)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--core", type=int, default=0)
    parser.add_argument("--beta", type=float, default=DEFAULT_BETA)
    parser.add_argument("--solver", choices=("auto", "cbc", "gurobi"), default="auto")
    parser.add_argument("--solver-log", action="store_true")
    parser.add_argument("--family", choices=("pi_tilde", "pi", "y", "x_node", "x_link"))
    parser.add_argument("--prefix", help="Constraint prefix, for example C2b or C7")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--nonzero-only", action="store_true")
    parser.add_argument("--export-lp", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    problem = load_problem(
        phy_path=args.phy,
        paths_path=args.paths,
        nodes_path=args.nodes,
        core_id=args.core,
    )

    if args.action == "data":
        check_data(problem)
        return
    if args.action == "drcs":
        check_data(problem, verbose=False)
        print_drc_parameters(problem)
        return
    if args.action == "all":
        check_data(problem)
        print_drc_parameters(problem)

    model = build_model(problem, beta=args.beta, verbose=args.action != "variables")
    if args.export_lp:
        export_lp(model, args.export_lp)

    if args.action == "model":
        return
    if args.action == "variables":
        print_variables(
            model,
            family=args.family,
            limit=args.limit,
            nonzero_only=args.nonzero_only,
        )
        return
    if args.action == "constraints":
        print_constraints(model, prefix=args.prefix, limit=args.limit)
        return

    status = solve_model(model, solver_name=args.solver, solver_log=args.solver_log)
    if status != "Optimal":
        raise RuntimeError(f"Solver did not return an optimal solution: {status}")
    check_solution(problem, model)
    if args.action == "all":
        print_variables(model, family="y", limit=args.limit, nonzero_only=True)


if __name__ == "__main__":
    main()
