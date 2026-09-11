"""Generate candidate PlaceRAN paths for one configured scenario."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

import model as placeran
from placeran_settings import add_settings_arguments, resolve_settings


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    add_settings_arguments(parser)
    parsed = parser.parse_known_args()[0]
    for key, value in resolve_settings(parsed).items():
        setattr(parsed, key, value)
    return parsed


def load_graph(args):
    links_file, nodes_file = placeran.topology_files(
        args.topology,
        args.network_size,
        args.ru_distribution,
        args.resource_level,
        args.topology_dir,
    )
    adjacency = defaultdict(list)
    with links_file.open(encoding="utf-8") as stream:
        raw_links = json.load(stream)["links"]
    records = raw_links.values() if args.topology == "T1" else raw_links
    for link in records:
        if args.topology == "T1":
            source = placeran._node_number(link["source"]["node"])
            destination = placeran._node_number(link["destination"]["node"])
            adjacency[source].append(destination)
            adjacency[destination].append(source)
        else:
            source, destination = sorted((link["fromNode"], link["toNode"]))
            adjacency[source].append(destination)

    with nodes_file.open(encoding="utf-8") as stream:
        raw_nodes = json.load(stream)["nodes"]
    node_records = raw_nodes.items() if args.topology == "T1" else ((None, node) for node in raw_nodes)
    destinations = []
    for key, node in node_records:
        if node["RU"]:
            cr_id = int(key.split("-", 1)[1]) if args.topology == "T1" else node["nodeNumber"]
            destinations.append(cr_id)
    return adjacency, destinations


def find_paths(adjacency, source, destination, limit):
    found = []

    def visit(node, visited, current):
        if len(found) >= limit:
            return
        if node == destination:
            # Preserve the original PlaceRAN rule: a candidate cannot traverse
            # both aggregation CRs 1 and 2 on the same longer physical route.
            if not (len(current) > 3 and 1 in current and 2 in current):
                found.append(current.copy())
            return
        for neighbor in adjacency[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                current.append(neighbor)
                visit(neighbor, visited, current)
                current.pop()
                visited.remove(neighbor)

    visit(source, {source}, [source])
    return found


def edge_strings(path):
    return [f"({path[index]}, {path[index + 1]})" for index in range(len(path) - 1)]


def generate_configurations(physical_paths):
    configurations = []
    seen = set()

    def add(target, seq, p1, p2, p3):
        signature = (tuple(p1), tuple(p2), tuple(p3))
        if signature in seen:
            return
        seen.add(signature)
        configurations.append(
            {
                "id": len(configurations) + 1,
                "source": "CN",
                "target": target,
                "seq": list(seq),
                "p1": p1,
                "p2": p2,
                "p3": p3,
            }
        )

    for path in physical_paths:
        edges = edge_strings(path)
        target = path[-1]
        for du_index in range(2, len(path) - 1):
            add(target, (path[1], path[du_index], target), edges[:1], edges[1:du_index], edges[du_index:])
        for du_index in range(1, len(path) - 1):
            add(target, (0, path[du_index], target), [], edges[:du_index], edges[du_index:])
        add(target, (0, 0, target), [], [], edges)
    return configurations


def main():
    args = parse_args()
    adjacency, destinations = load_graph(args)
    physical_paths = []
    for destination in destinations:
        physical_paths.extend(find_paths(adjacency, 0, destination, args.k_paths))
    configurations = generate_configurations(physical_paths)
    args.paths_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"paths": {f"path-{path['id']}": path for path in configurations}}
    with args.paths_file.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
    print(f"Scenario         : {args.scenario}")
    print(f"Topology directory: {args.topology_dir}")
    print(f"Physical paths    : {len(physical_paths)} (maximum {args.k_paths} per RU node)")
    print(f"Path configurations: {len(configurations)}")
    print(f"Paths file        : {args.paths_file}")


if __name__ == "__main__":
    main()
