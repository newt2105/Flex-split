"""Batch runner for heterogeneous Flex-split experiments."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_NETWORKS = (8, 16, 32, 64, 128, 256)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run heterogeneous Flex-split experiments")
    parser.add_argument("--networks", nargs="+", type=int, default=list(DEFAULT_NETWORKS))
    parser.add_argument("--profile", default="LC")
    parser.add_argument("--settings", default="FlexRanSplitProblem/settings/ilp.txt")
    parser.add_argument("--solver", choices=("auto", "cbc", "gurobi"), default="auto")
    parser.add_argument("--beta", type=float, default=0.5)
    parser.add_argument("--results-root", default="results_hetero")
    parser.add_argument("--solver-log", action="store_true")
    parser.add_argument("--quiet-hetero", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0.0 <= args.beta <= 1.0:
        raise ValueError("--beta must be between 0 and 1")

    results_root = REPO_DIR / args.results_root
    results_root.mkdir(parents=True, exist_ok=True)

    print("========================================")
    print(" Flex-split heterogeneous experiments")
    print("========================================")
    print(f"Networks : {args.networks}")
    print(f"Profile  : {args.profile}")
    print(f"Beta     : {args.beta}")
    print(f"Solver   : {args.solver}")
    print(f"Output   : {results_root}")

    for network in args.networks:
        print("\n" + "=" * 72)
        print(f"NETWORK {network}")
        print("=" * 72)

        network_results = results_root / f"network_{network}"
        network_results.mkdir(parents=True, exist_ok=True)

        phy = REPO_DIR / "data" / f"network_{network}" / "phy.pkl"
        paths = REPO_DIR / "data" / f"network_{network}" / "paths.pkl"
        nodes = (
            REPO_DIR
            / "FlexRanSplitProblem"
            / "model_files"
            / "T2_files"
            / f"F1_{network}_CRs_nodes_{args.profile}.json"
        )
        csv_path = network_results / "solution.csv"

        cmd = [
            sys.executable,
            "-m",
            "FlexRanSplitProblem.trung_run_ilp",
            "--settings",
            str(REPO_DIR / args.settings),
            "--phy",
            str(phy),
            "--paths",
            str(paths),
            "--nodes",
            str(nodes),
            "--results",
            str(network_results),
            "--csv",
            str(csv_path),
            "--solver",
            args.solver,
            "--beta",
            str(args.beta),
        ]

        if args.solver_log:
            cmd.append("--solver-log")
        if args.quiet_hetero:
            cmd.append("--quiet-hetero")

        subprocess.run(cmd, cwd=REPO_DIR, check=True)

    print("\nAll heterogeneous experiments completed.")
    print(f"Results: {results_root}")


if __name__ == "__main__":
    main()
