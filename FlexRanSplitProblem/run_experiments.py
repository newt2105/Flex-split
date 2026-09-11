"""Run the standard Flex-split scenarios from one INI settings file."""

from __future__ import annotations

import argparse
import configparser
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
if __package__ in {None, ""}:
    sys.path.insert(0, str(PACKAGE_DIR.parent))

import pulp

from FlexRanSplitProblem.common import FlexRanSplitProblem
from FlexRanSplitProblem.lp_formulation import extract_solution, formulateLp
from FlexRanSplitProblem.phy.genphy import load_phy_T1, load_phy_T2
from FlexRanSplitProblem.phy.path_gen import generate_paths
from FlexRanSplitProblem.phy.ran_model import (
    DRC_structure_T1,
    DRC_structure_T2,
    build_rus_from_nodes_json_T1,
    build_rus_from_nodes_json_T2,
)
from FlexRanSplitProblem.run_ilp import build_solver, save_sol, save_solution_csv


DEFAULT_SETTINGS = PACKAGE_DIR / "settings" / "experiments.ini"
VALID_CASES = {
    f"{topology}-{ru}-{resource}"
    for topology in ("T1", "T2")
    for ru in ("R1", "F1")
    for resource in ("LC", "RC", "HC")
}
NETWORK_SIZES = {"T1": 51, "T2": 128}


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PACKAGE_DIR / path).resolve()


def load_settings(path: Path) -> dict[str, object]:
    path = path.expanduser().resolve()
    parser = configparser.ConfigParser(allow_no_value=True)
    with path.open(encoding="utf-8") as stream:
        parser.read_file(stream)
    section = parser["experiments"]
    cases = [value.strip().upper() for value in section.get("cases", "").splitlines() if value.strip()]
    invalid = [case for case in cases if case not in VALID_CASES]
    if not cases:
        raise ValueError("[experiments] cases must contain at least one case")
    if invalid:
        raise ValueError("Invalid case(s): " + ", ".join(invalid))
    k_paths = section.getint("k_paths", 10)
    if k_paths < 1:
        raise ValueError("k_paths must be positive")
    beta = section.getfloat("beta", 0.5)
    if not 0.0 <= beta <= 1.0:
        raise ValueError("beta must be between 0 and 1")
    solver = section.get("solver", "auto").strip().lower()
    if solver not in {"auto", "cbc", "gurobi"}:
        raise ValueError("solver must be auto, cbc, or gurobi")
    raw_time_limit = section.get("time_limit", "").strip()
    time_limit = float(raw_time_limit) if raw_time_limit else None
    if time_limit is not None and time_limit <= 0:
        raise ValueError("time_limit must be positive or empty")
    return {
        "settings": path,
        "cases": cases,
        "k_paths": k_paths,
        "beta": beta,
        "solver": solver,
        "show_log": section.getboolean("show_log", False),
        "time_limit": time_limit,
        "stop_on_error": section.getboolean("stop_on_error", True),
        "results_root": resolve_path(section.get("results_root", "results_experiments")),
        "save_json": section.getboolean("save_json", True),
        "save_sol": section.getboolean("save_sol", False),
    }


def case_files(case: str) -> tuple[str, str, str, int, Path, Path]:
    topology, ru_distribution, resource_level = case.split("-")
    network_size = NETWORK_SIZES[topology]
    directory = PACKAGE_DIR / "model_files" / f"{topology}_files"
    links = directory / f"{network_size}_CRs_links_{resource_level}.json"
    nodes = directory / f"{ru_distribution}_{network_size}_CRs_nodes_{resource_level}.json"
    for path in (links, nodes):
        if not path.is_file():
            raise FileNotFoundError(f"Missing input for {case}: {path}")
    return topology, ru_distribution, resource_level, network_size, links, nodes


def solve_case(case: str, settings: dict[str, object]) -> dict[str, object]:
    topology, ru_distribution, resource_level, network_size, links, nodes = case_files(case)
    load_phy = load_phy_T1 if topology == "T1" else load_phy_T2
    load_rus = build_rus_from_nodes_json_T1 if topology == "T1" else build_rus_from_nodes_json_T2
    drcs = DRC_structure_T1() if topology == "T1" else DRC_structure_T2()

    physical_network = load_phy(str(links), str(nodes))
    paths = generate_paths(
        str(links),
        str(nodes),
        core_id=0,
        k_paths=int(settings["k_paths"]),
        topology=topology,
    )
    rus = load_rus(str(nodes))
    problem = FlexRanSplitProblem(
        physical_network=physical_network,
        paths=paths,
        rus=rus,
        drcs=drcs,
        core_id=0,
        name=f"Flexible_RAN_Placement_{case}",
    )
    model = formulateLp(problem, beta=float(settings["beta"]))
    solver = build_solver(
        str(settings["solver"]),
        bool(settings["show_log"]),
        settings["time_limit"],
    )
    started = time.perf_counter()
    model.solve(solver)
    runtime = time.perf_counter() - started
    status = pulp.LpStatus[model.status]
    if status != "Optimal":
        raise RuntimeError(f"{case} did not reach an optimal solution: {status}")

    solution = extract_solution(problem, model)
    result_dir = Path(settings["results_root"]) / case / f"k_paths_{settings['k_paths']}"
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = save_solution_csv(result_dir / "solution.csv", solution, runtime=runtime)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    payload = {
        "method": "Flex-split",
        "scenario": case,
        "topology": topology,
        "ru_distribution": ru_distribution,
        "resource_level": resource_level,
        "network_size": network_size,
        "k_paths": settings["k_paths"],
        "beta": settings["beta"],
        "solver": settings["solver"],
        "status": status,
        "objective": float(pulp.value(model.objective)),
        "runtime": runtime,
        "assignments": solution,
    }
    if settings["save_json"]:
        with (result_dir / f"solution_{timestamp}.json").open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
    if settings["save_sol"]:
        save_sol(model, result_dir / f"solution_{timestamp}.sol")

    if settings["show_log"]:
        print(f"Solver status: {status}")
        print(f"Objective    : {payload['objective']:.6f}")
        print(f"Solve time   : {runtime:.3f}s")
        print(f"CSV result   : {csv_path}")
        for item in solution:
            print(
                f"NSC {item['slice']}: DRC={item['drc']}, path={item['path']}, "
                f"L={item['latency']}, placement={item['vnf_placement']}"
            )
    return {
        "case": case,
        "status": status,
        "objective": payload["objective"],
        "runtime": runtime,
        "rus": len(rus),
        "paths": len(paths),
        "results_dir": str(result_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    return parser.parse_args()


def main() -> None:
    settings = load_settings(parse_args().settings)
    Path(settings["results_root"]).mkdir(parents=True, exist_ok=True)
    print(f"Settings: {settings['settings']}")
    print(f"Cases   : {', '.join(settings['cases'])}")
    print(f"Solver  : {settings['solver']}")
    print(f"Results : {settings['results_root']}")

    summary = []
    for index, case in enumerate(settings["cases"], start=1):
        print(f"\nCASE {index}/{len(settings['cases'])}: {case}", flush=True)
        try:
            result = solve_case(case, settings)
            summary.append(result)
            print(
                f"{case}: Optimal, objective={result['objective']:.6f}, "
                f"runtime={result['runtime']:.3f}s"
            )
        except Exception as exc:
            summary.append(
                {
                    "case": case,
                    "status": "FAILED",
                    "objective": "",
                    "runtime": "",
                    "rus": "",
                    "paths": "",
                    "results_dir": "",
                    "error": str(exc),
                }
            )
            print(f"{case}: FAILED - {exc}", file=sys.stderr)
            if settings["stop_on_error"]:
                break

    summary_path = Path(settings["results_root"]) / "run_summary.csv"
    fields = ("case", "status", "objective", "runtime", "rus", "paths", "results_dir", "error")
    with summary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary)
    print(f"\nSummary: {summary_path}")
    if any(item["status"] == "FAILED" for item in summary):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
