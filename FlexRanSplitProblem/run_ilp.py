"""Command-line runner for the flexible RAN placement ILP."""

from __future__ import annotations

import argparse
import configparser
import csv
import json
import pickle
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable

import pulp

from .common import FlexRanSplitProblem
from .lp_formulation import DEFAULT_BETA, extract_solution, formulateLp
from .phy.ran_model import DRC_structure_T2, build_rus_from_nodes_json_T2


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
DEFAULT_NODES = PACKAGE_DIR / "model_files" / "T2_files" / "F1_8_CRs_nodes_LC.json"
DEFAULT_PATHS = PACKAGE_DIR / "phy" / "paths.pkl"
DEFAULT_PHY = PACKAGE_DIR / "phy" / "phy.pkl"
DEFAULT_RESULTS = PACKAGE_DIR / "results"
DEFAULT_SETTINGS = PACKAGE_DIR / "settings" / "ilp.txt"

CSV_FIELDS = (
    "run_id",
    "network",
    "profile",
    "status",
    "objective",
    "solve_time_seconds",
    "beta",
    "solver",
    "slice",
    "ru",
    "deployed",
    "admitted",
    "drc",
    "path",
    "latency",
    "path_nodes",
    "vupf_node",
    "vcu_node",
    "vdu_node",
    "vru_node",
    "vupf_to_vcu_links",
    "vcu_to_vdu_links",
    "vdu_to_vru_links",
)


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


def _resolve_repo_path(value: str | Path) -> Path:
    """Resolve a settings path relative to the repository root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_DIR / path


def _read_bool(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    fallback: bool,
) -> bool:
    try:
        return parser.getboolean(section, option, fallback=fallback)
    except ValueError as exc:
        raise ValueError(
            f"Invalid boolean [{section}] {option} in settings file"
        ) from exc


def load_settings(settings_path: str | Path) -> Dict[str, Any]:
    """Load and validate the human-editable ``settings/ilp.txt``."""
    settings_path = Path(settings_path).expanduser()
    if not settings_path.is_absolute():
        settings_path = Path.cwd() / settings_path
    if not settings_path.is_file():
        raise FileNotFoundError(
            f"Settings file not found: {settings_path.resolve()}"
        )

    parser = configparser.ConfigParser()
    with settings_path.open("r", encoding="utf-8") as stream:
        parser.read_file(stream)

    required = {"input": (), "output": ("csv",)}
    for section, options in required.items():
        if not parser.has_section(section):
            raise ValueError(f"Missing [{section}] section in {settings_path}")
        for option in options:
            if not parser.has_option(section, option):
                raise ValueError(
                    f"Missing [{section}] {option} in {settings_path}"
                )

    solver = parser.get("solver", "name", fallback="auto").strip().lower()
    if solver not in {"auto", "cbc", "gurobi"}:
        raise ValueError("[solver] name must be auto, cbc, or gurobi")

    beta = parser.getfloat("model", "beta", fallback=DEFAULT_BETA)
    if not 0.0 <= beta <= 1.0:
        raise ValueError("[model] beta must be between 0 and 1")

    network = parser.getint("input", "network", fallback=16)
    if network < 1:
        raise ValueError("[input] network must be a positive integer")
    profile = parser.get("input", "profile", fallback="LC").strip().upper()
    path_variables = {"network": network, "profile": profile}

    def input_path(option: str, fallback: str) -> Path:
        value = parser.get("input", option, fallback=fallback)
        return _resolve_repo_path(value.format(**path_variables))

    results_value = parser.get(
        "output",
        "directory",
        fallback="results/network_{network}",
    ).format(**path_variables)
    csv_value = parser.get("output", "csv").format(**path_variables)
    return {
        "settings": settings_path,
        "network": network,
        "profile": profile,
        "phy": input_path("phy", "data/network_{network}/phy.pkl"),
        "paths": input_path("paths", "data/network_{network}/paths.pkl"),
        "nodes": input_path(
            "nodes",
            "FlexRanSplitProblem/model_files/T2_files/"
            "F1_{network}_CRs_nodes_{profile}.json",
        ),
        "results": _resolve_repo_path(results_value),
        "csv": _resolve_repo_path(csv_value),
        "csv_append": _read_bool(parser, "output", "append", False),
        "save_json": _read_bool(parser, "output", "save_json", False),
        "save_sol": _read_bool(parser, "output", "save_sol", False),
        "save_snapshot": _read_bool(
            parser, "output", "save_snapshot", False
        ),
        "core": parser.getint("model", "core", fallback=0),
        "beta": beta,
        "solver": solver,
        "solver_log": _read_bool(parser, "solver", "log", False),
    }


def save_solution_csv(
    filepath: str | Path,
    solution: Iterable[Dict[str, Any]],
    *,
    run_id: str,
    network: int,
    profile: str,
    status: str,
    objective: float,
    solve_time: float,
    beta: float,
    solver: str,
    append: bool = False,
) -> Path:
    """Write one flat CSV row per NSC and return the output path."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    write_header = not append or not filepath.exists() or filepath.stat().st_size == 0
    mode = "a" if append else "w"

    with filepath.open(mode, newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for item in solution:
            placement = item.get("vnf_placement", {})
            links = item.get("virtual_link_mapping", {})
            writer.writerow(
                {
                    "run_id": run_id,
                    "network": network,
                    "profile": profile,
                    "status": status,
                    "objective": objective,
                    "solve_time_seconds": solve_time,
                    "beta": beta,
                    "solver": solver,
                    "slice": item.get("slice"),
                    "ru": item.get("ru"),
                    "deployed": item.get("deployed"),
                    "admitted": item.get("admitted"),
                    "drc": item.get("drc"),
                    "path": item.get("path"),
                    "latency": item.get("latency"),
                    "path_nodes": json.dumps(item.get("path_nodes", [])),
                    "vupf_node": placement.get("vupf"),
                    "vcu_node": placement.get("vcu"),
                    "vdu_node": placement.get("vdu"),
                    "vru_node": placement.get("vru"),
                    "vupf_to_vcu_links": json.dumps(
                        links.get("vupf->vcu", [])
                    ),
                    "vcu_to_vdu_links": json.dumps(
                        links.get("vcu->vdu", [])
                    ),
                    "vdu_to_vru_links": json.dumps(
                        links.get("vdu->vru", [])
                    ),
                }
            )
    return filepath


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solve the flexible RAN placement ILP")
    parser.add_argument(
        "--settings",
        type=Path,
        default=DEFAULT_SETTINGS,
        help=f"configuration file (default: {DEFAULT_SETTINGS})",
    )
    parser.add_argument("--nodes", type=Path, help="override [input] nodes")
    parser.add_argument("--paths", type=Path, help="override [input] paths")
    parser.add_argument("--phy", type=Path, help="override [input] phy")
    parser.add_argument("--results", type=Path, help="override [output] directory")
    parser.add_argument("--csv", type=Path, help="override [output] csv")
    parser.add_argument("--core", type=int, help="override [model] core")
    parser.add_argument("--beta", type=float, help="override [model] beta")
    parser.add_argument("--solver", choices=("auto", "cbc", "gurobi"))
    parser.add_argument(
        "--solver-log",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="override [solver] log",
    )
    args = parser.parse_args()
    settings = load_settings(args.settings)

    for key in ("nodes", "paths", "phy", "results", "csv"):
        command_line_value = getattr(args, key)
        if command_line_value is not None:
            settings[key] = _resolve_repo_path(command_line_value)
    for key in ("core", "beta", "solver", "solver_log"):
        command_line_value = getattr(args, key)
        if command_line_value is not None:
            settings[key] = command_line_value

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

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    objective = float(pulp.value(model.objective))
    csv_path = save_solution_csv(
        args.csv,
        solution,
        run_id=timestamp,
        network=args.network,
        profile=args.profile,
        status=status,
        objective=objective,
        solve_time=problem.solver_time,
        beta=args.beta,
        solver=args.solver,
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
    if args.save_json:
        print(f"Semantic solution: {semantic_path.resolve()}")
    if args.save_sol:
        print(f"Raw variables: {raw_path.resolve()}")
    if args.save_snapshot:
        print(f"Problem snapshot: {snapshot_path.resolve()}")
    for item in solution:
        print(
            f"NSC {item['slice']}: DRC={item['drc']}, path={item['path']}, "
            f"placement={item['vnf_placement']}"
        )


if __name__ == "__main__":
    main()
