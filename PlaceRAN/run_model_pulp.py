"""Generate paths and run the PlaceRAN PuLP/CBC implementation."""

from __future__ import annotations

import argparse
import configparser
import subprocess
import sys
from pathlib import Path


PLACE_RAN_DIR = Path(__file__).resolve().parent
DEFAULT_SETTINGS = PLACE_RAN_DIR / "settings" / "network.txt"
SUPPORTED_T2_SIZES = {8, 16, 32, 64, 128, 256}


def _resolve_from_placeran(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PLACE_RAN_DIR / path).resolve()


def parse_network_name(name: str) -> tuple[str, int]:
    normalized = name.strip().lower()
    try:
        topology, raw_size = normalized.split("-", 1)
        network_size = int(raw_size)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "[network] name must have the form t2-8 or t1-51"
        ) from exc

    if topology == "t1":
        if network_size != 51:
            raise ValueError("T1 currently supports only network t1-51")
    elif topology == "t2":
        if network_size not in SUPPORTED_T2_SIZES:
            choices = ", ".join(f"t2-{size}" for size in sorted(SUPPORTED_T2_SIZES))
            raise ValueError(f"Unsupported T2 network. Available values: {choices}")
    else:
        raise ValueError("[network] name must start with t1- or t2-")
    return topology, network_size


def load_network_settings(path: Path) -> tuple[str, list[str]]:
    """Translate one network INI file into the existing PlaceRAN CLI options."""
    path = path.expanduser().resolve()
    parser = configparser.ConfigParser()
    with path.open("r", encoding="utf-8") as stream:
        parser.read_file(stream)

    section = parser["network"]
    name = section.get("name", "").strip().lower()
    topology, network_size = parse_network_name(name)

    ru_distribution = section.get("ru_distribution", "F1").strip().upper()
    resource_level = section.get("resource_level", "LC").strip().upper()
    if ru_distribution not in {"R1", "F1"}:
        raise ValueError("[network] ru_distribution must be R1 or F1")
    if resource_level not in {"LC", "RC", "HC"}:
        raise ValueError("[network] resource_level must be LC, RC, or HC")

    k_paths = section.getint("k_paths", fallback=10)
    if k_paths < 1:
        raise ValueError("[network] k_paths must be positive")
    solver = section.get("solver", "cbc").strip().lower()
    if solver not in {"auto", "cbc", "gurobi"}:
        raise ValueError("[network] solver must be auto, cbc, or gurobi")

    scenario = f"{topology.upper()}-{ru_distribution}-{resource_level}"
    results_root = _resolve_from_placeran(
        section.get("results_root", "results_pulp")
    )
    results_dir = results_root / f"{scenario}-{network_size}" / f"k_paths_{k_paths}"

    options = [
        "--case",
        scenario,
        "--k-paths",
        str(k_paths),
        "--solver",
        solver,
        "--results",
        str(results_dir),
    ]
    if topology == "t2":
        options.extend(("--network", name))
    if section.getboolean("solver_log", fallback=False):
        options.append("--solver-log")

    raw_time_limit = section.get("time_limit", "").strip()
    if raw_time_limit:
        time_limit = float(raw_time_limit)
        if time_limit <= 0:
            raise ValueError("[network] time_limit must be positive or empty")
        options.extend(("--time-limit", raw_time_limit))

    return name, options


def build_child_arguments(argv: list[str]) -> tuple[Path, str, list[str]]:
    launcher = argparse.ArgumentParser(add_help=False)
    launcher.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    launcher_args, child_args = launcher.parse_known_args(argv)
    network_name, setting_args = load_network_settings(launcher_args.settings)

    # Preserve the old CLI workflow: an explicit --case or --network replaces
    # the topology/size selected in network.txt. Other explicit options are
    # appended after the defaults, so argparse uses the command-line value.
    options_to_remove = set()
    if "--case" in child_args or "--network" in child_args:
        options_to_remove.update(("--case", "--network", "--results"))
    if "--k-paths" in child_args:
        options_to_remove.add("--results")
    if options_to_remove:
        setting_args = [
            value
            for index, value in enumerate(setting_args)
            if value not in options_to_remove
            and not (
                index > 0
                and setting_args[index - 1] in options_to_remove
            )
        ]
    return launcher_args.settings.expanduser().resolve(), network_name, setting_args + child_args


def main() -> None:
    settings_path, network_name, child_args = build_child_arguments(sys.argv[1:])
    print(f"Settings         : {settings_path}")
    print(f"Configured network: {network_name}")
    subprocess.run(
        [
            sys.executable,
            str(PLACE_RAN_DIR / "model_files" / "path_gen.py"),
            *child_args,
        ],
        cwd=str(PLACE_RAN_DIR),
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(PLACE_RAN_DIR / "model_files" / "model_pulp.py"),
            *child_args,
        ],
        cwd=str(PLACE_RAN_DIR),
        check=True,
    )


if __name__ == "__main__":
    main()
