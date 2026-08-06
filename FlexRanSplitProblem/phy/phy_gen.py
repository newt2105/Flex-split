# phy/phy_gen.py
import pickle
import argparse
from pathlib import Path

from .genphy import load_phy_T1, load_phy_T2


def main():
    parser = argparse.ArgumentParser("Generate physical RAN topology")
    parser.add_argument("--topo", choices=["T1", "T2"], default="T2")
    parser.add_argument("--links", required=True)
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--out", default="phy.pkl")

    args = parser.parse_args()

    if args.topo == "T1":
        PHY = load_phy_T1(args.links, args.nodes)
    else:
        PHY = load_phy_T2(args.links, args.nodes)

    out_path = Path(args.out)
    with out_path.open("wb") as f:
        pickle.dump(PHY, f)

    print("✅ PHY graph generated")
    print(f"   Nodes : {PHY.number_of_nodes()}")
    print(f"   Edges : {PHY.number_of_edges()}")
    print(f"   Saved : {out_path.resolve()}")


if __name__ == "__main__":
    main()
