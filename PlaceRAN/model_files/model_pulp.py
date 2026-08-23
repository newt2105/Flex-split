"""PuLP/CBC implementation of the original three-stage PlaceRAN model.

This module intentionally reuses the topology, path, RU and DRC definitions
from ``model.py``.  Only the modeling backend changes: DOcplex/CPLEX is
replaced by PuLP/CBC while the three lexicographic objectives are preserved.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import pulp

import model as placeran
from placeran_settings import add_settings_arguments, resolve_settings


Assignment = Tuple[int, int, int]  # path id, DRC id, RU id
FUNCTIONS = ("f8", "f7", "f6", "f5", "f4", "f3", "f2")
DRC_PRIORITY = {1: 4, 2: 1, 4: 6, 5: 5, 6: 10, 7: 9, 8: 25, 9: 7, 10: 8}
PLACE_RAN_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = PLACE_RAN_DIR / "results_pulp"
EPSILON = 1e-9
CSV_FIELDS = ("NSC", "DRC", "path", "L", "placement", "runtime")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Solve the original three-stage PlaceRAN model with PuLP/CBC"
    )
    add_settings_arguments(parser)
    parser.add_argument("--solver-log", action="store_true", help="Show the CBC solver log")
    parser.add_argument("--time-limit", type=float, default=None, help="Per-stage time limit in seconds")
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None, help="CSV output path")
    parser.add_argument("--append", action="store_true", help="Append rows to an existing CSV")
    parser.add_argument("--no-save", action="store_true", help="Do not save CSV/JSON results")
    parsed = parser.parse_args()
    settings = resolve_settings(parsed)
    for key, value in settings.items():
        setattr(parsed, key, value)
    if parsed.results is None:
        parsed.results = DEFAULT_RESULTS_DIR / parsed.network / f"k_paths_{parsed.k_paths}"
    if parsed.csv is None:
        parsed.csv = parsed.results / "solution.csv"
    return parsed


def load_scenario(network: str):
    """Load one of the bundled T2/F1/LC network instances."""
    network_size = int(network.rsplit("-", 1)[1])
    placeran.links.clear()
    placeran.capacity.clear()
    placeran.delay.clear()
    placeran.crs.clear()
    placeran.paths.clear()
    placeran.read_topology_T2(network_size)
    return placeran.DRC_structure_T2(), placeran.RU_location_T2(network_size)


def path_matches_drc(path, drc) -> bool:
    """Apply the original DRC/path and delay rules before variable creation."""
    has_cu = drc.Fs_CU != [0]
    has_du = drc.Fs_DU != [0]
    if has_cu != (path.seq[0] != 0):
        return False
    if has_du != (path.seq[1] != 0):
        return False
    return (
        path.delay_p1 <= drc.delay_BH + EPSILON
        and path.delay_p2 <= drc.delay_MH + EPSILON
        and path.delay_p3 <= drc.delay_FH + EPSILON
    )


def candidate_assignments(drcs, rus) -> List[Assignment]:
    """Return only variables that can satisfy the original zero/one rules."""
    candidates = []
    rus_by_cr = {}
    for ru_id, ru in rus.items():
        rus_by_cr.setdefault(ru.CR, []).append(ru_id)
    for path_id, path in placeran.paths.items():
        for drc_id, drc in drcs.items():
            if not path_matches_drc(path, drc):
                continue
            if path.seq[2] != path.target:
                continue
            for ru_id in rus_by_cr.get(path.target, ()):
                candidates.append((path_id, drc_id, ru_id))
    return candidates


def assignment_uses_function_at_cr(index: Assignment, cr_id: int, function: str, drcs) -> bool:
    path_id, drc_id, _ru_id = index
    path = placeran.paths[path_id]
    drc = drcs[drc_id]
    return (
        (function in drc.Fs_CU and path.seq[0] == cr_id)
        or (function in drc.Fs_DU and path.seq[1] == cr_id)
        or (function in drc.Fs_RU and path.seq[2] == cr_id)
    )


def add_indicator_constraints(
    problem: pulp.LpProblem,
    indicator: pulp.LpVariable,
    selected_count,
    maximum: int,
    name: str,
) -> None:
    """Make ``indicator`` exactly equal to 1 iff selected_count is positive."""
    problem += selected_count <= maximum * indicator, f"{name}_upper"
    problem += indicator <= selected_count, f"{name}_lower"


def build_model(
    stage: int,
    drcs,
    rus,
    candidates: Sequence[Assignment],
    stage_1_value: int | None = None,
    stage_2_value: int | None = None,
):
    started = time.perf_counter()
    problem = pulp.LpProblem(f"PlaceRAN_Stage_{stage}", pulp.LpMinimize)
    x = {
        index: pulp.LpVariable(
            "x_path_{}_drc_{}_ru_{}".format(*index), cat=pulp.LpBinary
        )
        for index in candidates
    }
    maximum = len(rus)

    used_cr = {
        cr_id: pulp.LpVariable(f"used_cr_{cr_id}", cat=pulp.LpBinary)
        for cr_id in placeran.crs
        if cr_id != 0
    }
    used_function = {
        (cr_id, function): pulp.LpVariable(
            f"used_function_{cr_id}_{function}", cat=pulp.LpBinary
        )
        for cr_id in placeran.crs
        for function in FUNCTIONS
    }
    used_drc = {
        drc_id: pulp.LpVariable(f"used_drc_{drc_id}", cat=pulp.LpBinary)
        for drc_id in drcs
    }

    # Every RU selects exactly one compatible path/DRC assignment.
    for ru_id in rus:
        ru_candidates = [x[index] for index in candidates if index[2] == ru_id]
        if not ru_candidates:
            raise ValueError(f"RU {ru_id} has no feasible path/DRC assignment")
        problem += pulp.lpSum(ru_candidates) == 1, f"unicity_ru_{ru_id}"

    # Link-bandwidth constraints.  read_topology_T2 stores one orientation;
    # paths can contain either orientation, matching the original formulation.
    for link_id, link in enumerate(dict.fromkeys(placeran.links)):
        reverse_link = (link[1], link[0])
        terms = []
        for index in candidates:
            path = placeran.paths[index[0]]
            drc = drcs[index[1]]
            coefficient = 0.0
            if link in path.p1 or reverse_link in path.p1:
                coefficient += drc.bw_BH
            if link in path.p2 or reverse_link in path.p2:
                coefficient += drc.bw_MH
            if link in path.p3 or reverse_link in path.p3:
                coefficient += drc.bw_FH
            if coefficient:
                terms.append(coefficient * x[index])
        problem += (
            pulp.lpSum(terms) <= placeran.capacity[link],
            f"links_bw_{link_id}_{link[0]}_{link[1]}",
        )

    # CR CPU-capacity constraints.
    for cr_id, cr in placeran.crs.items():
        terms = []
        for index in candidates:
            path = placeran.paths[index[0]]
            drc = drcs[index[1]]
            coefficient = 0.0
            if path.seq[0] == cr_id:
                coefficient += drc.cpu_CU
            if path.seq[1] == cr_id:
                coefficient += drc.cpu_DU
            if path.seq[2] == cr_id:
                coefficient += drc.cpu_RU
            if coefficient:
                terms.append(coefficient * x[index])
        problem += pulp.lpSum(terms) <= cr.cpu, f"crs_cpu_usage_{cr_id}"

    # Exact linearization of min(1, sum(x)) for used CRs.
    for cr_id, indicator in used_cr.items():
        selected_count = pulp.lpSum(
            x[index]
            for index in candidates
            if cr_id in placeran.paths[index[0]].seq
        )
        add_indicator_constraints(
            problem, indicator, selected_count, maximum, f"used_cr_indicator_{cr_id}"
        )

    # Exact linearization used to express max(0, sum(x)-1) as
    # sum(x) - min(1, sum(x)) in the Stage-1 objective.
    function_counts = {}
    for (cr_id, function), indicator in used_function.items():
        selected_count = pulp.lpSum(
            x[index]
            for index in candidates
            if assignment_uses_function_at_cr(index, cr_id, function, drcs)
        )
        function_counts[(cr_id, function)] = selected_count
        add_indicator_constraints(
            problem,
            indicator,
            selected_count,
            maximum,
            f"used_function_indicator_{cr_id}_{function}",
        )

    for drc_id, indicator in used_drc.items():
        selected_count = pulp.lpSum(
            x[index] for index in candidates if index[1] == drc_id
        )
        add_indicator_constraints(
            problem, indicator, selected_count, maximum, f"used_drc_indicator_{drc_id}"
        )

    stage_1_expression = (
        pulp.lpSum(used_cr.values())
        - pulp.lpSum(
            function_counts[key] - used_function[key]
            for key in used_function
        )
    )
    stage_2_expression = pulp.lpSum(used_drc.values())
    stage_3_expression = pulp.lpSum(
        DRC_PRIORITY[index[1]] * x[index] for index in candidates
    )

    if stage_1_value is not None:
        problem += stage_1_expression == stage_1_value, "fix_stage_1_objective"
    if stage_2_value is not None:
        problem += stage_2_expression == stage_2_value, "fix_stage_2_objective"

    objectives = {
        1: stage_1_expression,
        2: stage_2_expression,
        3: stage_3_expression,
    }
    problem += objectives[stage], f"stage_{stage}_objective"
    allocation_time = time.perf_counter() - started
    return problem, x, allocation_time


def solve_stage(
    stage: int,
    drcs,
    rus,
    candidates: Sequence[Assignment],
    solver_log: bool,
    time_limit: float | None,
    stage_1_value: int | None = None,
    stage_2_value: int | None = None,
    warm_start: Iterable[Assignment] = (),
):
    print(f"Running Stage - {stage} (PuLP/CBC)")
    print("-" * 107)
    problem, x, allocation_time = build_model(
        stage, drcs, rus, candidates, stage_1_value, stage_2_value
    )
    warm_start_set = set(warm_start)
    for index, variable in x.items():
        variable.setInitialValue(1 if index in warm_start_set else 0)

    solver = pulp.PULP_CBC_CMD(
        msg=solver_log,
        gapRel=0,
        timeLimit=time_limit,
        warmStart=bool(warm_start_set),
    )
    solve_started = time.perf_counter()
    problem.solve(solver)
    solve_time = time.perf_counter() - solve_started
    status = pulp.LpStatus[problem.status]
    if status != "Optimal":
        raise RuntimeError(f"Stage {stage} did not reach an optimal solution: {status}")

    objective = float(pulp.value(problem.objective))
    integer_objective = int(round(objective))
    if abs(objective - integer_objective) > 1e-6:
        raise RuntimeError(f"Stage {stage} returned a non-integer objective: {objective}")
    selected = [index for index in candidates if pulp.value(x[index]) > 0.5]

    print(f"Stage {stage} - Allocation Time: {allocation_time}")
    print(f"Stage {stage} - Elapsed Time: {solve_time}")
    print(f"Stage {stage} - Optimal Solution: {integer_objective}")
    print(
        f"Stage {stage} - Model Size: {len(problem.variables())} vars, "
        f"{len(problem.constraints)} constraints"
    )
    return {
        "objective": integer_objective,
        "allocation_time": allocation_time,
        "solve_time": solve_time,
        "variables": len(problem.variables()),
        "constraints": len(problem.constraints),
        "selected": selected,
    }


def assignment_record(index: Assignment, drcs) -> Dict[str, object]:
    path_id, drc_id, ru_id = index
    path = placeran.paths[path_id]
    drc = drcs[drc_id]
    placement = {
        "vupf": 0,
        "vcu": path.seq[0],
        "vdu": path.seq[1],
        "vru": path.seq[2],
    }
    return {
        "slice": ru_id,
        "ru": ru_id,
        "path": path_id,
        "drc": drc_id,
        "latency": path.delay_p1 + path.delay_p2 + path.delay_p3,
        "placement": placement,
        "cu": None if drc.Fs_CU == [0] else path.seq[0],
        "du": None if drc.Fs_DU == [0] else path.seq[1],
        "ru_cr": None if drc.Fs_RU == [0] else path.seq[2],
        "path_sequence": list(path.seq),
    }


def save_solution_csv(
    filepath: Path,
    records: Sequence[Mapping[str, object]],
    runtime: float,
    append: bool = False,
) -> Path:
    """Save the same compact CSV schema used by FlexRanSplitProblem."""
    filepath = filepath.expanduser().resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)
    write_header = not append or not filepath.exists() or filepath.stat().st_size == 0
    mode = "a" if append else "w"
    with filepath.open(mode, newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "NSC": record["slice"],
                    "DRC": record["drc"],
                    "path": record["path"],
                    "L": f"{record['latency']:.3f}",
                    "placement": str(record["placement"]),
                    "runtime": f"{runtime:.3f}",
                }
            )
    return filepath


def print_detailed_solution(records: Sequence[Mapping[str, object]]) -> None:
    print("Detailed Stage 3 placement:")
    print("RU -> Path -> DRC -> CU/DU/RU locations")
    for record in records:
        cu = "N/A" if record["cu"] is None else f"CR {record['cu']}"
        du = "N/A" if record["du"] is None else f"CR {record['du']}"
        ru = "N/A" if record["ru_cr"] is None else f"CR {record['ru_cr']}"
        print(
            f"RU {record['ru']} -> Path {record['path']} -> DRC {record['drc']} "
            f"-> CU={cu}, DU={du}, RU={ru}"
        )


def main() -> None:
    args = parse_args()
    total_started = time.perf_counter()
    print(f"Network settings: {args.network_settings}")
    print(f"Path settings   : {args.path_settings}")
    print(f"Network         : {args.network}")
    print(f"Paths per RU    : {args.k_paths}")
    drcs, rus = load_scenario(args.network)
    candidates = candidate_assignments(drcs, rus)
    print(f"{len(candidates)} feasible path/DRC/RU assignments generated")

    stage_1 = solve_stage(
        1, drcs, rus, candidates, args.solver_log, args.time_limit
    )
    stage_2 = solve_stage(
        2,
        drcs,
        rus,
        candidates,
        args.solver_log,
        args.time_limit,
        stage_1_value=stage_1["objective"],
        warm_start=stage_1["selected"],
    )
    stage_3 = solve_stage(
        3,
        drcs,
        rus,
        candidates,
        args.solver_log,
        args.time_limit,
        stage_1_value=stage_1["objective"],
        stage_2_value=stage_2["objective"],
        warm_start=stage_2["selected"],
    )

    records = [
        assignment_record(index, drcs)
        for index in sorted(stage_3["selected"], key=lambda item: item[2])
    ]
    print_detailed_solution(records)
    total_time = time.perf_counter() - total_started
    solver_runtime = sum(stage["solve_time"] for stage in (stage_1, stage_2, stage_3))
    print(f"TOTAL TIME: {total_time}")
    print(f"SOLVER TIME: {solver_runtime}")

    if not args.no_save:
        results_dir = args.results.expanduser().resolve()
        results_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_path = results_dir / f"placeran_pulp_{args.network}_{timestamp}.json"
        payload = {
            "method": "PlaceRAN",
            "backend": "PuLP/CBC",
            "scenario": args.network,
            "k_paths": args.k_paths,
            "network_settings": str(args.network_settings),
            "path_settings": str(args.path_settings),
            "stage_1": {key: value for key, value in stage_1.items() if key != "selected"},
            "stage_2": {key: value for key, value in stage_2.items() if key != "selected"},
            "stage_3": {key: value for key, value in stage_3.items() if key != "selected"},
            "total_time": total_time,
            "solver_runtime": solver_runtime,
            "assignments": records,
        }
        with result_path.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        csv_path = save_solution_csv(args.csv, records, solver_runtime, args.append)
        print(f"Result saved: {result_path}")
        print(f"CSV result : {csv_path}")


if __name__ == "__main__":
    main()
