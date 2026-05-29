"""Run a small default-vs-latency-resource scheduler comparison.

This script only compares initial placement policies.  It does not perform
runtime migration, rescheduling, evictions, or RL training/evaluation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from fog_simulation.analysis import export_slo_outputs
from fog_simulation.simulation.resource_accounting import ResourceAccounting
from fog_simulation.simulation.runner import run_simulation
from fog_simulation.topology import create_edge_fog_cloud_topology


POLICIES = ("default", "latency_resource")


def run_comparison(
    stop_time: int,
    results_root,
    with_gateways: bool = True,
    gateways_per_zone: int = 1,
    routing_policy: str = "hop",
    seed: int = 42,
    topology_seed: int = 42,
    top_n: int = 10,
) -> dict[str, dict[str, float | int | str]]:
    results_root = Path(results_root)
    results_root.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, dict[str, float | int | str]] = {}
    for policy in POLICIES:
        print("\n" + "=" * 70)
        print(f"Running scheduler policy: {policy}")
        print("=" * 70)

        topology, _positions, _nodes_info = create_edge_fog_cloud_topology(
            with_gateways=with_gateways,
            gateways_per_zone=gateways_per_zone,
            seed=topology_seed,
        )
        sim, results_path = run_simulation(
            topology,
            stop_time=stop_time,
            recorder=None,
            scheduler_type=policy,
            routing_policy=routing_policy,
            seed=seed,
            topology_params={
                "with_gateways": with_gateways,
                "gateways_per_zone": gateways_per_zone,
                "seed": topology_seed,
            },
            results_dir=results_root / policy,
        )
        export_slo_outputs(results_path, window_size=250, top_n=top_n)
        summaries[policy] = _summarize_results(
            results_path=results_path,
            accounting=ResourceAccounting(sim.topology),
        )

    _print_comparison_table(summaries)
    return summaries


def _summarize_results(results_path: Path, accounting: ResourceAccounting) -> dict:
    summary_path = results_path / "slo_summary.csv"
    if summary_path.exists():
        df = pd.read_csv(summary_path)
    else:
        df = pd.DataFrame()

    acct_summary = accounting.summary()
    totals = acct_summary["totals"]

    return {
        "results_path": str(results_path),
        "max_p99_latency": _numeric_max(df, "p99_latency"),
        "mean_p99_latency": _numeric_mean(df, "p99_latency"),
        "max_jitter": _numeric_max(df, "jitter"),
        "mean_jitter": _numeric_mean(df, "jitter"),
        "slo_violated_groups": int(df["slo_violated"].astype(bool).sum())
        if "slo_violated" in df.columns
        else 0,
        "mean_violation_rate": _numeric_mean(df, "violation_rate"),
        "total_cpu_utilization": _safe_ratio(
            totals["CPU_used"], totals["CPU_capacity"]
        ),
        "total_ram_utilization": _safe_ratio(
            totals["RAM_used"], totals["RAM_capacity"]
        ),
        "total_bw_utilization": _safe_ratio(totals["BW_used"], totals["BW_capacity"]),
    }


def _print_comparison_table(summaries: dict[str, dict]) -> None:
    metrics = [
        "max_p99_latency",
        "mean_p99_latency",
        "max_jitter",
        "mean_jitter",
        "slo_violated_groups",
        "mean_violation_rate",
        "total_cpu_utilization",
        "total_ram_utilization",
        "total_bw_utilization",
    ]
    print("\n" + "=" * 70)
    print("SCHEDULER COMPARISON")
    print("=" * 70)
    print(f"{'Metric':<28} {'default':>18} {'latency_resource':>18}")
    print("-" * 70)
    for metric in metrics:
        left = summaries.get("default", {}).get(metric, 0)
        right = summaries.get("latency_resource", {}).get(metric, 0)
        print(f"{metric:<28} {_format_value(left):>18} {_format_value(right):>18}")
    print("-" * 70)
    for policy, summary in summaries.items():
        print(f"{policy:<18}: {summary['results_path']}")


def _numeric_max(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return float(values.max()) if len(values) else 0.0


def _numeric_mean(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return float(values.mean()) if len(values) else 0.0


def _safe_ratio(used: float, capacity: float) -> float:
    return float(used / capacity) if capacity else 0.0


def _format_value(value) -> str:
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare default and latency_resource initial schedulers."
    )
    parser.add_argument("--stop-time", type=int, default=1000)
    parser.add_argument("--results-root", default="results_fog_simulation")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--no-gateways", action="store_true")
    parser.add_argument("--gateways-per-zone", type=int, default=1)
    parser.add_argument("--routing-policy", choices=["hop", "latency"], default="hop")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--topology-seed", type=int, default=42)
    args = parser.parse_args(argv)

    run_comparison(
        stop_time=args.stop_time,
        results_root=args.results_root,
        with_gateways=not args.no_gateways,
        gateways_per_zone=args.gateways_per_zone,
        routing_policy=args.routing_policy,
        seed=args.seed,
        topology_seed=args.topology_seed,
        top_n=args.top_n,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
