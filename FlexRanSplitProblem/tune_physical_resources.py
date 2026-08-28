"""Generate heterogeneous T2 JSON profiles while preserving PlaceRAN inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

try:
    from .phy.resource_tuning import tune_t2_resources
except ImportError:  # Direct execution from FlexRanSplitProblem/.
    from phy.resource_tuning import tune_t2_resources


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = PACKAGE_DIR / "model_files" / "T2_files"
DEFAULT_OUTPUT = PACKAGE_DIR / "model_files" / "T2_tuned_files"
DEFAULT_NETWORKS = (8, 16, 32, 64, 128, 256)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2)
        stream.write("\n")


def generate_profiles(
    networks: Iterable[int],
    *,
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    core_id: int = 0,
) -> list[dict]:
    summaries = []
    for network in networks:
        nodes_source = source / f"F1_{network}_CRs_nodes_LC.json"
        links_source = source / f"{network}_CRs_links_LC.json"
        missing = [
            str(path) for path in (nodes_source, links_source) if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(f"Missing PlaceRAN source file(s): {missing}")

        nodes, links, summary = tune_t2_resources(
            _load_json(nodes_source),
            _load_json(links_source),
            network=network,
            core_id=core_id,
        )
        _write_json(output / f"F1_{network}_CRs_nodes_HET.json", nodes)
        _write_json(output / f"{network}_CRs_links_HET.json", links)
        summaries.append(summary.to_dict())

    manifest = {
        "source_profile": "LC",
        "output_profile": "HET",
        "topology_and_delays_preserved": True,
        "networks": summaries,
    }
    _write_json(output / "resource_profiles_HET.json", manifest)
    return summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate heterogeneous T2 node/link resource profiles"
    )
    parser.add_argument("--networks", nargs="+", type=int, default=DEFAULT_NETWORKS)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--core", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summaries = generate_profiles(
        args.networks,
        source=args.source,
        output=args.output,
        core_id=args.core,
    )
    for summary in summaries:
        print(
            f"network_{summary['network']}: "
            f"A=CR{summary['profile_a_node']}, "
            f"B=CR{summary['profile_b_node']}"
        )
    print(f"HET JSON directory: {args.output.resolve()}")


if __name__ == "__main__":
    main()

