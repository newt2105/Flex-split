
# PlaceRAN: optimal placement of virtualized network functions in Beyond 5G radio access networks

This repository aims to demonstrate the **PlaceRAN: optimal placement of virtualized network functions in Beyond 5G radio access networks** model implementation.  In our tests we used the Ubuntu Server 18.04 and Ubuntu 20.04, with Python 3.6.9, docplex 2.20.204 and the IBM CPLEX version 12.8.0.

- [Description](#description)
- [Topologies](#topologies)
- [Scenarios](#scenarios)
- [Running with PuLP/CBC](#running-with-pulpcbc)
- [Final Results](#final-results)
- [Citation](#citation)

## Description
This work proposes the first exact model for positioning radio functions for vNGRAN planning, named **PlaceRAN**, as a *Binary Integer Linear Programming (BILP)* problem. The objective is to minimize the computing resources and maximize the aggregation level of radio functions. The evaluation considered two realistic network topologies, named as T1 and T2. 

This repository contains more informations about our model, the T1 and T2 topologies, the scenarios and about our final results.

## Topologies
In our evaluation we used two topologies, named Topology 1 (T1) and Topology 2 (T2) to compare the different topology scenarios (Low Quality, Random Quality and High Quality) and RUs scenarios (F1 and R1). 

T1 topology represents a current ring based RAN deployment, with two CRs positioned close to the core network, in a centralized way, and the others 49 CRs are distributed as a ring based cluster. 

The T2 topology is a hierarchical topology, that are organized in layers, this kind of topologies shows a trend in the design of the future RAN topologies, being aligned with the most recent analysis. T2 topology has two CRs positioned close to the core network, in a centralized way, and the others 126 CRs are distributed in hierarchical layers.


<p align="center">
  <img src="https://github.com/LABORA-INF-UFG/paper-FGLKLRC-2021/blob/main/topo_fig.png"/>
</p>

## Scenarios

To evaluate our goals with different scenarios of topologies and radio distribution, we defined three types of topology scenarios named as High Capacity (HC), Random Capacity (RC) and Low Capacity (LC). The HC scenario have high quality links with higher bandwidth and lower latency values. The LC scenario is the opposite, links with lower bandwidth and higher latency values. Finally, the RC scenario is the middle ground between the HC and LC scenarios, with links having higher and lower bandwidth and latency values.

We also define different scenarios to the Radio Units (RUs) distribution named as Fixed 1 (F1) and Random 1 (R1). In the F1 scenario, each CR has a RU coupled to it. In the R1 scenario, we define the RU distribution randomly, where each CR can have one RU coupled to it or none.

## Running with PuLP/CBC

The original three-stage PlaceRAN formulation can be solved with PuLP and the
open-source CBC backend. All standard experiments are controlled by one file:
`settings/experiments.ini`.

```ini
# settings/experiments.ini
[experiments]
cases =
    T1-R1-LC
    T1-R1-RC
    T1-R1-HC
    T1-F1-LC
    T1-F1-RC
    T1-F1-HC
    T2-R1-LC
    T2-R1-RC
    T2-R1-HC
    T2-F1-LC
    T2-F1-RC
    T2-F1-HC
k_paths = 10
solver = cbc
solver_log = false
time_limit =
stop_on_error = true
results_root = results_pulp
```

On Windows PowerShell, run:

```powershell
cd D:\Code\flexransplit\PlaceRAN
py -m pip install -r requirements-pulp.txt
py .\run_experiments_pulp.py
```

The cases are executed in the order in which they appear in the INI file.
Comment out a case with `#` to skip it. Each scenario writes its own
`solution.csv` and timestamped JSON file under
`results_pulp/<CASE>/k_paths_<K>/`. A batch summary is written to
`results_pulp/run_summary.csv`.

To run only one scenario without editing the batch settings:

```powershell
py .\run_model_pulp.py --case T1-R1-LC --k-paths 10 --solver cbc
```

The low-level runner also supports generated T2 sizes for backward
compatibility:

```powershell
py .\run_model_pulp.py --case T2-F1-LC --network t2-16 --k-paths 10 `
  --topology-dir ..\FlexRanSplitProblem\data_heterogeneous\network_16\placeran `
  --results results_pulp_heterogeneous\t2-16\k_paths_10
```

Use Gurobi through either its Python API or command-line backend:

```powershell
py .\run_model_pulp.py --case T2-F1-LC --solver gurobi --solver-log
```

### Run one network from `settings/network.txt`

Edit only `settings/network.txt`, for example:

```ini
[network]
name = t2-8
ru_distribution = F1
resource_level = LC
k_paths = 2
solver = gurobi
```

Then run:

```powershell
py .\run_model_pulp.py
```

Supported network names are `t1-51`, `t2-8`, `t2-16`, `t2-32`, `t2-64`,
`t2-128`, and `t2-256`. Results are separated by network size, for example
`results_pulp/T2-F1-LC-8/k_paths_2`.

`--solver auto` prefers Gurobi when available and otherwise uses CBC.
Use `solver_log = true` to display the solver log. The final RU/path/DRC
placement is printed to the terminal.

The primary `solution.csv` uses the same schema as FlexRanSplitProblem:

```csv
NSC,DRC,path,L,placement,runtime
1,10,5,1.330,"{'vupf': 0, 'vcu': 1, 'vdu': 4, 'vru': 3}",0.649
```

`L` is total path latency and `runtime` is the sum of CBC solve time over the
three PlaceRAN stages. If a T2 topology has fewer than `k_paths` distinct
physical routes to an RU, the generator keeps all available routes without
creating duplicates.

## Final results

To see the final results, i. e., the optimal solutions of each topology and/or the improvements of each scenario, we provide a set of charts that can be used to compare the improvements of our approach. The topology files, scenarios and the model implementation are in this repository.

## Citation

```
@ARTICLE{morais-placeran:22,  
    author={Morais, Fernando Zanferrari and De Almeida, Gabriel Matheus Faria and Pinto, Leizer Lima and Cardoso, Kleber and Contreras, Luis M. and Righi, Rodrigo da Rosa and Both, Cristiano Bonato},
    journal={IEEE Transactions on Mobile Computing},   
    title={PlaceRAN: optimal placement of virtualized network functions in Beyond 5G radio access networks},   
    year={2022},  
    volume={},  
    number={},  
    pages={1-1},  
    doi={10.1109/TMC.2022.3171525}
}
```
