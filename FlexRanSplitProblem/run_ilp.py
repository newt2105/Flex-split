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

from .common import FlexRanSplitProblem, SliceProfile
from .lp_formulation import DEFAULT_BETA, extract_solution, formulateLp
from .phy.ran_model import DRC_structure_T2, build_rus_from_nodes_json_T2


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
DEFAULT_NODES = PACKAGE_DIR / "model_files" / "T2_files" / "F1_8_CRs_nodes_LC.json"
DEFAULT_PATHS = PACKAGE_DIR / "phy" / "paths.pkl"
DEFAULT_PHY = PACKAGE_DIR / "phy" / "phy.pkl"
DEFAULT_RESULTS = PACKAGE_DIR / "results"
DEFAULT_SETTINGS = PACKAGE_DIR / "settings" / "ilp.txt"

CSV_FIELDS = ("NSC", "service", "DRC", "path", "L", "placement", "runtime")


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


def load_slice_profiles(filepath: str | Path) -> Dict[int, SliceProfile]:
    """Load service definitions and per-NSC assignments from JSON."""
    filepath = Path(filepath)
    with filepath.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)

    if not isinstance(payload, dict):
        raise ValueError("Slice profile JSON must contain an object")
    services = payload.get("services")
    assignments = payload.get("slices")
    if not isinstance(services, dict) or not services:
        raise ValueError("Slice profile JSON must define a non-empty 'services' object")
    if not isinstance(assignments, dict) or not assignments:
        raise ValueError("Slice profile JSON must define a non-empty 'slices' object")

    service_profiles: Dict[str, SliceProfile] = {}
    for service, values in services.items():
        if not isinstance(service, str) or not isinstance(values, dict):
            raise ValueError("Each service profile must be a named JSON object")
        raw_max_latency = values.get("max_latency")
        service_profiles[service] = SliceProfile(
            service=service,
            cpu_scale=float(values.get("cpu_scale", 1.0)),
            bw_scale=float(values.get("bw_scale", 1.0)),
            max_latency=(
                None if raw_max_latency is None else float(raw_max_latency)
            ),
        )

    result: Dict[int, SliceProfile] = {}
    for raw_slice_id, service in assignments.items():
        try:
            slice_id = int(raw_slice_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid NSC ID in slice profiles: {raw_slice_id!r}") from exc
        if slice_id in result:
            raise ValueError(f"Duplicate NSC ID in slice profiles: {slice_id}")
        if not isinstance(service, str):
            raise ValueError(f"NSC {slice_id} must reference a service name")
        if service not in service_profiles:
            raise ValueError(
                f"NSC {slice_id} references undefined service {service!r}"
            )
        result[slice_id] = service_profiles[service]
    return result


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

    slice_profiles_value = parser.get(
        "input", "slice_profiles", fallback=""
    ).strip()
    slice_profiles_path = (
        _resolve_repo_path(slice_profiles_value.format(**path_variables))
        if slice_profiles_value
        else None
    )

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
        "slice_profiles": slice_profiles_path,
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
    runtime: float,
    append: bool = False,
) -> Path:
    """Write compact placement results and solver runtime to CSV."""
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
            latency = item.get("latency")
            writer.writerow(
                {
                    "NSC": item.get("slice"),
                    "service": item.get("service", "default"),
                    "DRC": item.get("drc"),
                    "path": item.get("path"),
                    "L": "" if latency is None else f"{latency:.3f}",
                    "placement": str(placement),
                    "runtime": f"{runtime:.3f}",
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
    parser.add_argument(
        "--slice-profiles",
        type=Path,
        help="override the optional [input] slice_profiles JSON",
    )
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

    for key in ("nodes", "paths", "phy", "slice_profiles", "results", "csv"):
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
    print(
        "Slices  :",
        args.slice_profiles.resolve() if args.slice_profiles else "default profile",
    )

    with args.phy.open("rb") as stream:
        physical_network = pickle.load(stream)
    with args.paths.open("rb") as stream:
        paths = pickle.load(stream)
    slice_profiles = (
        load_slice_profiles(args.slice_profiles) if args.slice_profiles else None
    )

    problem = FlexRanSplitProblem(
        physical_network=physical_network,
        paths=paths,
        rus=build_rus_from_nodes_json_T2(str(args.nodes)),
        drcs=DRC_structure_T2(),
        core_id=args.core,
        name="Flexible_RAN_Placement",
        slice_profiles=slice_profiles,
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
    if args.save_json:
        print(f"Semantic solution: {semantic_path.resolve()}")
    if args.save_sol:
        print(f"Raw variables: {raw_path.resolve()}")
    if args.save_snapshot:
        print(f"Problem snapshot: {snapshot_path.resolve()}")
    for item in solution:
        latency = item.get("latency")
        latency_text = "None" if latency is None else f"{latency:.3f}"
        print(
            f"NSC {item['slice']} ({item['service']}): "
            f"DRC={item['drc']}, path={item['path']}, "
            f"L={latency_text}, placement={item['vnf_placement']}"
        )


if __name__ == "__main__":
    main()
