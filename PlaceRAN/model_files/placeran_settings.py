"""Shared settings loader for PlaceRAN path generation and optimization."""

from __future__ import annotations

import argparse
import configparser
from pathlib import Path
from typing import Dict, Union


PLACE_RAN_DIR = Path(__file__).resolve().parent.parent
DEFAULT_NETWORK_SETTINGS = PLACE_RAN_DIR / "settings" / "network.txt"
DEFAULT_PATH_SETTINGS = PLACE_RAN_DIR / "settings" / "path.txt"
NETWORK_CHOICES = ("t2-8", "t2-16", "t2-32", "t2-64", "t2-128", "t2-256")


def _resolve_settings_path(value: Union[str, Path]) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _resolve_topology_directory(value: Union[str, Path]) -> Path:
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else Path.cwd() / path
    if not resolved.is_dir():
        raise FileNotFoundError(
            f"Topology directory not found: {resolved.resolve()}"
        )
    return resolved.resolve()


def _read_parser(path: Union[str, Path]) -> tuple[Path, configparser.ConfigParser]:
    resolved = _resolve_settings_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Settings file not found: {resolved.resolve()}")
    parser = configparser.ConfigParser()
    with resolved.open("r", encoding="utf-8") as stream:
        parser.read_file(stream)
    return resolved.resolve(), parser


def load_network_settings(path: Union[str, Path]) -> tuple[Path, str]:
    resolved, parser = _read_parser(path)
    if not parser.has_section("network") or not parser.has_option("network", "name"):
        raise ValueError(f"Missing [network] name in {resolved}")
    network = parser.get("network", "name").strip().lower()
    if network not in NETWORK_CHOICES:
        choices = ", ".join(NETWORK_CHOICES)
        raise ValueError(f"[network] name must be one of: {choices}")
    return resolved, network


def load_path_settings(path: Union[str, Path]) -> tuple[Path, int]:
    resolved, parser = _read_parser(path)
    if not parser.has_section("paths") or not parser.has_option("paths", "k_paths"):
        raise ValueError(f"Missing [paths] k_paths in {resolved}")
    k_paths = parser.getint("paths", "k_paths")
    if k_paths < 1:
        raise ValueError("[paths] k_paths must be a positive integer")
    return resolved, k_paths


def add_settings_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--network-settings",
        type=Path,
        default=DEFAULT_NETWORK_SETTINGS,
        help=f"network settings file (default: {DEFAULT_NETWORK_SETTINGS})",
    )
    parser.add_argument(
        "--path-settings",
        type=Path,
        default=DEFAULT_PATH_SETTINGS,
        help=f"path settings file (default: {DEFAULT_PATH_SETTINGS})",
    )
    parser.add_argument(
        "--network",
        choices=NETWORK_CHOICES,
        default=None,
        help="override [network] name",
    )
    parser.add_argument(
        "--topology-dir",
        type=Path,
        default=None,
        help="directory containing PlaceRAN-compatible T2 node/link JSON files",
    )
    parser.add_argument(
        "--k-paths",
        type=int,
        default=None,
        help="override [paths] k_paths",
    )


def resolve_settings(args: argparse.Namespace) -> Dict[str, object]:
    network_settings, configured_network = load_network_settings(args.network_settings)
    path_settings, configured_k_paths = load_path_settings(args.path_settings)
    network = args.network or configured_network
    k_paths = args.k_paths if args.k_paths is not None else configured_k_paths
    topology_dir = (
        _resolve_topology_directory(args.topology_dir)
        if args.topology_dir is not None
        else (PLACE_RAN_DIR / "model_files" / "T2_files").resolve()
    )
    if k_paths < 1:
        raise ValueError("k_paths must be a positive integer")
    return {
        "network_settings": network_settings,
        "path_settings": path_settings,
        "network": network,
        "k_paths": k_paths,
        "topology_dir": topology_dir,
    }
