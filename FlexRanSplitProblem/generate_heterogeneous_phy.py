"""Generate persistent heterogeneous PHY datasets from existing T2 pickles."""

from __future__ import annotations

import argparse
import configparser
import json
import pickle
import shutil
from pathlib import Path
from typing import Any, Dict, Tuple


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
DEFAULT_SETTINGS = PACKAGE_DIR / "settings" / "heterogeneous_phy.txt"


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_DIR / path


def _parse_int_list(value: str, option: str) -> Tuple[int, ...]:
    try:
        result = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError(f"[{option}] must be a comma-separated integer list") from exc
    if not result:
        raise ValueError(f"[{option}] must contain at least one value")
    return result


def _parse_factors(value: str, option: str) -> Tuple[float, ...]:
    try:
        factors = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError(f"[{option}] must be a comma-separated numeric list") from exc
    if not factors:
        raise ValueError(f"[{option}] must contain at least one factor")
    if any(factor <= 0.0 or factor > 1.0 for factor in factors):
        raise ValueError(f"[{option}] factors must be in the interval (0, 1]")
    return factors


def load_settings(settings_path: str | Path) -> Dict[str, Any]:
    """Read and validate heterogeneous-PHY generation settings."""
    settings_path = Path(settings_path).expanduser()
    if not settings_path.is_absolute():
        settings_path = Path.cwd() / settings_path
    if not settings_path.is_file():
        raise FileNotFoundError(f"Settings file not found: {settings_path.resolve()}")

    parser = configparser.ConfigParser()
    with settings_path.open("r", encoding="utf-8") as stream:
        parser.read_file(stream)

    for section in ("generation", "input", "output"):
        if not parser.has_section(section):
            raise ValueError(f"Missing [{section}] section in {settings_path}")

    networks = _parse_int_list(
        parser.get("generation", "networks"),
        "generation/networks",
    )
    if any(network < 1 for network in networks):
        raise ValueError("[generation] networks must contain positive integers")

    return {
        "settings": settings_path,
        "networks": networks,
        "profile": parser.get("generation", "profile", fallback="LC").strip().upper(),
        "core": parser.getint("generation", "core", fallback=0),
        "node_cpu_factors": _parse_factors(
            parser.get("generation", "node_cpu_factors"),
            "generation/node_cpu_factors",
        ),
        "link_bw_factors": _parse_factors(
            parser.get("generation", "link_bw_factors"),
            "generation/link_bw_factors",
        ),
        "overwrite": parser.getboolean("generation", "overwrite", fallback=False),
        "copy_paths": parser.getboolean("output", "copy_paths", fallback=True),
        "write_placeran_json": parser.getboolean(
            "output", "write_placeran_json", fallback=True
        ),
        "source_data_directory": _resolve_repo_path(
            parser.get("input", "data_directory", fallback="data")
        ),
        "source_nodes_directory": _resolve_repo_path(
            parser.get(
                "input",
                "nodes_directory",
                fallback="FlexRanSplitProblem/model_files/T2_files",
            )
        ),
        "output_directory": _resolve_repo_path(
            parser.get(
                "output",
                "directory",
                fallback="FlexRanSplitProblem/data_heterogeneous",
            )
        ),
    }


def _edge_key(source: Any, target: Any) -> Tuple[Any, Any]:
    return tuple(sorted((source, target)))


def _capacity(attributes: Dict[str, Any]) -> float:
    for key in ("capacity", "cap", "bandwidth"):
        if key in attributes:
            return float(attributes[key])
    raise KeyError("Physical link has no capacity/cap/bandwidth attribute")


def _set_capacity(attributes: Dict[str, Any], value: float) -> None:
    for key in ("capacity", "cap", "bandwidth"):
        if key in attributes:
            attributes[key] = value
            return
    attributes["capacity"] = value


def make_heterogeneous(
    physical_network: Any,
    *,
    core_id: int,
    node_cpu_factors: Tuple[float, ...],
    link_bw_factors: Tuple[float, ...],
) -> Dict[str, Any]:
    """Scale resources in place and return a serializable change summary."""
    node_changes = []
    nodes = sorted(node for node in physical_network.nodes if node != core_id)
    for index, node in enumerate(nodes):
        factor = node_cpu_factors[index % len(node_cpu_factors)]
        attributes = physical_network.nodes[node]
        old_cpu = float(attributes.get("cpu", 0.0))
        new_cpu = old_cpu * factor
        attributes["cpu"] = new_cpu
        node_changes.append(
            {
                "node": node,
                "old_cpu": old_cpu,
                "factor": factor,
                "new_cpu": new_cpu,
            }
        )

    pairs = sorted(
        {_edge_key(source, target) for source, target in physical_network.edges if source != target}
    )
    link_changes = []
    for index, (source, target) in enumerate(pairs):
        factor = link_bw_factors[index % len(link_bw_factors)]
        directions = []
        if physical_network.has_edge(source, target):
            directions.append(physical_network[source][target])
        if physical_network.has_edge(target, source):
            directions.append(physical_network[target][source])
        if not directions:
            continue

        old_bw = min(_capacity(attributes) for attributes in directions)
        new_bw = old_bw * factor
        for attributes in directions:
            _set_capacity(attributes, new_bw)
        link_changes.append(
            {
                "source": source,
                "target": target,
                "old_bandwidth": old_bw,
                "factor": factor,
                "new_bandwidth": new_bw,
            }
        )

    return {"nodes": node_changes, "links": link_changes}


def _write_pickle(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def _write_nodes_json(source: Path, output: Path, physical_network: Any) -> None:
    with source.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    for item in payload["nodes"]:
        node = int(item["nodeNumber"])
        if node in physical_network:
            item["cpu"] = physical_network.nodes[node]["cpu"]
    with output.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _write_links_json(source: Path, output: Path, physical_network: Any) -> None:
    """Write PlaceRAN-compatible link JSON with scaled capacities."""
    with source.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    for item in payload["links"]:
        source_node = int(item["fromNode"])
        target_node = int(item["toNode"])
        if physical_network.has_edge(source_node, target_node):
            attributes = physical_network[source_node][target_node]
        elif physical_network.has_edge(target_node, source_node):
            attributes = physical_network[target_node][source_node]
        else:
            raise ValueError(
                f"Source link {(source_node, target_node)} is missing from the PHY"
            )
        item["capacity"] = _capacity(attributes)
    with output.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def generate_network(network: int, settings: Dict[str, Any]) -> Path:
    """Generate one self-contained heterogeneous dataset directory."""
    source_dir = settings["source_data_directory"] / f"network_{network}"
    source_phy = source_dir / "phy.pkl"
    source_paths = source_dir / "paths.pkl"
    source_nodes = (
        settings["source_nodes_directory"]
        / f"F1_{network}_CRs_nodes_{settings['profile']}.json"
    )
    source_links = (
        settings["source_nodes_directory"]
        / f"{network}_CRs_links_{settings['profile']}.json"
    )
    required = [source_phy, source_nodes]
    if settings["copy_paths"]:
        required.append(source_paths)
    if settings["write_placeran_json"]:
        required.append(source_links)
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing input file(s): " + ", ".join(str(path) for path in missing)
        )

    output_dir = settings["output_directory"] / f"network_{network}"
    output_phy = output_dir / "phy.pkl"
    placeran_dir = output_dir / "placeran"
    expected_outputs = [output_phy, output_dir / "nodes.json"]
    if settings["copy_paths"]:
        expected_outputs.append(output_dir / "paths.pkl")
    if settings["write_placeran_json"]:
        expected_outputs.extend(
            (
                placeran_dir
                / f"F1_{network}_CRs_nodes_{settings['profile']}.json",
                placeran_dir / f"{network}_CRs_links_{settings['profile']}.json",
            )
        )
    if all(path.exists() for path in expected_outputs) and not settings["overwrite"]:
        print(f"network_{network}: skipped (already exists: {output_phy})")
        return output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    with source_phy.open("rb") as stream:
        physical_network = pickle.load(stream)

    changes = make_heterogeneous(
        physical_network,
        core_id=settings["core"],
        node_cpu_factors=settings["node_cpu_factors"],
        link_bw_factors=settings["link_bw_factors"],
    )
    _write_pickle(output_phy, physical_network)
    _write_nodes_json(source_nodes, output_dir / "nodes.json", physical_network)

    if settings["write_placeran_json"]:
        placeran_dir.mkdir(parents=True, exist_ok=True)
        _write_nodes_json(
            source_nodes,
            placeran_dir / f"F1_{network}_CRs_nodes_{settings['profile']}.json",
            physical_network,
        )
        _write_links_json(
            source_links,
            placeran_dir / f"{network}_CRs_links_{settings['profile']}.json",
            physical_network,
        )

    if settings["copy_paths"]:
        shutil.copy2(source_paths, output_dir / "paths.pkl")

    summary = {
        "network": network,
        "source_phy": str(source_phy.resolve()),
        "node_cpu_factors": settings["node_cpu_factors"],
        "link_bw_factors": settings["link_bw_factors"],
        **changes,
    }
    with (output_dir / "resource_changes.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")

    print(
        f"network_{network}: saved {output_phy} "
        f"({len(changes['nodes'])} nodes, {len(changes['links'])} links)"
    )
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create persistent heterogeneous PHY datasets"
    )
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.settings)
    print(f"Settings: {settings['settings'].resolve()}")
    print(f"Networks: {list(settings['networks'])}")
    print(f"Output  : {settings['output_directory'].resolve()}")
    for network in settings["networks"]:
        generate_network(network, settings)


if __name__ == "__main__":
    main()
