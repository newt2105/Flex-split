"""Generate PHY graphs and candidate paths for multiple T2 networks."""

from __future__ import annotations

import argparse
import configparser
import pickle
from pathlib import Path
from typing import Any, Dict, List

from .phy.genphy import load_phy_T2
from .phy.path_gen import generate_paths


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
DEFAULT_PATH_SETTINGS = PACKAGE_DIR / "settings" / "path_gen.txt"


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_DIR / path


def load_generation_settings(settings_path: str | Path) -> Dict[str, Any]:
    """Read path-generation options from ``settings/path_gen.txt``."""
    settings_path = Path(settings_path).expanduser()
    if not settings_path.is_absolute():
        settings_path = Path.cwd() / settings_path
    if not settings_path.is_file():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")

    parser = configparser.ConfigParser()
    with settings_path.open("r", encoding="utf-8") as stream:
        parser.read_file(stream)
    if not parser.has_section("generation"):
        raise ValueError(f"Missing [generation] section in {settings_path}")

    raw_networks = parser.get("generation", "networks", fallback="")
    try:
        networks: List[int] = [
            int(value.strip())
            for value in raw_networks.split(",")
            if value.strip()
        ]
    except ValueError as exc:
        raise ValueError(
            "[generation] networks must be comma-separated integers"
        ) from exc
    if not networks or any(network < 1 for network in networks):
        raise ValueError("[generation] networks must contain positive integers")

    k_paths = parser.getint("generation", "k_paths", fallback=10)
    if k_paths < 1:
        raise ValueError("[generation] k_paths must be at least 1")

    profile = parser.get("generation", "profile", fallback="LC").strip().upper()
    overwrite = parser.getboolean("generation", "overwrite", fallback=False)
    return {
        "settings": settings_path,
        "networks": networks,
        "profile": profile,
        "core": parser.getint("generation", "core", fallback=0),
        "k_paths": k_paths,
        "overwrite": overwrite,
        "source_directory": _resolve_repo_path(
            parser.get(
                "input",
                "source_directory",
                fallback="FlexRanSplitProblem/model_files/T2_files",
            )
        ),
        "output_directory": _resolve_repo_path(
            parser.get("output", "directory", fallback="data")
        ),
    }


def generate_network(
    network: int,
    *,
    profile: str,
    core: int,
    k_paths: int,
    overwrite: bool,
    source_directory: Path,
    output_directory: Path,
) -> Dict[str, Any]:
    """Generate one network and return a compact summary."""
    links_file = source_directory / f"{network}_CRs_links_{profile}.json"
    nodes_file = source_directory / f"F1_{network}_CRs_nodes_{profile}.json"
    output_dir = output_directory / f"network_{network}"
    phy_file = output_dir / "phy.pkl"
    paths_file = output_dir / "paths.pkl"

    missing = [path for path in (links_file, nodes_file) if not path.is_file()]
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing source file(s): {names}")
    output_dir.mkdir(parents=True, exist_ok=True)

    phy_created = overwrite or not phy_file.is_file()
    if phy_created:
        physical_network = load_phy_T2(str(links_file), str(nodes_file))
        with phy_file.open("wb") as stream:
            pickle.dump(physical_network, stream)
    else:
        with phy_file.open("rb") as stream:
            physical_network = pickle.load(stream)

    paths_created = overwrite or not paths_file.is_file()
    if paths_created:
        paths = generate_paths(
            links_json=str(links_file),
            nodes_json=str(nodes_file),
            core_id=core,
            k_paths=k_paths,
            output_path=str(paths_file),
        )
    else:
        with paths_file.open("rb") as stream:
            paths = pickle.load(stream)

    return {
        "network": network,
        "nodes": physical_network.number_of_nodes(),
        "edges": physical_network.number_of_edges(),
        "paths": len(paths),
        "phy_file": phy_file,
        "paths_file": paths_file,
        "phy_created": phy_created,
        "paths_created": paths_created,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate T2 PHY/path datasets listed in settings/path_gen.txt"
    )
    parser.add_argument("--settings", type=Path, default=DEFAULT_PATH_SETTINGS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_generation_settings(args.settings)
    print(f"Settings: {config['settings'].resolve()}")
    print(f"Networks: {config['networks']}")

    summaries = []
    for network in config["networks"]:
        print(f"\nGenerating network_{network} ...")
        summary = generate_network(
            network,
            profile=config["profile"],
            core=config["core"],
            k_paths=config["k_paths"],
            overwrite=config["overwrite"],
            source_directory=config["source_directory"],
            output_directory=config["output_directory"],
        )
        summaries.append(summary)
        action = "created" if (
            summary["phy_created"] or summary["paths_created"]
        ) else "already exists"
        print(
            f"  {action}: |N|={summary['nodes']}, |E|={summary['edges']}, "
            f"paths={summary['paths']}"
        )
        print(f"  PHY   : {summary['phy_file'].resolve()}")
        print(f"  Paths : {summary['paths_file'].resolve()}")

    print(f"\nDone: {len(summaries)} network(s) are ready")


if __name__ == "__main__":
    main()
