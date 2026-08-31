from collections import defaultdict
import argparse
import json
import ast

from placeran_settings import add_settings_arguments, resolve_settings


def parse_args():
    parser = argparse.ArgumentParser(description="Generate PlaceRAN paths")
    add_settings_arguments(parser)
    # run_model_pulp.py forwards model options too; path generation only needs
    # to consume the shared settings and deliberately ignores the rest.
    parsed = parser.parse_known_args()[0]
    settings = resolve_settings(parsed)
    for key, value in settings.items():
        setattr(parsed, key, value)
    return parsed


args = parse_args()
network_size = int(args.network.rsplit("-", 1)[1])
links_file = args.topology_dir / f"{network_size}_CRs_links_LC.json"
nodes_file = args.topology_dir / f"F1_{network_size}_CRs_nodes_LC.json"
print("Topology directory:", args.topology_dir)

paths = []
k = 0
k_stop = args.k_paths


class Graph:
    def __init__(self, vertices):
        self.V = vertices
        self.graph = defaultdict(list)

    def addEdge(self, u, v):
        self.graph[u].append(v)

    def printAllPathsUtil(self, u, d, visited, path):
        visited[u] = True
        path.append(u)
        if u == d:
            if len(path) > 3 and 1 in path and 2 in path:
                pass
            else:
                global k
                k += 1
                if k < k_stop + 1:
                    p = str(path)
                    p = ast.literal_eval(p)
                    paths.append(p)
        else:
            for i in self.graph[u]:
                if visited[i] == False:
                    self.printAllPathsUtil(i, d, visited, path)
        path.pop()
        visited[u] = False

    def printAllPaths(self, s, d):
        visited = [False] * (self.V)
        path = []
        self.printAllPathsUtil(s, d, visited, path)


with open(links_file) as json_file:
    data = json.load(json_file)
    g = Graph(600)
    json_links = data["links"]
    for item in json_links:
        link = item
        source_node = link["fromNode"]
        destination_node = link["toNode"]
        if source_node < destination_node:
            g.addEdge(source_node, destination_node)
            # ADD THIS CODE FOR T1 TOPOLOGY
            # g.addEdge(destination_node, source_node)
        else:
            g.addEdge(destination_node, source_node)
            # ADD THIS CODE FOR T1 TOPOLOGY
            # g.addEdge(source_node, destination_node)
    dst = []
    with open(nodes_file) as dst_file:
        json_dst = json.load(dst_file)
        nodes = json_dst["nodes"]
        for item in nodes:
            if item["RU"]:
                dst.append(item["nodeNumber"])
    for destination_node in dst:
        k = 0
        g.printAllPaths(0, destination_node)
with open('paths.json', 'w') as json_file:
    data = {}
    data["paths"] = {}
    path_data = {}
    seq = []
    count = 2
    id = 1
    for path in paths:
        for position in range(0, len(path) - 1):
            if position == count:
                seq.append(path[1])
                p1 = []
                edge = "({}, {})".format(str(path[0]), str(path[1]))
                p1.append(edge)
                seq.append(path[position])
                p2 = []
                for i in range(1, len(path) - 1):
                    if i != position:
                        edge = "({}, {})".format(str(path[i]), str(path[i + 1]))
                        p2.append(edge)
                    if i + 1 == position:
                        break
                seq.append(path[len(path) - 1])
                p3 = []
                for i in range(position, len(path) - 1):
                    if i != len(path) - 1:
                        edge = "({}, {})".format(str(path[i]), str(path[i + 1]))
                        p3.append(edge)
                    if i + 1 == position:
                        break
                count += 1
                p = {}
                p["id"] = id
                p["source"] = "CN"
                p["target"] = path[len(path) - 1]
                p["seq"] = seq
                p["p1"] = p1
                p["p2"] = p2
                p["p3"] = p3
                append = True
                if path_data:
                    for i in path_data:
                        p_i = path_data[i]
                        if p_i:
                            if p_i["p1"] == p["p1"] and p_i["p2"] == p["p2"] and p_i["p3"] == p["p3"] and p_i["id"] != \
                                    p["id"]:
                                append = False
                if append:
                    path_data["path-{}".format(str(id))] = p
                    id += 1
            seq = []
        count = 2
    count = 1
    for path in paths:
        for position in range(0, len(path) - 1):
            if position == count:
                seq.append(path[0])
                p1 = []
                seq.append(path[position])
                p2 = []
                for i in range(0, len(path) - 1):
                    if i != position:
                        edge = "({}, {})".format(str(path[i]), str(path[i + 1]))
                        p2.append(edge)
                    if i + 1 == position:
                        break
                seq.append(path[len(path) - 1])
                p3 = []
                for i in range(position, len(path) - 1):
                    if i != len(path) - 1:
                        edge = "({}, {})".format(str(path[i]), str(path[i + 1]))
                        p3.append(edge)
                    if i + 1 == position:
                        break
                count += 1
                p = {}
                p["id"] = id
                p["source"] = "CN"
                p["target"] = path[len(path) - 1]
                p["seq"] = seq
                p["p1"] = p1
                p["p2"] = p2
                p["p3"] = p3
                append = True
                if path_data:
                    for i in path_data:
                        p_i = path_data[i]
                        if p_i:
                            if p_i["p1"] == p["p1"] and p_i["p2"] == p["p2"] and p_i["p3"] == p["p3"]:
                                append = False
                if append:
                    path_data["path-{}".format(str(id))] = p
                    id += 1
            seq = []
        count = 1
    for path in paths:
        seq.append(0)
        p1 = []
        seq.append(0)
        p2 = []
        seq.append(path[len(path) - 1])
        p3 = []
        for i in range(0, len(path) - 1):
            if i != len(path) - 1:
                edge = "({}, {})".format(str(path[i]), str(path[i + 1]))
                p3.append(edge)
            if i + 1 == (len(path) - 1):
                break
        p = {}
        p["id"] = id
        p["source"] = "CN"
        p["target"] = path[len(path) - 1]
        p["seq"] = seq
        p["p1"] = p1
        p["p2"] = p2
        p["p3"] = p3
        p["p3"] = p3
        p["p3"] = p3
        append = True
        if path_data:
            for i in path_data:
                p_i = path_data[i]
                if p_i:
                    if p_i["p1"] == p["p1"] and p_i["p2"] == p["p2"] and p_i["p3"] == p["p3"] and p_i["id"] != p["id"]:
                        append = False
        if append:
            path_data["path-{}".format(str(id))] = p
            id += 1
        seq = []
    data["paths"] = path_data
    sum = 0
    for iten in path_data:
        sum += 1
    print(
        "{} paths configurations successfully found for {} (k_paths={})".format(
            sum, args.network, args.k_paths
        )
    )
    json.dump(data, json_file, indent=4)
