
from __future__ import annotations

import pulp
from typing import Any, Dict, List

from .common import FlexRanSplitProblem
from .helper import (
    node_cpu_cap,
    edge_bw_cap,
    seg_edges,
    seg_delay,
    path_latency,
    end_node_of_seg,
)

BETA = 0.9999     # ưu tiên accept
BIG_M = 10**6     # dùng cho delay gating (an toàn)


def formulateLp(problem: FlexRanSplitProblem) -> pulp.LpProblem:
    PHY = problem.PHY
    core_id = getattr(problem, "core", 0)

    # Sets
    S = problem.flow_set               # RU ids (sb)
    K = problem.Ks                     # DRC ids
    P = [p.id for p in problem.paths]  # path ids
    P_by_id: Dict[Any, Any] = {p.id: p for p in problem.paths}

    lp = pulp.LpProblem(
        name=getattr(problem, "name", "FlexRanSplit_ILP"),
        sense=pulp.LpMinimize
    )
    lp.constraints.clear()

    # -----------------------------
    # Variables
    # -----------------------------
    # admission adm[b] ∈ {0,1}
    adm = pulp.LpVariable.dicts("adm", S, cat=pulp.LpBinary)

    # DRC selection pi[b,k] ∈ {0,1}
    pi = {b: pulp.LpVariable.dicts(f"pi_{b}", K, cat=pulp.LpBinary) for b in S}

    # path selection theta[b,k,p] ∈ {0,1}
    # theta[b,k,p] = 1 iff path p is selected for RU b using DRC k.
    theta = pulp.LpVariable.dicts(
        "theta",
        (S, K, P),
        cat=pulp.LpBinary,
    )

    # -----------------------------
    # C1: chọn đúng 1 DRC hoặc reject
    # sum_k pi[b,k] = adm[b]
    # -----------------------------
    for b in S:
        lp += (pulp.lpSum(pi[b][k] for k in K) == adm[b], f"C1_drc_{b}")

    # -----------------------------
    # C2: chọn đúng 1 cặp DRC/path
    # sum_k sum_p theta[b,k,p] = 1
    # -----------------------------
    for b in S:
        lp += (
            pulp.lpSum(theta[b][k][pid] for k in K for pid in P) == 1,
            f"C2_path_{b}",
        )

    # -----------------------------
    # C3: DRC/path consistency
    # A path can only be selected under the DRC selected by pi.
    # -----------------------------
    for b in S:
        for k in K:
            lp += (
                pulp.lpSum(theta[b][k][pid] for pid in P) == pi[b][k],
                f"C3_drc_path_{b}_{k}",
            )

    # -----------------------------
    # C4: Delay constraints for BH/MH/FH (gated by theta)
    # seg_delay(path, seg) <= delay_req(b,k,seg) + M*(1-theta)
    # -----------------------------
    for b in S:
        for k in K:
            for pid in P:
                p = P_by_id[pid]
                for seg in ("BH", "MH", "FH"):
                    lp += (
                        seg_delay(p, seg) <= problem.delay_req(b, k, seg) + BIG_M * (1 - theta[b][k][pid]),
                        f"C4_delay_{seg}_{b}_{k}_{pid}"
                    )

    # -----------------------------
    # C5: Node CPU capacity
    # CU node = end(BH), DU node = end(MH), RU node fixed
    # Sum CPU load on node i <= cap(i)
    # -----------------------------
    for i in PHY.nodes:
        i = int(i)
        expr = []

        cap_i = node_cpu_cap(PHY, i)

        for b in S:
            ru_node = int(problem.ru_location(b))
            for k in K:
                cpu_cu = problem.node_req(b, k, "vcu")
                cpu_du = problem.node_req(b, k, "vdu")
                cpu_ru = problem.node_req(b, k, "vru")

                for pid in P:
                    p = P_by_id[pid]
                    cu_node = end_node_of_seg(p, "BH", core_id, ru_node)
                    du_node = end_node_of_seg(p, "MH", core_id, ru_node)

                    if i == cu_node and cpu_cu != 0:
                        expr.append(cpu_cu * theta[b][k][pid])
                    if i == du_node and cpu_du != 0:
                        expr.append(cpu_du * theta[b][k][pid])
                    if i == ru_node and cpu_ru != 0:
                        expr.append(cpu_ru * theta[b][k][pid])

        lp += (pulp.lpSum(expr) <= cap_i, f"C5_cpu_{i}")

    # -----------------------------
    # C6: Link bandwidth capacity
    # If edge e is used in segment seg of path p -> consume bw_req(b,k,seg)
    # Sum BW on edge e <= cap(e)
    # -----------------------------
    for e in PHY.edges:
        e = (int(e[0]), int(e[1]))
        cap_e = edge_bw_cap(PHY, e)
        expr = []

        for b in S:
            for k in K:
                bw_bh = problem.link_req(b, k, "BH")
                bw_mh = problem.link_req(b, k, "MH")
                bw_fh = problem.link_req(b, k, "FH")

                for pid in P:
                    p = P_by_id[pid]
                    if e in seg_edges(p, "BH") and bw_bh != 0:
                        expr.append(bw_bh * theta[b][k][pid])
                    if e in seg_edges(p, "MH") and bw_mh != 0:
                        expr.append(bw_mh * theta[b][k][pid])
                    if e in seg_edges(p, "FH") and bw_fh != 0:
                        expr.append(bw_fh * theta[b][k][pid])

        lp += (pulp.lpSum(expr) <= cap_e, f"C6_bw_{e[0]}_{e[1]}")

    # -----------------------------
    # Objective: minimize  -BETA*sum(adm) + (1-BETA)*sum(theta * latency(path))
    # (minimize form)
    # -----------------------------
    lp += (
        -BETA * pulp.lpSum(adm[b] for b in S)
        + (1 - BETA) * pulp.lpSum(
            theta[b][k][pid] * path_latency(P_by_id[pid])
            for b in S
            for k in K
            for pid in P
        ),
        "OBJ"
    )

    # attach vars for debug/extract
    lp._vars = {"adm": adm, "pi": pi, "theta": theta}
    return lp


def extract_solution(problem: FlexRanSplitProblem, lp: pulp.LpProblem):
    """
    Return list of dict:
      {ru, admitted, drc, path}
    """
    vars_ = getattr(lp, "_vars", None)
    if vars_ is None:
        raise ValueError("LP has no attached vars. Build with formulateLp().")

    adm = vars_["adm"]
    theta = vars_["theta"]

    P = [p.id for p in problem.paths]

    out = []
    for b in problem.flow_set:
        admitted = (pulp.value(adm[b]) or 0) > 0.5
        if not admitted:
            out.append({"ru": b, "admitted": 0, "drc": None, "path": None})
            continue

        chosen_k, chosen_p = None, None
        for k in problem.Ks:
            for pid in P:
                if (pulp.value(theta[b][k][pid]) or 0) > 0.5:
                    chosen_k, chosen_p = k, pid
                    break
            if chosen_k is not None:
                break

        out.append({"ru": b, "admitted": 1, "drc": chosen_k, "path": chosen_p})
    return out
