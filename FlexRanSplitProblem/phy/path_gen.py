"""Generate physical paths independently of CU/DU placement decisions."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path as FilePath
from typing import List, Tuple

import networkx as nx

from .path_model import Path


def _parse_t1_node(value: str) -> int:
    return 0 if value == "CN" else int(str(value).rsplit("N", 1)[1])


def build_graph_from_links(links_json: str, topology: str = "T2") -> nx.Graph:
    graph = nx.Graph()
    with open(links_json, "r", encoding="utf-8") as stream:
        data = json.load(stream)

    if topology == "T1":
        for link in data["links"].values():
            graph.add_edge(
                _parse_t1_node(link["source"]["node"]),
                _parse_t1_node(link["destination"]["node"]),
                delay=float(str(link["LinkDelay"]).replace(",", ".")),
            )
    else:
        for link in data["links"]:
            graph.add_edge(
                int(link["fromNode"]),
                int(link["toNode"]),
                delay=float(link["delay"]),
            )
    return graph


def load_ru_nodes(nodes_json: str, topology: str = "T2") -> List[int]:
    with open(nodes_json, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if topology == "T1":
        return [
            int(key.rsplit("-", 1)[1])
            for key, node in data["nodes"].items()
            if int(node["RU"]) > 0
        ]
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
    topology: str = "T2",
) -> List[Path]:
    """Generate up to ``k_paths`` latency-shortest physical paths per RU node.

    CU and DU positions are deliberately not enumerated here: they are selected
    by ``x_node`` in the ILP.  Consequently, each physical node sequence occurs
    exactly once in the returned path set.
    """
    if k_paths < 1:
        raise ValueError("k_paths must be at least 1")

    topology = topology.strip().upper()
    if topology not in {"T1", "T2"}:
        raise ValueError("topology must be T1 or T2")

    graph = build_graph_from_links(links_json, topology)
    paths: List[Path] = []
    path_id = 1

    for ru_node in load_ru_nodes(nodes_json, topology):
        candidates = nx.shortest_simple_paths(
            graph,
            core_id,
            ru_node,
            weight="delay",
        )
        accepted = 0
        for node_sequence in candidates:
            nodes = list(node_sequence)
            if len(nodes) > 3 and 1 in nodes and 2 in nodes:
                continue
            edges = edges_from_nodes(nodes)
            paths.append(
                Path(
                    id=path_id,
                    nodes=nodes,
                    latency=path_delay(graph, edges),
                )
            )
            path_id += 1
            accepted += 1
            if accepted == k_paths:
                break

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
    parser.add_argument("--topology", choices=("T1", "T2"), default="T2")
    parser.add_argument("--out", required=True, help="Output pickle path")
    args = parser.parse_args()

    paths = generate_paths(
        links_json=args.links,
        nodes_json=args.nodes,
        core_id=args.core,
        k_paths=args.k_paths,
        output_path=args.out,
        topology=args.topology,
    )
    print(f"Generated {len(paths)} physical paths in {FilePath(args.out).resolve()}")


if __name__ == "__main__":
    main()
