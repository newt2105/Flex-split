# Flex-split formulation, implementation, and physical-resource tuning

## 1. Scope and invariants

The HET experiment does **not** change any DRC/VNF requirement, objective,
solver constraint, topology edge, RU placement, or link delay.  The original
PlaceRAN JSON files remain untouched.  Tuned copies are generated under
`model_files/T2_tuned_files/`.

The implementation has nine DRCs, with IDs `1, 2, 4, 5, 6, 7, 8, 9, 10`.
The draft paper says twelve standardized combinations, but the current solver
uses exactly the nine objects returned by `DRC_structure_T2()`.

## 2. Exact DRC requirements from `phy/ran_model.py`

CPU and delay values are identical in the T1 and T2 builders.  Bandwidth
values differ by topology family.

| DRC | CU CPU | DU CPU | RU CPU | Delay BH/MH/FH | BW T1 BH/MH/FH | BW T2 BH/MH/FH |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.49 | 2.058 | 2.352 | 10 / 10 / 0.25 | 3 / 5.4 / 17.4 | 9.9 / 13.2 / 42.6 |
| 2 | 0.98 | 1.568 | 2.352 | 10 / 10 / 0.25 | 3 / 5.4 / 17.4 | 9.9 / 13.2 / 42.6 |
| 4 | 0.49 | 1.225 | 3.185 | 10 / 10 / 0.25 | 3 / 5.4 / 5.6 | 9.9 / 13.2 / 13.6 |
| 5 | 0.98 | 0.735 | 3.185 | 10 / 10 / 0.25 | 3 / 5.4 / 5.6 | 9.9 / 13.2 / 13.6 |
| 6 | 0 | 0.49 | 4.41 | 0 / 10 / 10 | 0 / 3 / 5.4 | 0 / 9.9 / 13.2 |
| 7 | 0 | 3 | 3.92 | 0 / 10 / 10 | 0 / 3 / 5.4 | 0 / 9.9 / 13.2 |
| 8 | 0 | 0 | 4.9 | 0 / 0 / 10 | 0 / 0 / 3 | 0 / 0 / 9.9 |
| 9 | 0 | 2.54 | 2.354 | 0 / 10 / 0.25 | 0 / 3 / 17.4 | 0 / 9.9 / 42.6 |
| 10 | 0 | 1.71 | 3.185 | 0 / 10 / 0.25 | 0 / 3 / 5.6 | 0 / 3 / 13.6 |

The proposed values in the task are therefore confirmed for T2: DRC5/10 use
RU CPU 3.185 and FH 13.6; DRC8 uses RU CPU 4.9 and FH 9.9.

## 3. Paper-to-code trace

| Paper | Implementation |
|---|---|
| Physical graph `G=(N,E)` | `FlexRanSplitProblem.PHY`, `N`, and `E` |
| One NSC per RU | `S`, built by `build_rus_from_nodes_json_T2()` |
| Candidate paths `P_s` | `paths_for_slice(s)`; duplicate node sequences are removed |
| DRC selection `pi[s,k]` | binary `pi` |
| Used DRC `pi_tilde[k]` | binary `pi_tilde` with a logical-OR linearization |
| DRC/path selection `y[s,k,p]` | binary `y` |
| VNF placement | binary `x_node[s,k,p,i,v]` |
| Virtual-link mapping | binary `x_link[s,k,p,i,j,v,w]` |
| C1 DRC selection | exactly one `pi` per NSC |
| C2 path selection | exactly one `(k,p)` per NSC |
| Missing draft link | code adds C2b, `sum_p y[s,k,p] == pi[s,k]` |
| C3 endpoints | UPF fixed at core, RU VNF fixed at its RU-bearing CR |
| C4/C5 placement | every VNF uses one distinct physical node on the path |
| C6 capacities | aggregated node CPU and directed-link bandwidth |
| C7/C8 flow | ordered flow conservation and inactive-path suppression |
| Objective | `beta * used_DRC_count + (1-beta) * total_latency/max_path_latency` |

Important implementation consequences:

1. C5 applies even when CU or DU CPU is zero.  A selected path therefore needs
   at least four distinct physical nodes for UPF, CU, DU, and RU.  Some of the
   shortest three-node paths generated in `paths.pkl` are structurally
   infeasible and the solver must choose a longer candidate.
2. DRC BH/MH/FH delay limits are stored in the model but are **not** enforced
   by `lp_formulation.py`.  Link delays affect only total path latency in the
   objective.
3. The latency denominator is the maximum latency of one candidate path, not
   the sum over NSCs.  Consequently, the normalized latency sum can approach
   `|S|`; it is not generally in `[0,1]` as claimed by the draft.
4. T2 JSON links are loaded in both directions into a `DiGraph`.  Capacity is
   enforced independently per direction.

## 4. Physical network data

All T1/T2 JSON files in Flex-split are byte-for-byte identical to the matching
PlaceRAN files before HET generation.

T1 LC has 51 CR nodes and 63 undirected JSON links.  F1 places 49 RUs and R1
places 39.  LC CPU capacities are 16 on four CRs and 8 on 47 CRs; LC link
capacities are 10, 25, and 100, with delays from 0.4 to 0.9073.  HC and RC keep
the same topology but use their own CPU, bandwidth, delay, RAM, and RU profiles.

The T2 LC instances have the following structure.  Layer counts include the
core at hop zero.

| Network | RU/NSC | Hop-layer node counts | RU CPU distribution | Link capacity distribution |
|---:|---:|---|---|---|
| 8 | 6 | 1 / 2 / 3 / 3 | 3x16, 3x8 | 2x100, 6x50, 6x25 |
| 16 | 14 | 1 / 2 / 5 / 9 | 5x16, 9x8 | 2x100, 10x50, 18x25 |
| 32 | 30 | 1 / 2 / 6 / 24 | 6x16, 24x8 | 2x800, 12x100, 49x50 |
| 64 | 62 | 1 / 2 / 8 / 54 | 8x16, 54x8 | 2x800, 16x100, 109x50 |
| 128 | 126 | 1 / 2 / 20 / 76 / 15 / 15 | 20x16, 106x8 | 2x800, 40x100, 152x50, 30x40 |
| 256 | 254 | 1 / 2 / 20 / 200 / 21 / 13 | 20x16, 234x8 | 2x2000, 248x100, 226x50 |

## 5. Why the observed DRC IDs appear

The objective has no term that prefers one DRC ID over another when both use
one distinct DRC and achieve the same latency.  Re-evaluating every existing
Flex-split path and placement with all nine T2 profiles gives these
same-routing alternative optima:

| Network | Recorded DRC | Other DRCs feasible on the identical paths/placements |
|---:|---:|---|
| 8 | 5 | 4, 5, 6, 7, 8, 10 |
| 16 | 10 | 6, 7, 8, 10 |
| 32 | 8 | 6, 8 |
| 64 | 8 | 8 |
| 128 | 8 | 6, 8 |
| 256 | 8 | 8 |

Thus the IDs for networks 8, 16, 32, and 128 are not uniquely identified by
the objective; solver tie-breaking selects one of several equal optima.  For
network 8, a full placement search also confirms that each of DRC4, 5, 6, 7,
8, and 10 is a universal DRC.  DRC1, 2, and 9 fail at outer access links
because FH 42.6 exceeds capacity 25.

At 64 and 256, DRC8 is attractive because it consumes no CU/DU CPU and no
BH/MH bandwidth.  On the recorded minimum-latency routes, alternatives hit
shared resources: at 64, DRC6 would load link `1->3` by 138.6 over capacity
100 and DRC10 would load CR3 by 27.125 over capacity 16; at 256, the analogous
bottlenecks are link `1->19` at 198 over 100 and CR19 at 32.255 over 16.

## 6. HET tuning rule and proof

For each network, the generator chooses:

* profile A: the lowest-ID RU-bearing CR exactly two hops from the core;
* profile B: the lowest-ID RU-bearing CR more than two hops from the core.

| Network | Profile A CR | Profile B CR |
|---:|---:|---:|
| 8 | 3 | 6 |
| 16 | 3 | 8 |
| 32 | 3 | 9 |
| 64 | 3 | 11 |
| 128 | 3 | 23 |
| 256 | 3 | 23 |

Profile A receives CPU 3.4 and capacity 15 on every incident link.  From the
actual DRC table, its endpoint-feasible set is exactly `{4,5,10}`.  Profile B
receives CPU 5.2 and capacity 10.5 on every incident link; its endpoint-feasible
set is exactly `{8}`.  Because these sets are disjoint, no single DRC can cover
all regions.  This conclusion considers all nine implemented DRCs.

A constructive placement was checked against the existing ten candidate paths
per RU for every network: DRC10 serves profile A and DRC8 serves all other
RUs.  Every instance 8 through 256 is feasible.  The maximum observed resource
ratios in this witness are `4.9/5.2 = 0.9423` at profile B CPU and
`9.9/10.5 = 0.9429` at profile B access bandwidth.

## 7. Artifact pipeline and commands

`load_phy_T2()` copies node `cpu` and link `capacity`/`delay` into `phy.pkl`.
`generate_paths()` uses only topology and delay to produce up to ten
latency-shortest paths per RU; it does not use CPU or bandwidth.  HET therefore
has the same candidate node sequences as LC, but a fresh `phy.pkl` is required.

Generate and solve as follows from the repository root:

```powershell
python FlexRanSplitProblem/tune_physical_resources.py
python -m FlexRanSplitProblem.generate_all_networks --settings FlexRanSplitProblem/settings/path_gen_heterogeneous.txt
python -m FlexRanSplitProblem.run_ilp --settings FlexRanSplitProblem/settings/ilp_heterogeneous.txt
```

`overwrite = true` in the HET path-generation settings is intentional.  The
baseline settings use `overwrite = false`, which would otherwise keep stale LC
capacities in an existing `phy.pkl`.

