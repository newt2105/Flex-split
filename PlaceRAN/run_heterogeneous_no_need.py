"""Run one generated heterogeneous topology using a single settings file."""

from __future__ import annotations

import argparse
import configparser
import subprocess
import sys
from pathlib import Path


PLACE_RAN_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS = PLACE_RAN_DIR / "settings" / "heterogeneous.txt"
SUPPORTED_NETWORKS = {8, 16, 32, 64, 128, 256}


def _resolve_from_placeran(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PLACE_RAN_DIR / path


def load_settings(path: Path) -> dict[str, object]:
    path = path.expanduser().resolve()
    parser = configparser.ConfigParser()
    with path.open("r", encoding="utf-8") as stream:
        parser.read_file(stream)

    network = parser.getint("run", "network")
    if network not in SUPPORTED_NETWORKS:
        choices = ", ".join(str(item) for item in sorted(SUPPORTED_NETWORKS))
        raise ValueError(f"[run] network must be one of: {choices}")

    k_paths = parser.getint("run", "k_paths", fallback=10)
    if k_paths < 1:
        raise ValueError("[run] k_paths must be positive")

    solver = parser.get("run", "solver", fallback="gurobi").strip().lower()
    if solver not in {"auto", "cbc", "gurobi"}:
        raise ValueError("[run] solver must be auto, cbc, or gurobi")

    topology_root = _resolve_from_placeran(
        parser.get(
            "run",
            "topology_root",
            fallback="../FlexRanSplitProblem/data_heterogeneous",
        )
    ).resolve()
    results_root = _resolve_from_placeran(
        parser.get("run", "results_root", fallback="results_pulp_heterogeneous")
    ).resolve()

    return {
        "settings": path,
        "network": network,
        "k_paths": k_paths,
        "solver": solver,
        "solver_log": parser.getboolean("run", "solver_log", fallback=False),
        "topology_root": topology_root,
        "results_root": results_root,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.settings)
    network = int(settings["network"])
    k_paths = int(settings["k_paths"])
    topology_dir = (
        Path(settings["topology_root"]) / f"network_{network}" / "placeran"
    )
    results_dir = (
        Path(settings["results_root"])
        / f"t2-{network}"
        / f"k_paths_{k_paths}"
    )

    expected = (
        topology_dir / f"{network}_CRs_links_LC.json",
        topology_dir / f"F1_{network}_CRs_nodes_LC.json",
    )
    missing = [path for path in expected if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing generated PlaceRAN topology file(s): "
            + ", ".join(str(path) for path in missing)
        )

    command = [
        sys.executable,
        str(PLACE_RAN_DIR / "run_model_pulp.py"),
        "--network",
        f"t2-{network}",
        "--k-paths",
        str(k_paths),
        "--topology-dir",
        str(topology_dir),
        "--results",
        str(results_dir),
        "--solver",
        str(settings["solver"]),
    ]
    if settings["solver_log"]:
        command.append("--solver-log")

    print(f"Settings : {settings['settings']}")
    print(f"Network  : t2-{network}")
    print(f"Topology : {topology_dir}")
    print(f"Results  : {results_dir}")
    subprocess.run(command, cwd=PLACE_RAN_DIR, check=True)


if __name__ == "__main__":
    main()
