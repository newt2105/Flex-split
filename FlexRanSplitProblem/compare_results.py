"""Compare PlaceRAN and FlexibleSplit solution CSV files by network size."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
DEFAULT_PLACERAN_RESULTS = REPO_DIR / "PlaceRAN" / "results_pulp"
DEFAULT_FLEX_RESULTS = PACKAGE_DIR / "results"
DEFAULT_OUTPUT = DEFAULT_FLEX_RESULTS / "comparison.csv"

OUTPUT_FIELDS = (
    "network",
    "placeran_runtime_s",
    "flexible_runtime_s",
    "placeran_drc_count",
    "flexible_drc_count",
)


def _network_from_path(path: Path, model: str) -> int | None:
    """Extract the CR count from a PlaceRAN or FlexibleSplit result path."""
    text = path.as_posix()
    pattern = r"(?:^|/)t2-(\d+)(?:/|$)" if model == "placeran" else r"(?:^|/)network_(\d+)(?:/|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def discover_results(root: str | Path, model: str) -> Dict[int, Path]:
    """Return one ``solution.csv`` path per discovered network size."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"Results directory not found: {root}")

    discovered: Dict[int, Path] = {}
    for path in sorted(root.rglob("solution.csv")):
        network = _network_from_path(path, model)
        if network is None:
            continue
        if network in discovered:
            raise ValueError(
                f"Multiple {model} solution.csv files found for network "
                f"{network}: {discovered[network]} and {path}"
            )
        discovered[network] = path
    return discovered


def _latest_run(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep the last NSC sequence when a CSV contains appended runs."""
    runs: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    previous_nsc: int | None = None

    for row in rows:
        raw_nsc = (row.get("NSC") or "").strip()
        if not raw_nsc or raw_nsc.upper() == "NSC":
            continue
        try:
            nsc = int(raw_nsc)
        except ValueError as exc:
            raise ValueError(f"Invalid NSC value {raw_nsc!r}") from exc
        if current and previous_nsc is not None and nsc <= previous_nsc:
            runs.append(current)
            current = []
        current.append(row)
        previous_nsc = nsc

    if current:
        runs.append(current)
    if not runs:
        raise ValueError("Solution CSV contains no NSC result rows")
    return runs[-1]


def summarize_solution(path: str | Path) -> Dict[str, Any]:
    """Summarize runtime and unique DRC usage from one solution CSV."""
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"NSC", "DRC", "runtime"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"{path} is missing required column(s): {sorted(missing)}"
            )
        rows = _latest_run(reader)

    runtimes = {
        float(row["runtime"])
        for row in rows
        if (row.get("runtime") or "").strip()
    }
    if len(runtimes) != 1:
        raise ValueError(
            f"Expected one repeated runtime value in {path}, found "
            f"{sorted(runtimes)}"
        )

    drcs = sorted(
        {
            int(float(row["DRC"]))
            for row in rows
            if (row.get("DRC") or "").strip()
        }
    )
    return {
        "runtime": runtimes.pop(),
        "drc_count": len(drcs),
    }


def compare_networks(
    placeran_results: str | Path = DEFAULT_PLACERAN_RESULTS,
    flexible_results: str | Path = DEFAULT_FLEX_RESULTS,
) -> List[Dict[str, Any]]:
    """Compare networks that have a solution CSV in both result trees."""
    placeran_files = discover_results(placeran_results, "placeran")
    flexible_files = discover_results(flexible_results, "flexible")
    common_networks = sorted(set(placeran_files).intersection(flexible_files))
    if not common_networks:
        raise ValueError("No matching network sizes were found")

    rows: List[Dict[str, Any]] = []
    for network in common_networks:
        placeran = summarize_solution(placeran_files[network])
        flexible = summarize_solution(flexible_files[network])
        rows.append(
            {
                "network": network,
                "placeran_runtime_s": f"{placeran['runtime']:.3f}",
                "flexible_runtime_s": f"{flexible['runtime']:.3f}",
                "placeran_drc_count": placeran["drc_count"],
                "flexible_drc_count": flexible["drc_count"],
            }
        )
    return rows


def write_comparison_csv(rows: Iterable[Dict[str, Any]], output: str | Path) -> Path:
    """Write comparison rows to CSV."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare PlaceRAN and FlexibleSplit runtimes/DRC usage"
    )
    parser.add_argument("--placeran", type=Path, default=DEFAULT_PLACERAN_RESULTS)
    parser.add_argument("--flexible", type=Path, default=DEFAULT_FLEX_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = compare_networks(args.placeran, args.flexible)
    output = write_comparison_csv(rows, args.output)
    print(f"Compared networks: {[row['network'] for row in rows]}")
    print(f"Comparison CSV: {output.resolve()}")
    for row in rows:
        print(
            f"network_{row['network']}: runtime PlaceRAN="
            f"{row['placeran_runtime_s']}s, FlexibleSplit="
            f"{row['flexible_runtime_s']}s; DRC count PlaceRAN="
            f"{row['placeran_drc_count']}, FlexibleSplit="
            f"{row['flexible_drc_count']}"
        )


if __name__ == "__main__":
    main()
