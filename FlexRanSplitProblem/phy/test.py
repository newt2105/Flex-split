# print_paths.py
import pickle


def main():
    with open("/home/stu1/Code/flexransplit/FlexRanSplitProblem/phy/paths.pkl", "rb") as f:
        paths = pickle.load(f)

    print(f"[OK] Loaded {len(paths)} paths\n")

    # In ra một vài path đầu để kiểm tra
    for p in paths[:107]:
        print(f"Path ID: {p.id}")
        print(f"  Nodes     : {p.nodes}")
        print(f"  BH edges  : {p.edges_BH}, delay = {p.delay_BH}")
        print(f"  MH edges  : {p.edges_MH}, delay = {p.delay_MH}")
        print(f"  FH edges  : {p.edges_FH}, delay = {p.delay_FH}")
        print("-" * 50)


if __name__ == "__main__":
    main()
