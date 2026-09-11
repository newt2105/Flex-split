"""Summarize heterogeneous ILP solution CSV files by network size."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .compare_results import discover_results, summarize_solution


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_RESULTS = PACKAGE_DIR / "results_heterogeneous"
DEFAULT_OUTPUT = DEFAULT_RESULTS / "summary.csv"
OUTPUT_FIELDS = ("network", "drc_count", "runtime_s")


def write_summary(results: Path, output: Path) -> Path:
    files = discover_results(results, "flexible")
    if not files:
        raise ValueError(f"No network_*/solution.csv files found in {results}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for network, solution_path in sorted(files.items()):
            summary = summarize_solution(solution_path)
            writer.writerow(
                {
                    "network": network,
                    "drc_count": summary["drc_count"],
                    "runtime_s": f"{summary['runtime']:.3f}",
                }
            )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize runtime and DRC usage of heterogeneous ILP results"
    )
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = write_summary(args.results, args.output)
    print(f"Summary CSV: {output.resolve()}")


if __name__ == "__main__":
    main()
