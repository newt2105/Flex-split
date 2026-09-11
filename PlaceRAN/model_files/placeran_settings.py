"""Shared command-line settings for PlaceRAN path generation and PuLP."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict


PLACE_RAN_DIR = Path(__file__).resolve().parent.parent
CASE_CHOICES = tuple(
    f"{topology}-{ru}-{resource}"
    for topology in ("T1", "T2")
    for ru in ("R1", "F1")
    for resource in ("LC", "RC", "HC")
)
NETWORK_CHOICES = ("t2-8", "t2-16", "t2-32", "t2-64", "t2-128", "t2-256")
STANDARD_NETWORK_SIZES = {"T1": 51, "T2": 128}


def parse_case(value: str) -> tuple[str, str, str]:
    normalized = value.strip().upper()
    if normalized not in CASE_CHOICES:
        choices = ", ".join(CASE_CHOICES)
        raise ValueError(f"case must be one of: {choices}")
    topology, ru_distribution, resource_level = normalized.split("-")
    return topology, ru_distribution, resource_level


def _resolve_directory(value: Path | None, topology: str) -> Path:
    path = value or PLACE_RAN_DIR / "model_files" / f"{topology}_files"
    path = path.expanduser()
    resolved = path if path.is_absolute() else PLACE_RAN_DIR / path
    if not resolved.is_dir():
        raise FileNotFoundError(f"Topology directory not found: {resolved.resolve()}")
    return resolved.resolve()


def _resolve_file(value: Path) -> Path:
    path = value.expanduser()
    return (path if path.is_absolute() else PLACE_RAN_DIR / path).resolve()


def add_settings_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--case",
        default="T2-F1-LC",
        help="scenario in the form T1-R1-LC (default: T2-F1-LC)",
    )
    parser.add_argument(
        "--network",
        choices=NETWORK_CHOICES,
        default=None,
        help="legacy/generated T2 size override, for example t2-32",
    )
    parser.add_argument(
        "--topology-dir",
        type=Path,
        default=None,
        help="directory containing matching PlaceRAN node/link JSON files",
    )
    parser.add_argument(
        "--k-paths",
        type=int,
        default=10,
        help="maximum number of physical core-to-RU paths (default: 10)",
    )
    parser.add_argument(
        "--paths-file",
        type=Path,
        default=PLACE_RAN_DIR / "paths.json",
        help="generated candidate-path JSON file",
    )


def resolve_settings(args: argparse.Namespace) -> Dict[str, object]:
    topology, ru_distribution, resource_level = parse_case(args.case)
    network_size = STANDARD_NETWORK_SIZES[topology]

    if args.network is not None:
        if topology != "T2":
            raise ValueError("--network can only be combined with a T2 case")
        network_size = int(args.network.rsplit("-", 1)[1])

    if args.k_paths < 1:
        raise ValueError("k_paths must be a positive integer")

    scenario = f"{topology}-{ru_distribution}-{resource_level}"
    return {
        "scenario": scenario,
        "topology": topology,
        "ru_distribution": ru_distribution,
        "resource_level": resource_level,
        "network_size": network_size,
        "network": f"{topology.lower()}-{network_size}",
        "k_paths": args.k_paths,
        "topology_dir": _resolve_directory(args.topology_dir, topology),
        "paths_file": _resolve_file(args.paths_file),
    }
