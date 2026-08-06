# phy/phy_print.py
import pickle
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser("Print physical RAN topology from pkl")
    parser.add_argument("--phy", required=True, help="Path to phy.pkl")
    parser.add_argument("--detail", action="store_true",
                        help="Print node/link attributes")
    args = parser.parse_args()

    phy_path = Path(args.phy)
    if not phy_path.exists():
        raise FileNotFoundError(f"{phy_path} not found")

    # -----------------------------
    # Load PHY
    # -----------------------------
    with phy_path.open("rb") as f:
        PHY = pickle.load(f)

    print("===== PHYSICAL NETWORK =====")
    print(f"Nodes: {PHY.number_of_nodes()}")
    print(f"Edges: {PHY.number_of_edges()}")
    print()

    # -----------------------------
    # Print nodes
    # -----------------------------
    print("----- Nodes -----")
    for n, attr in PHY.nodes(data=True):
        print(f"Node {n}")
        if args.detail:
            for k, v in attr.items():
                print(f"   {k}: {v}")

    print()

    # -----------------------------
    # Print edges
    # -----------------------------
    print("----- Links -----")
    for u, v, attr in PHY.edges(data=True):
        print(f"Link {u} -> {v}")
        if args.detail:
            for k, val in attr.items():
                print(f"   {k}: {val}")

    print("\n✅ Done.")


if __name__ == "__main__":
    main()
