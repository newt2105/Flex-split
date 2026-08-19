"""Generate physical paths independently of CU/DU placement decisions."""

from __future__ import annotations

import argparse
import itertools
import json
import pickle
from pathlib import Path as FilePath
from typing import List, Tuple

import networkx as nx

from .path_model import Path


def build_graph_from_links(links_json: str) -> nx.Graph:
    graph = nx.Graph()
    with open(links_json, "r", encoding="utf-8") as stream:
        data = json.load(stream)

    for link in data["links"]:
        graph.add_edge(
            int(link["fromNode"]),
            int(link["toNode"]),
            delay=float(link["delay"]),
        )
    return graph


def load_ru_nodes(nodes_json: str) -> List[int]:
    with open(nodes_json, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    return [
        int(node["nodeNumber"])
        for node in data["nodes"]
        if int(node["RU"]) > 0
    ]


def path_delay(graph: nx.Graph, edges: List[Tuple[int, int]]) -> float:
    return sum(float(graph[u][v]["delay"]) for u, v in edges)


def edges_from_nodes(nodes: List[int]) -> List[Tuple[int, int]]:
    return list(zip(nodes, nodes[1:]))


def generate_paths(
    links_json: str,
    nodes_json: str,
    core_id: int = 0,
    k_paths: int = 4,
    output_path: str | None = None,
) -> List[Path]:
    """Generate up to ``k_paths`` latency-shortest physical paths per RU node.

    CU and DU positions are deliberately not enumerated here: they are selected
    by ``x_node`` in the ILP.  Consequently, each physical node sequence occurs
    exactly once in the returned path set.
    """
    if k_paths < 1:
        raise ValueError("k_paths must be at least 1")

    graph = build_graph_from_links(links_json)
    paths: List[Path] = []
    path_id = 1

    for ru_node in load_ru_nodes(nodes_json):
        candidates = nx.shortest_simple_paths(
            graph,
            core_id,
            ru_node,
            weight="delay",
        )
        for node_sequence in itertools.islice(candidates, k_paths):
            nodes = list(node_sequence)
            edges = edges_from_nodes(nodes)
            paths.append(
                Path(
                    id=path_id,
                    nodes=nodes,
                    latency=path_delay(graph, edges),
                )
            )
            path_id += 1

    if output_path is not None:
        destination = FilePath(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as stream:
            pickle.dump(paths, stream)

    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate core-to-RU physical paths for the placement ILP"
    )
    parser.add_argument("--links", required=True, help="Physical-link JSON")
    parser.add_argument("--nodes", required=True, help="Physical-node/RU JSON")
    parser.add_argument("--core", type=int, default=0, help="Core node ID")
    parser.add_argument("--k-paths", type=int, default=4)
    parser.add_argument("--out", required=True, help="Output pickle path")
    args = parser.parse_args()

    paths = generate_paths(
        links_json=args.links,
        nodes_json=args.nodes,
        core_id=args.core,
        k_paths=args.k_paths,
        output_path=args.out,
    )
    print(f"Generated {len(paths)} physical paths in {FilePath(args.out).resolve()}")


if __name__ == "__main__":
    main()
