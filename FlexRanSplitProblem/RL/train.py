"""Command-line training entry point for masked PPO."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict

from ..common import FlexRanSplitProblem
from .environment import FlexRanSplitEnv, RewardConfig
from .ppo_agent import MaskedPPOAgent, PPOConfig


PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROBLEM = PACKAGE_DIR / "results" / "problem_20260125_224620.pkl.gz"
DEFAULT_CHECKPOINT = Path(__file__).resolve().parent / "checkpoints" / "masked_ppo.pt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train masked PPO for FlexRAN Split.")
    parser.add_argument("--problem", type=Path, default=DEFAULT_PROBLEM)
    parser.add_argument("--output", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--timesteps", type=int, default=100_000)
    parser.add_argument("--rollout-steps", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--update-epochs", type=int, default=10)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--latency-weight", type=float, default=0.0)
    parser.add_argument("--shuffle-rus", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, ...")
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
    config = PPOConfig(
        learning_rate=args.learning_rate,
        rollout_steps=args.rollout_steps,
        batch_size=args.batch_size,
        update_epochs=args.update_epochs,
        seed=args.seed,
        device=args.device,
    )
    agent = MaskedPPOAgent(env.observation_dim, env.action_dim, config=config)

    print(
        f"Problem: {args.problem}\n"
        f"RUs: {len(env.catalog.ru_ids)} | DRCs: {len(env.catalog.drc_ids)} | "
        f"paths: {len(env.catalog.paths)}\n"
        f"observation_dim: {env.observation_dim} | action_dim: {env.action_dim}"
    )

    def log_update(metrics: Dict[str, float]) -> None:
        print(
            f"steps={int(metrics['timesteps']):7d} "
            f"episodes={int(metrics['episodes']):6d} "
            f"policy_loss={metrics['policy_loss']:+.4f} "
            f"value_loss={metrics['value_loss']:.4f} "
            f"entropy={metrics['entropy']:.4f}"
        )

    agent.train(env, total_timesteps=args.timesteps, callback=log_update)
    agent.save(
        args.output,
        metadata={"environment": env.checkpoint_metadata()},
    )
    print(f"Checkpoint saved to: {args.output}")


if __name__ == "__main__":
    main()
