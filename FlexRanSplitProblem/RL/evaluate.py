"""Command-line evaluation entry point for a trained masked PPO policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..common import FlexRanSplitProblem
from .environment import FlexRanSplitEnv, RewardConfig
from .evaluation import evaluate_agent
from .ppo_agent import MaskedPPOAgent


PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROBLEM = PACKAGE_DIR / "results" / "problem_20260125_224620.pkl.gz"
DEFAULT_CHECKPOINT = Path(__file__).resolve().parent / "checkpoints" / "masked_ppo.pt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate masked PPO for FlexRAN Split.")
    parser.add_argument("--problem", type=Path, default=DEFAULT_PROBLEM)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--latency-weight", type=float, default=0.0)
    parser.add_argument("--shuffle-rus", action="store_true")
    parser.add_argument("--stochastic", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--json-output", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    problem = FlexRanSplitProblem.loadFromFile(str(args.problem))
    problem.sanity_check()
    env = FlexRanSplitEnv(
        problem,
        reward_config=RewardConfig(latency_weight=args.latency_weight),
        shuffle_rus=args.shuffle_rus,
    )
    agent = MaskedPPOAgent.load(args.checkpoint, device=args.device)
    results = evaluate_agent(
        agent,
        env,
        episodes=args.episodes,
        deterministic=not args.stochastic,
        seed=args.seed,
    )

    for result in results:
        print(
            f"Episode {result['episode']}: admitted "
            f"{result['admitted']}/{result['total_rus']}, "
            f"reward={result['reward']:.4f}"
        )
        for allocation in result["allocations"]:
            print(
                f"  RU {allocation['ru']}: admitted={allocation['admitted']} "
                f"DRC={allocation['drc']} path={allocation['path']}"
            )

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8"
        )
        print(f"Evaluation saved to: {args.json_output}")


if __name__ == "__main__":
    main()
