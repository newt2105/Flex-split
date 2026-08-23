"""Run the external three-stage PlaceRAN model and compare it with the ILP.

The upstream implementation in ``model_files/model.py`` only prints the three
objective values.  This runner keeps that model unchanged, captures the final
stage, and writes both a semantic JSON file and the nonzero raw variables.

Run from the directory that contains ``FlexRanSplitProblem``::

    python -m FlexRanSplitProblem.run_placeran \
        --ilp-solution FlexRanSplitProblem/results/solution_YYYYMMDD_HHMMSS.json

It may also be run directly from this directory::

    python run_placeran.py

PlaceRAN uses DOcplex and a local IBM CPLEX installation.  Unlike the newer
PuLP ILP runner, CBC cannot solve this original model because it contains
DOcplex-specific min/max expressions.
"""

from __future__ import annotations

import argparse
import builtins
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_ROOT = PACKAGE_DIR.parent / "PlaceRAN"
DEFAULT_RESULTS = PACKAGE_DIR / "results" / "placeran"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PlaceRAN and export its final solution like run_ilp.py"
    )
    parser.add_argument(
        "--model-root",
        type=Path,
        default=DEFAULT_MODEL_ROOT,
        help=(
            "Directory containing model_files/model.py and PlaceRAN input "
            f"files (default: {DEFAULT_MODEL_ROOT})"
        ),
    )
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument(
        "--ilp-solution",
        type=Path,
        help="Optional run_ilp.py JSON result to compare with PlaceRAN",
    )
    parser.add_argument("--solver-log", action="store_true")
    return parser.parse_args()


def find_input(root: Path, relative_path: str | Path) -> Path:
    """Resolve both the upstream and the in-package PlaceRAN layouts."""
    relative_path = Path(relative_path)
    candidates = [root / relative_path]
    if relative_path == Path("paths.json"):
        candidates.append(root / "model_files" / "paths.json")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_placeran_module(model_root: Path) -> ModuleType:
    model_path = model_root / "model_files" / "model.py"
    if not model_path.is_file():
        raise FileNotFoundError(f"PlaceRAN model was not found: {model_path}")

    spec = importlib.util.spec_from_file_location("placeran_original_model", model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load PlaceRAN model from {model_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as error:
        if error.name == "docplex" or (error.name or "").startswith("docplex."):
            raise RuntimeError(
                "PlaceRAN requires DOcplex. Install it with: pip install docplex"
            ) from error
        raise
    except Exception as error:
        raise RuntimeError(
            "DOcplex could not be loaded. Check that the Python, DOcplex, and "
            "IBM CPLEX versions are compatible."
        ) from error

    # The original model opens every input relative to the current directory.
    # Resolve those paths against --model-root so this runner works from any CWD.
    def open_from_model_root(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, Path)) and not Path(file).is_absolute():
            file = find_input(model_root, file)
        return builtins.open(file, *args, **kwargs)

    module.open = open_from_model_root
    return module


def clear_topology(module: ModuleType) -> None:
    """Avoid accumulating duplicate links when the three stages reload data."""
    for name in ("links", "capacity", "delay", "crs", "paths"):
        value = getattr(module, name, None)
        if hasattr(value, "clear"):
            value.clear()


def install_model_recorder(
    module: ModuleType, solver_log: bool
) -> tuple[list[Any], Callable[..., Any]]:
    """Record each locally scoped DOcplex model created by the old functions."""
    original_model = module.Model
    recorded_models: list[Any] = []

    def recording_model(*args: Any, **kwargs: Any) -> Any:
        if solver_log:
            kwargs["log_output"] = True
        model = original_model(*args, **kwargs)
        recorded_models.append(model)
        return model

    module.Model = recording_model
    return recorded_models, original_model


def run_stage(
    stage: Callable[..., float | None], recorded_models: list[Any], *args: float
) -> tuple[float, float]:
    started = time.perf_counter()
    model_count = len(recorded_models)
    try:
        returned_objective = stage(*args)
        if returned_objective is None:
            if len(recorded_models) == model_count:
                raise RuntimeError("PlaceRAN stage did not create a model")
            solution = recorded_models[-1].solution
            if solution is None:
                raise RuntimeError("PlaceRAN stage did not produce a solution")
            returned_objective = solution.get_objective_value()
        objective = float(returned_objective)
    except Exception as error:
        message = str(error).lower()
        stage_name = getattr(stage, "__name__", "PlaceRAN stage")
        model = recorded_models[-1] if len(recorded_models) > model_count else None
        variable_count = getattr(model, "number_of_variables", None)
        constraint_count = getattr(model, "number_of_constraints", None)
        if callable(variable_count):
            variable_count = variable_count()
        if callable(constraint_count):
            constraint_count = constraint_count()
        size = (
            f" Model size: {variable_count} variables, "
            f"{constraint_count} constraints."
            if variable_count is not None and constraint_count is not None
            else ""
        )

        limit_markers = (
            "error 1016",
            "problem size limits exceeded",
            "community edition",
            "promotional version",
        )
        if any(marker in message for marker in limit_markers):
            raise RuntimeError(
                f"{stage_name} exceeds the 1000-variable/1000-constraint "
                f"limit of the CPLEX Community/Promotional edition.{size} "
                "Use a full academic or commercial CPLEX license."
            ) from error

        runtime_markers = (
            "no cplex runtime found",
            "cplex runtime not found",
            "cannot solve model: no cplex",
        )
        if any(marker in message for marker in runtime_markers):
            raise RuntimeError(
                "PlaceRAN needs the IBM CPLEX Python runtime in addition to "
                "DOcplex. Install/configure CPLEX, then run this command again."
            ) from error
        raise RuntimeError(f"{stage_name} failed: {error}{size}") from error
    return objective, time.perf_counter() - started


def path_nodes(path: Any) -> list[int]:
    edges = list(path.p1) + list(path.p2) + list(path.p3)
    if not edges:
        return [int(node) for node in path.seq]

    nodes = [int(edges[0][0])]
    for source, target in edges:
        source = int(source)
        target = int(target)
        if nodes[-1] != source:
            nodes.append(source)
        nodes.append(target)
    return nodes


def edge_list(edges: Iterable[tuple[int, int]]) -> list[list[int]]:
    return [[int(source), int(target)] for source, target in edges]


def extract_solution(module: ModuleType, model: Any) -> list[dict[str, Any]]:
    """Convert selected PlaceRAN x[path, DRC, RU] variables to ILP JSON."""
    selected: list[tuple[int, int, int]] = []
    for key, variable in model.x.items():
        if float(variable.solution_value) > 0.5:
            path_id, drc_id, ru_id = key
            selected.append((int(path_id), int(drc_id), int(ru_id)))

    solution = []
    for path_id, drc_id, ru_id in sorted(selected, key=lambda item: item[2]):
        path = module.paths[path_id]
        nodes = path_nodes(path)
        cu_node, du_node, ru_node = (int(node) for node in path.seq)
        solution.append(
            {
                "slice": ru_id,
                "ru": ru_id,
                "deployed": 1,
                "admitted": 1,
                "drc": drc_id,
                "path": path_id,
                "path_nodes": nodes,
                "latency": float(path.delay_p1 + path.delay_p2 + path.delay_p3),
                "vnf_placement": {
                    "vupf": 0,
                    "vcu": cu_node,
                    "vdu": du_node,
                    "vru": ru_node,
                },
                "virtual_link_mapping": {
                    "vupf->vcu": edge_list(path.p1),
                    "vcu->vdu": edge_list(path.p2),
                    "vdu->vru": edge_list(path.p3),
                },
            }
        )

    expected_rus = set(int(ru_id) for ru_id in module.RU_location_T2())
    selected_rus = {item["ru"] for item in solution}
    duplicates = len(solution) != len(selected_rus)
    if selected_rus != expected_rus or duplicates:
        missing = sorted(expected_rus - selected_rus)
        raise RuntimeError(
            "Invalid PlaceRAN solution: "
            f"missing RUs={missing}, duplicate selections={duplicates}"
        )
    return solution


def save_raw_solution(model: Any, filepath: Path) -> None:
    with filepath.open("w", encoding="utf-8") as stream:
        stream.write(f"# Solution for model {model.name}\n")
        stream.write(
            f"# Objective value = {model.solution.get_objective_value()}\n"
        )
        for variable in model.iter_variables():
            value = float(variable.solution_value)
            if abs(value) > 1e-6:
                stream.write(f"{variable.name} {value}\n")


def load_solution_file(filepath: Path) -> list[dict[str, Any]]:
    if not filepath.is_file():
        raise FileNotFoundError(f"ILP solution was not found: {filepath}")
    with filepath.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    slices = payload.get("slices", payload) if isinstance(payload, dict) else payload
    if not isinstance(slices, list):
        raise ValueError(f"Invalid solution format in {filepath}")
    return slices


def slice_id(item: dict[str, Any]) -> int:
    identifier = item.get("slice", item.get("ru"))
    if identifier is None:
        raise ValueError(f"Solution item has no slice/ru identifier: {item}")
    return int(identifier)


def is_deployed(item: dict[str, Any]) -> bool:
    return bool(item.get("deployed", item.get("admitted", 1)))


def summarize_solution(slices: list[dict[str, Any]]) -> dict[str, Any]:
    deployed = [item for item in slices if is_deployed(item)]
    used_drcs = sorted(
        {int(item["drc"]) for item in deployed if item.get("drc") is not None}
    )
    latencies = [
        float(item["latency"])
        for item in deployed
        if item.get("latency") is not None
    ]
    placements_available = all(
        item.get("vnf_placement") is not None for item in deployed
    )
    placement_nodes = (
        sorted(
            {
                int(node)
                for item in deployed
                for node in item["vnf_placement"].values()
                if node is not None
            }
        )
        if placements_available
        else None
    )
    return {
        "slice_count": len(slices),
        "deployed_count": len(deployed),
        "used_drcs": used_drcs,
        "used_drc_count": len(used_drcs),
        "total_latency": sum(latencies) if len(latencies) == len(deployed) else None,
        "average_latency": (
            sum(latencies) / len(latencies)
            if latencies and len(latencies) == len(deployed)
            else None
        ),
        "placement_nodes": placement_nodes,
        "active_non_core_node_count": (
            len([node for node in placement_nodes if node != 0])
            if placement_nodes is not None
            else None
        ),
    }


def comparable_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "drc": item.get("drc"),
        "path": item.get("path"),
        "path_nodes": item.get("path_nodes"),
        "latency": item.get("latency"),
        "vnf_placement": item.get("vnf_placement"),
    }


def compare_solutions(
    placeran_slices: list[dict[str, Any]], ilp_slices: list[dict[str, Any]]
) -> dict[str, Any]:
    placeran_by_slice = {slice_id(item): item for item in placeran_slices}
    ilp_by_slice = {slice_id(item): item for item in ilp_slices}
    placeran_summary = summarize_solution(placeran_slices)
    ilp_summary = summarize_solution(ilp_slices)

    per_slice = []
    for identifier in sorted(set(placeran_by_slice) | set(ilp_by_slice)):
        placeran_item = placeran_by_slice.get(identifier)
        ilp_item = ilp_by_slice.get(identifier)
        per_slice.append(
            {
                "slice": identifier,
                "placeran": comparable_item(placeran_item),
                "ilp": comparable_item(ilp_item),
                "same_drc": (
                    placeran_item is not None
                    and ilp_item is not None
                    and placeran_item.get("drc") == ilp_item.get("drc")
                ),
                "same_path_nodes": (
                    None
                    if placeran_item is None
                    or ilp_item is None
                    or placeran_item.get("path_nodes") is None
                    or ilp_item.get("path_nodes") is None
                    else placeran_item.get("path_nodes")
                    == ilp_item.get("path_nodes")
                ),
                "same_vnf_placement": (
                    None
                    if placeran_item is None
                    or ilp_item is None
                    or placeran_item.get("vnf_placement") is None
                    or ilp_item.get("vnf_placement") is None
                    else placeran_item.get("vnf_placement")
                    == ilp_item.get("vnf_placement")
                ),
            }
        )

    deltas = {}
    for metric in (
        "deployed_count",
        "used_drc_count",
        "total_latency",
        "average_latency",
        "active_non_core_node_count",
    ):
        placeran_value = placeran_summary[metric]
        ilp_value = ilp_summary[metric]
        deltas[metric] = (
            placeran_value - ilp_value
            if placeran_value is not None and ilp_value is not None
            else None
        )

    return {
        "note": (
            "PlaceRAN and ILP path IDs come from different path catalogs; "
            "compare path_nodes and placements instead of the numeric path ID."
        ),
        "summary": {"placeran": placeran_summary, "ilp": ilp_summary},
        "delta_placeran_minus_ilp": deltas,
        "per_slice": per_slice,
    }


def display_comparison(comparison: dict[str, Any]) -> None:
    summaries = comparison["summary"]
    deltas = comparison["delta_placeran_minus_ilp"]
    print("\nPlaceRAN vs ILP")
    print(f"{'Metric':<28} {'PlaceRAN':>12} {'ILP':>12} {'Delta':>12}")
    for metric in (
        "deployed_count",
        "used_drc_count",
        "total_latency",
        "average_latency",
        "active_non_core_node_count",
    ):
        placeran_value = summaries["placeran"][metric]
        ilp_value = summaries["ilp"][metric]
        delta = deltas[metric]
        print(
            f"{metric:<28} {str(placeran_value):>12} "
            f"{str(ilp_value):>12} {str(delta):>12}"
        )


def main() -> None:
    args = parse_args()
    model_root = args.model_root.resolve()
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=True)

    placeran = load_placeran_module(model_root)
    recorded_models, original_model = install_model_recorder(
        placeran, solver_log=args.solver_log
    )
    placeran.f1_vars.clear()
    placeran.f2_vars.clear()

    total_started = time.perf_counter()
    try:
        clear_topology(placeran)
        stage_1, time_1 = run_stage(placeran.run_stage_1, recorded_models)
        clear_topology(placeran)
        stage_2, time_2 = run_stage(
            placeran.run_stage_2, recorded_models, stage_1
        )
        clear_topology(placeran)
        stage_3, time_3 = run_stage(
            placeran.run_stage_3, recorded_models, stage_1, stage_2
        )
    finally:
        placeran.Model = original_model
    total_time = time.perf_counter() - total_started

    if len(recorded_models) != 3 or recorded_models[-1].solution is None:
        raise RuntimeError("PlaceRAN did not produce a final Stage 3 solution")

    final_model = recorded_models[-1]
    slices = extract_solution(placeran, final_model)
    payload = {
        "model": "PlaceRAN",
        "model_root": str(model_root),
        "status": "Optimal",
        "objective": stage_3,
        "stage_objectives": {
            "stage_1": stage_1,
            "stage_2": stage_2,
            "stage_3": stage_3,
        },
        "stage_times_seconds": {
            "stage_1": time_1,
            "stage_2": time_2,
            "stage_3": time_3,
            "total": total_time,
        },
        "slices": slices,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    semantic_path = results / f"solution_{timestamp}.json"
    raw_path = results / f"solution_{timestamp}.sol"
    with semantic_path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
    save_raw_solution(final_model, raw_path)

    comparison_path = None
    if args.ilp_solution is not None:
        ilp_path = args.ilp_solution.resolve()
        comparison = compare_solutions(slices, load_solution_file(ilp_path))
        comparison["placeran_solution"] = str(semantic_path)
        comparison["ilp_solution"] = str(ilp_path)
        comparison_path = results / f"comparison_{timestamp}.json"
        with comparison_path.open("w", encoding="utf-8") as stream:
            json.dump(comparison, stream, indent=2)

    print("\nPlaceRAN final result")
    print(f"Solver status: Optimal")
    print(
        "Stage objectives: "
        f"S1={stage_1:.6f}, S2={stage_2:.6f}, S3={stage_3:.6f}"
    )
    print(f"Total time: {total_time:.3f} s")
    print(f"Semantic solution: {semantic_path}")
    print(f"Raw variables: {raw_path}")
    for item in slices:
        print(
            f"NSC {item['slice']}: DRC={item['drc']}, path={item['path']}, "
            f"L={item['latency']:.3f}, placement={item['vnf_placement']}"
        )
    if comparison_path is not None:
        display_comparison(comparison)
        print(f"Comparison report: {comparison_path}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ImportError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
