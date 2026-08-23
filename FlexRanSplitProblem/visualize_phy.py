"""Draw the physical network and optionally highlight ILP paths/placements.

Examples (run from the repository parent)::

    python -m FlexRanSplitProblem.visualize_phy \
      --phy data/network_16/phy.pkl \
      --paths data/network_16/paths.pkl \
      --path-id 5 \
      --out results/network_16/path_5.png

    python -m FlexRanSplitProblem.visualize_phy \
      --phy data/network_16/phy.pkl \
      --paths data/network_16/paths.pkl \
      --solution results/network_16/solution_YYYYMMDD_HHMMSS.json \
      --slice 1 \
      --edge-labels \
      --out results/network_16/nsc_1.png
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.lines import Line2D


def load_pickle(path: str | Path) -> Any:
    with Path(path).open("rb") as stream:
        return pickle.load(stream)


def to_drawing_graph(physical_network: nx.Graph) -> nx.Graph:
    """Collapse symmetric directed arcs into one drawable physical link."""
    graph = nx.Graph()
    graph.add_nodes_from(physical_network.nodes(data=True))
    for source, target, attributes in physical_network.edges(data=True):
        if not graph.has_edge(source, target):
            graph.add_edge(source, target, **attributes)
    return graph


def layered_positions(graph: nx.Graph, core_id: int) -> Dict[Any, Tuple[float, float]]:
    """Place nodes by hop distance from the core for a RAN-like layout."""
    if core_id not in graph:
        raise ValueError(f"Core node {core_id} is not in the physical graph")

    distances = nx.single_source_shortest_path_length(graph, core_id)
    drawing_graph = graph.copy()
    unreachable_layer = max(distances.values(), default=0) + 1
    for node in drawing_graph.nodes:
        drawing_graph.nodes[node]["layer"] = distances.get(node, unreachable_layer)

    return nx.multipartite_layout(
        drawing_graph,
        subset_key="layer",
        align="vertical",
        scale=2.0,
    )


def find_path(paths: Iterable[Any], path_id: int) -> Any:
    for path in paths:
        if int(path.id) == int(path_id):
            return path
    raise KeyError(f"Path {path_id} was not found")


def load_solution(solution_path: str | Path) -> List[Dict[str, Any]]:
    with Path(solution_path).open("r", encoding="utf-8") as stream:
        payload = json.load(stream)

    slices = payload.get("slices", payload) if isinstance(payload, dict) else payload
    return list(slices)


def load_slice_solution(solution_path: str | Path, slice_id: int) -> Dict[str, Any]:
    for item in load_solution(solution_path):
        if int(item.get("slice", item.get("ru"))) == int(slice_id):
            return item
    raise KeyError(f"NSC/slice {slice_id} was not found in {solution_path}")


def edge_sequence(nodes: List[Any]) -> List[Tuple[Any, Any]]:
    return list(zip(nodes, nodes[1:]))


def draw_phy_and_paths(
    physical_network: nx.Graph,
    paths: Iterable[Any],
    path_ids: Iterable[int] = (),
    placement: Dict[str, Any] | None = None,
    core_id: int = 0,
    edge_labels: bool = False,
    output_path: str | Path = "results/phy-path.png",
    title: str | None = None,
) -> Path:
    """Render the PHY topology and selected paths to a PNG file."""
    graph = to_drawing_graph(physical_network)
    positions = layered_positions(graph, core_id)
    paths = list(paths)
    selected_paths = [find_path(paths, path_id) for path_id in path_ids]

    highlighted_nodes = {
        node
        for path in selected_paths
        for node in path.nodes
    }
    highlighted_edges = {
        frozenset(edge)
        for path in selected_paths
        for edge in edge_sequence(list(path.nodes))
    }
    ru_nodes = {path.nodes[-1] for path in paths if path.nodes}

    node_colors = []
    node_sizes = []
    for node in graph.nodes:
        if node == core_id:
            node_colors.append("#7c3aed")
            node_sizes.append(1050)
        elif node in highlighted_nodes:
            node_colors.append("#f59e0b")
            node_sizes.append(950)
        elif node in ru_nodes:
            node_colors.append("#16a34a")
            node_sizes.append(850)
        else:
            node_colors.append("#94a3b8")
            node_sizes.append(750)

    base_edges = [
        edge
        for edge in graph.edges
        if frozenset(edge) not in highlighted_edges
    ]
    selected_edges = [
        edge
        for edge in graph.edges
        if frozenset(edge) in highlighted_edges
    ]

    width = max(10.0, min(20.0, 0.75 * graph.number_of_nodes()))
    height = max(7.0, min(14.0, 0.55 * graph.number_of_nodes()))
    figure, axis = plt.subplots(figsize=(width, height), constrained_layout=True)

    nx.draw_networkx_edges(
        graph,
        positions,
        edgelist=base_edges,
        edge_color="#94a3b8",
        width=1.4,
        alpha=0.65,
        ax=axis,
    )
    nx.draw_networkx_edges(
        graph,
        positions,
        edgelist=selected_edges,
        edge_color="#dc2626",
        width=4.0,
        alpha=0.95,
        ax=axis,
    )
    nx.draw_networkx_nodes(
        graph,
        positions,
        node_color=node_colors,
        node_size=node_sizes,
        edgecolors="#ffffff",
        linewidths=1.5,
        ax=axis,
    )

    labels = {}
    placement_by_node: Dict[Any, List[str]] = {}
    for vnf, node in (placement or {}).items():
        placement_by_node.setdefault(node, []).append(vnf)
    for node in graph.nodes:
        suffix = ""
        if node == core_id:
            suffix = "\nCORE"
        elif node in placement_by_node:
            suffix = "\n" + ",".join(placement_by_node[node])
        elif node in ru_nodes:
            suffix = "\nRU"
        labels[node] = f"{node}{suffix}"

    nx.draw_networkx_labels(
        graph,
        positions,
        labels=labels,
        font_size=9,
        font_color="#0f172a",
        ax=axis,
    )

    if edge_labels:
        labels_by_edge = {}
        for source, target, attributes in graph.edges(data=True):
            capacity = attributes.get("capacity", attributes.get("cap", "?"))
            delay = attributes.get("delay", "?")
            labels_by_edge[(source, target)] = f"A={capacity}\nL={delay}"
        nx.draw_networkx_edge_labels(
            graph,
            positions,
            edge_labels=labels_by_edge,
            font_size=7,
            rotate=False,
            ax=axis,
        )

    legend = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#7c3aed", markeredgecolor="#ffffff", markersize=10, label="Core"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#16a34a", markeredgecolor="#ffffff", markersize=10, label="RU endpoint"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#f59e0b", markeredgecolor="#ffffff", markersize=10, label="Selected-path node"),
        Line2D([0], [0], color="#dc2626", linewidth=4, label="Selected path"),
    ]
    axis.legend(handles=legend, loc="best", frameon=False)
    axis.set_title(title or "Physical RAN topology and selected path", fontsize=14)
    axis.set_axis_off()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize PHY topology and ILP paths")
    parser.add_argument("--phy", required=True, type=Path)
    parser.add_argument("--paths", required=True, type=Path)
    parser.add_argument("--path-id", type=int, action="append", default=[])
    parser.add_argument("--solution", type=Path)
    parser.add_argument("--slice", dest="slice_id", type=int)
    parser.add_argument("--core", type=int, default=0)
    parser.add_argument("--edge-labels", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("results/phy-path.png"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.slice_id is not None and not args.solution:
        raise ValueError("--slice requires --solution")

    physical_network = load_pickle(args.phy)
    paths = load_pickle(args.paths)
    path_ids = list(args.path_id)
    placement = None
    title = None

    if args.solution and args.slice_id is not None:
        selected = load_slice_solution(args.solution, args.slice_id)
        path_ids.append(int(selected["path"]))
        placement = selected.get("vnf_placement", {})
        title = (
            f"NSC {args.slice_id}: DRC {selected['drc']}, "
            f"path {selected['path']}, latency {selected['latency']:.3f}"
        )
    elif args.solution:
        selected_slices = load_solution(args.solution)
        path_ids.extend(int(item["path"]) for item in selected_slices)
        title = f"Selected ILP paths for {len(selected_slices)} NSCs"

    output = draw_phy_and_paths(
        physical_network=physical_network,
        paths=paths,
        path_ids=path_ids,
        placement=placement,
        core_id=args.core,
        edge_labels=args.edge_labels,
        output_path=args.out,
        title=title,
    )
    print(f"Visualization saved to {output.resolve()}")


if __name__ == "__main__":
    main()
