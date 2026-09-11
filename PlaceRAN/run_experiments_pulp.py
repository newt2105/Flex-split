"""Run an ordered list of PlaceRAN scenarios from one INI settings file."""

from __future__ import annotations

import argparse
import configparser
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PLACE_RAN_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS = PLACE_RAN_DIR / "settings" / "experiments.ini"
VALID_CASES = {
    f"{topology}-{ru}-{resource}"
    for topology in ("T1", "T2")
    for ru in ("R1", "F1")
    for resource in ("LC", "RC", "HC")
}


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PLACE_RAN_DIR / path).resolve()


def load_settings(path: Path):
    path = path.expanduser().resolve()
    parser = configparser.ConfigParser(allow_no_value=True)
    with path.open(encoding="utf-8") as stream:
        parser.read_file(stream)
    section = parser["experiments"]
    cases = [item.strip().upper() for item in section.get("cases", "").splitlines() if item.strip()]
    invalid = [item for item in cases if item not in VALID_CASES]
    if not cases:
        raise ValueError("[experiments] cases must contain at least one scenario")
    if invalid:
        raise ValueError("Invalid case(s): " + ", ".join(invalid))
    k_paths = section.getint("k_paths", 10)
    if k_paths < 1:
        raise ValueError("k_paths must be positive")
    solver = section.get("solver", "cbc").strip().lower()
    if solver not in {"cbc", "gurobi", "auto"}:
        raise ValueError("solver must be cbc, gurobi, or auto")
    raw_time_limit = section.get("time_limit", "").strip()
    time_limit = float(raw_time_limit) if raw_time_limit else None
    if time_limit is not None and time_limit <= 0:
        raise ValueError("time_limit must be positive or empty")
    return {
        "path": path,
        "cases": cases,
        "k_paths": k_paths,
        "solver": solver,
        "solver_log": section.getboolean("solver_log", False),
        "time_limit": time_limit,
        "stop_on_error": section.getboolean("stop_on_error", True),
        "results_root": resolve_path(section.get("results_root", "results_pulp")),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    return parser.parse_args()


def main():
    settings = load_settings(parse_args().settings)
    settings["results_root"].mkdir(parents=True, exist_ok=True)
    print(f"Settings: {settings['path']}")
    print(f"Cases   : {', '.join(settings['cases'])}")
    print(f"Solver  : {settings['solver']}")
    print(f"Results : {settings['results_root']}")

    summary = []
    total = len(settings["cases"])
    for index, case in enumerate(settings["cases"], start=1):
        print("\n" + "=" * 80)
        print(f"CASE {index}/{total}: {case}")
        print("=" * 80, flush=True)
        result_dir = settings["results_root"] / case / f"k_paths_{settings['k_paths']}"
        command = [
            sys.executable,
            str(PLACE_RAN_DIR / "run_model_pulp.py"),
            "--case",
            case,
            "--k-paths",
            str(settings["k_paths"]),
            "--solver",
            settings["solver"],
            "--results",
            str(result_dir),
        ]
        if settings["solver_log"]:
            command.append("--solver-log")
        if settings["time_limit"] is not None:
            command.extend(("--time-limit", str(settings["time_limit"])))

        started = time.perf_counter()
        completed = subprocess.run(command, cwd=PLACE_RAN_DIR, check=False)
        elapsed = time.perf_counter() - started
        status = "OK" if completed.returncode == 0 else "FAILED"
        summary.append((case, status, completed.returncode, elapsed, str(result_dir)))
        if completed.returncode and settings["stop_on_error"]:
            break

    summary_path = settings["results_root"] / "run_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("case", "status", "return_code", "elapsed_seconds", "results_dir", "finished_at"))
        finished_at = datetime.now().isoformat(timespec="seconds")
        for case, status, return_code, elapsed, result_dir in summary:
            writer.writerow((case, status, return_code, f"{elapsed:.3f}", result_dir, finished_at))

    failed = [row[0] for row in summary if row[1] == "FAILED"]
    print("\nRun summary:")
    for case, status, _return_code, elapsed, _result_dir in summary:
        print(f"  {case}: {status} ({elapsed:.3f}s)")
    print(f"Summary CSV: {summary_path}")
    if failed:
        raise SystemExit("Failed case(s): " + ", ".join(failed))


if __name__ == "__main__":
    main()
