"""Smoke checks that both non-RL scheduler policies still run.

Run with:
    python -m fog_simulation.simulation.smoke_scheduler_runs
"""

import argparse
import tempfile
from pathlib import Path

from fog_simulation.simulation.runner import run_simulation
from fog_simulation.topology import create_edge_fog_cloud_topology


POLICIES = ("default", "latency_resource")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-time", type=int, default=300)
    parser.add_argument("--routing-policy", choices=["hop", "latency"], default="hop")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--results-root", default=None)
    args = parser.parse_args(argv)

    if args.results_root is None:
        tmp = tempfile.TemporaryDirectory(prefix="yafs_scheduler_smoke_")
        results_root = Path(tmp.name)
    else:
        tmp = None
        results_root = Path(args.results_root)

    try:
        for policy in POLICIES:
            topology, _positions, _nodes_info = create_edge_fog_cloud_topology(
                with_gateways=True,
                gateways_per_zone=1,
                seed=args.seed,
            )
            _sim, results_path = run_simulation(
                topology,
                stop_time=args.stop_time,
                recorder=None,
                scheduler_type=policy,
                routing_policy=args.routing_policy,
                seed=args.seed,
                topology_params={
                    "with_gateways": True,
                    "gateways_per_zone": 1,
                    "seed": args.seed,
                },
                results_dir=results_root / policy,
            )
            assert (results_path / "sim_trace.csv").exists()
            assert (results_path / "sim_trace_link.csv").exists()
            assert (results_path / "experiment_config.json").exists()
    finally:
        if tmp is not None:
            tmp.cleanup()

    print("Scheduler run smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
