import json
import networkx as nx
from dataclasses import dataclass
from typing import List, Tuple
from FlexRanSplitProblem.phy.path_model import Path

import pickle



# =========================
# Helpers
# =========================
def build_graph_from_links(links_json: str) -> nx.Graph:
    G = nx.Graph()
    with open(links_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    for link in data["links"]:
        u = int(link["fromNode"])
        v = int(link["toNode"])
        delay = float(link["delay"])
        G.add_edge(u, v, delay=delay)
    return G


def load_ru_nodes(nodes_json: str) -> List[int]:
    rus = []
    with open(nodes_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    for n in data["nodes"]:
        if int(n["RU"]) > 0:
            rus.append(int(n["nodeNumber"]))
    return rus


def path_delay(G: nx.Graph, edges: List[Tuple[int, int]]) -> float:
    return sum(G[u][v]["delay"] for (u, v) in edges)


def edges_from_nodes(nodes: List[int]) -> List[Tuple[int, int]]:
    return [(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]


# =========================
# Main path generation
# =========================
def generate_paths(
    links_json: str,
    nodes_json: str,
    core_id: int = 0,
    k_paths: int = 4,
) -> List[Path]:

    G = build_graph_from_links(links_json)
    ru_nodes = load_ru_nodes(nodes_json)

    paths: List[Path] = []
    pid = 1

    for ru in ru_nodes:
        # lấy k-shortest simple paths core -> RU
        simple_paths = nx.shortest_simple_paths(G, core_id, ru, weight="delay")

        for p_nodes in list(simple_paths)[:k_paths]:
            edges = edges_from_nodes(p_nodes)
            L = len(edges)

            # chọn CU và DU position (đúng bài: nằm trên path)
            for cu_pos in range(0, L):
                for du_pos in range(cu_pos, L):
                    edges_BH = edges[:cu_pos]
                    edges_MH = edges[cu_pos:du_pos]
                    edges_FH = edges[du_pos:]

                    d_bh = path_delay(G, edges_BH)
                    d_mh = path_delay(G, edges_MH)
                    d_fh = path_delay(G, edges_FH)

                    paths.append(
                        Path(
                            id=pid,
                            nodes=p_nodes,
                            edges_BH=edges_BH,
                            edges_MH=edges_MH,
                            edges_FH=edges_FH,
                            delay_BH=d_bh,
                            delay_MH=d_mh,
                            delay_FH=d_fh,
                        )
                    )
                    pid += 1

    print(f"{len(paths)} valid path configurations generated")
    with open("/home/stu1/Code/flexransplit/FlexRanSplitProblem/phy/paths.pkl", "wb") as f:
        pickle.dump(paths, f)
        
    return paths


# =========================
# Standalone run (optional)
# =========================
if __name__ == "__main__":
    paths = generate_paths(
        links_json="/home/stu1/Code/flexransplit/FlexRanSplitProblem/model_files/T2_files/8_CRs_links_LC.json",
        nodes_json="/home/stu1/Code/flexransplit/FlexRanSplitProblem/model_files/T2_files/F1_8_CRs_nodes_LC.json",
        core_id=0,
        k_paths=4,
    )

    # optional: save as pickle / json if needed
