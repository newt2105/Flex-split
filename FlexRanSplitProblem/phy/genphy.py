import json
import networkx as nx



def load_phy_T1(links_json: str, nodes_json: str) -> nx.DiGraph:
    PHY = nx.DiGraph()

    # ---- Links ----
    with open(links_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    for _, link in data["links"].items():
        src = _parse_T1_node(link["source"]["node"])
        dst = _parse_T1_node(link["destination"]["node"])

        bw = float(link["linkCapacity"])
        d = float(str(link["LinkDelay"]).replace(",", "."))

        # legacy code: add BOTH directions
        PHY.add_edge(src, dst, capacity=bw, delay=d)
        PHY.add_edge(dst, src, capacity=bw, delay=d)

    # ---- Nodes (CRs) ----
    with open(nodes_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data["nodes"]:
        cr_id = int(str(item).rsplit("-", 1)[1])
        cpu = float(data["nodes"][item]["CPU"])
        PHY.add_node(cr_id, cpu=cpu)

    # Core CN = 0
    PHY.add_node(0, cpu=0.0)

    return PHY


def _parse_T1_node(x) -> int:
    if x == "CN":
        return 0
    return int(str(x).rsplit("N", 1)[1])


# ---------------------------
# T2: topology nhỏ (int ids)
# ---------------------------
def load_phy_T2(links_json: str, nodes_json: str) -> nx.DiGraph:
    PHY = nx.DiGraph()

    # ---- Links ----
    with open(links_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    for link in data["links"]:
        u = int(link["fromNode"])
        v = int(link["toNode"])
        bw = float(link["capacity"])
        d = float(link["delay"])

        # legacy logic: undirected stored as min/max
        PHY.add_edge(u, v, capacity=bw, delay=d)
        PHY.add_edge(v, u, capacity=bw, delay=d)

    # ---- Nodes ----
    with open(nodes_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    for node in data["nodes"]:
        i = int(node["nodeNumber"])
        cpu = float(node["cpu"])
        PHY.add_node(i, cpu=cpu)

    PHY.add_node(0, cpu=0.0)

    return PHY
