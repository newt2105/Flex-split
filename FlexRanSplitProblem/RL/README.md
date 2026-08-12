# Flexible RAN Split RL

This package models the static Flexible RAN Split problem as one finite RL
episode. At step `t`, the environment handles one RU. Action `0` rejects it;
every other fixed action selects one `(DRC, path)` pair.

Invalid pairs receive probability zero through an action mask. A pair is invalid
when its path ends at another RU node, violates a segment delay, or exceeds the
currently available CPU/bandwidth.

## Files

- `catalog.py`: fixed action ids and precomputed resource demands.
- `environment.py`: state, transitions, reward, and dynamic action masks.
- `model.py`: masked actor-critic MLP.
- `rollout.py`: PPO rollout buffer and GAE.
- `ppo_agent.py`: training, inference, and checkpoints.
- `train.py`: training CLI.
- `evaluate.py`: evaluation CLI.
- `tests/`: environment and return-calculation tests.

## State, action, and reward

The flat state is:

```text
[progress, current-RU-node one-hot, remaining CPU ratios, remaining BW ratios]
```

The action dimension is fixed for one problem:

```text
1 + number_of_DRCs * number_of_paths
```

The default reward is `+1` for admission and `0` for rejection, so episode
return equals the admitted-RU count. `--latency-weight` optionally adds a small
normalized latency tie-breaker.

## Install

From the repository root (the directory containing `FlexRanSplitProblem`):

```powershell
python -m pip install -r FlexRanSplitProblem/RL/requirements.txt
```

## Train

```powershell
python -m FlexRanSplitProblem.RL.train `
  --problem FlexRanSplitProblem/results/problem_20260125_224620.pkl.gz `
  --timesteps 100000
```

Useful options include `--shuffle-rus`, `--latency-weight 0.01`, `--device cuda`,
and `--output path/to/checkpoint.pt`.

## Evaluate

```powershell
python -m FlexRanSplitProblem.RL.evaluate `
  --problem FlexRanSplitProblem/results/problem_20260125_224620.pkl.gz `
  --checkpoint FlexRanSplitProblem/RL/checkpoints/masked_ppo.pt `
  --json-output FlexRanSplitProblem/results/rl_solution.json
```

The checkpoint is tied to the exact node/edge/DRC/path ordering of the training
problem. A different topology with different dimensions needs a newly trained
model. Padding or a candidate-scoring/GNN policy is a later extension for a
single model that generalizes across topology sizes.

## Test

From inside `FlexRanSplitProblem`:

```powershell
python -m unittest discover -s RL/tests -v
```
