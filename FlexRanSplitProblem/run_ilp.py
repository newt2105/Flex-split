# run_ilp.py
import pickle
import json
from pathlib import Path
from datetime import datetime

import pulp

from .common import FlexRanSplitProblem
from .lp_formulation import formulateLp, extract_solution
from .phy.ran_model import (
    DRC_structure_T2,
    build_rus_from_nodes_json_T2,
)

# =========================
# Paths / Topology config
# =========================
LINKS_JSON = "/home/stu1/Code/flexransplit/FlexRanSplitProblem/model_files/T2_files/8_CRs_links_LC.json"
NODES_JSON = "/home/stu1/Code/flexransplit/FlexRanSplitProblem/model_files/T2_files/F1_8_CRs_nodes_LC.json"
PATHS_PKL  = "/home/stu1/Code/flexransplit/FlexRanSplitProblem/phy/paths.pkl"
PHY_PKL    = "/home/stu1/Code/flexransplit/FlexRanSplitProblem/phy/phy.pkl"
CORE_ID = 0

# =========================
# Results directory
# =========================
RESULTS_DIR = Path("/home/stu1/Code/flexransplit/FlexRanSplitProblem/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def save_sol(lp: pulp.LpProblem, filepath: Path):
    """
    Save raw ILP solution in Gurobi-like .sol format
    """
    with open(filepath, "w") as f:
        f.write(f"# Solution for model {lp.name}\n")
        f.write(f"# Objective value = {pulp.value(lp.objective)}\n")
        for v in lp.variables():
            if v.varValue is not None and abs(v.varValue) > 1e-6:
                f.write(f"{v.name} {v.varValue}\n")


def main():
    print("[1] Building physical network...")
    with open(PHY_PKL, "rb") as f:
        PHY = pickle.load(f)

    print("[2] Loading paths...")
    with open(PATHS_PKL, "rb") as f:
        paths = pickle.load(f)
    print(f"    Loaded {len(paths)} paths")

    print("[3] Loading RUs...")
    rus = build_rus_from_nodes_json_T2(NODES_JSON)
    print(f"    Loaded {len(rus)} RUs")

    print("[4] Loading DRCs...")
    drcs = DRC_structure_T2()
    print(f"    Loaded {len(drcs)} DRCs")

    print("[5] Building FlexRanSplitProblem...")
    problem = FlexRanSplitProblem(
        physical_network=PHY,
        paths=paths,
        rus=rus,
        drcs=drcs,
        core_id=CORE_ID,
        name="FlexRAN_ILP_T2",
    )
    problem.sanity_check()

    print("[6] Formulating ILP...")
    lp = formulateLp(problem)

    print("[7] Solving ILP (Gurobi, silent)...")
    solver = pulp.GUROBI_CMD(msg=False)
    lp.solve(solver)

    status = pulp.LpStatus[lp.status]
    print(f"[8] Solver status: {status}")

    if status != "Optimal":
        print("[!] Warning: solution is not optimal")

    print("[9] Extracting semantic solution...")
    solution = extract_solution(problem, lp)

    # =========================
    # Save results
    # =========================
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- semantic solution (JSON)
    sol_json = RESULTS_DIR / f"solution_{ts}.json"
    with open(sol_json, "w") as f:
        json.dump(solution, f, indent=2)
    print(f"[10] Semantic solution saved to {sol_json}")

    # --- raw solver solution (.sol)
    sol_txt = RESULTS_DIR / f"solution_{ts}.sol"
    save_sol(lp, sol_txt)
    print(f"[11] Raw solver solution saved to {sol_txt}")

    # --- snapshot of full problem
    snapshot_file = RESULTS_DIR / f"problem_{ts}.pkl.gz"
    FlexRanSplitProblem.saveToFile(str(snapshot_file), problem)
    print(f"[12] Problem snapshot saved to {snapshot_file}")

    print("\n===== FINAL SOLUTION (SUMMARY) =====")
    for s in solution:
        print(s)


if __name__ == "__main__":
    main()
