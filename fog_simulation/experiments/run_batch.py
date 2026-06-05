"""Run reproducible DriftGuard scheduler experiment batches.

Run with:
    python -m fog_simulation.experiments.run_batch \
        --manifest experiments/scenarios/nominal.json \
        --results-root results_experiments/nominal
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from pathlib import Path
from typing import Any

import pandas as pd

from fog_simulation.analysis import export_slo_outputs
from fog_simulation.experiments.aggregate_results import aggregate_results
from fog_simulation.simulation.resource_accounting import ResourceAccounting
from fog_simulation.simulation.runner import run_simulation
from fog_simulation.simulation.slo_monitor import (
    build_service_metadata,
    compute_latency_metrics,
    load_traces,
    save_summary,
)
from fog_simulation.analysis.slo_report import generate_report
from fog_simulation.topology import create_edge_fog_cloud_topology


RUN_INDEX_COLUMNS = [
    "scenario_name",
    "scheduler_type",
    "routing_policy",
    "seed",
    "topology_seed",
    "results_path",
    "config_path",
    "run_metrics_path",
    "status",
    "error",
    "simulation_runtime_seconds",
]


def run_batch(manifest_path, results_root, overrides: dict[str, Any] | None = None) -> dict[str, Path]:
    manifest_path = Path(manifest_path)
    results_root = Path(results_root)
    manifest = _load_manifest(manifest_path)
    manifest = _apply_overrides(manifest, overrides or {})
    scenario_name = manifest["scenario_name"]

    results_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, results_root / "manifest.json")

    run_index_rows = []
    for scheduler_type in manifest["schedulers"]:
        for routing_policy in manifest["routing_policies"]:
            for seed in manifest["seeds"]:
                topology_seed = _resolve_topology_seed(manifest, seed)
                run_dir = results_root / _run_dir_name(
                    scheduler_type, routing_policy, seed
                )
                run_dir.mkdir(parents=True, exist_ok=True)

                print("\n" + "=" * 78)
                print(
                    f"Batch run: scenario={scenario_name} "
                    f"scheduler={scheduler_type} routing={routing_policy} seed={seed}"
                )
                print("=" * 78)

                started = time.perf_counter()
                status = "success"
                error = ""
                config_path = run_dir / "experiment_config.json"
                run_metrics_path = run_dir / "run_metrics.json"
                try:
                    topology_params = _manifest_topology_params(manifest)
                    topology_params["seed"] = topology_seed
                    topology, _positions, _nodes_info = create_edge_fog_cloud_topology(
                        **topology_params
                    )
                    stress_profile = dict(manifest.get("stress_profile", {}))
                    applied_adjustments = _apply_topology_stress(
                        topology,
                        stress_profile,
                    )
                    workload_params = dict(manifest.get("workload_params", {}))
                    sim, results_path = run_simulation(
                        topology,
                        stop_time=int(manifest["stop_time"]),
                        recorder=None,
                        scheduler_type=scheduler_type,
                        routing_policy=routing_policy,
                        seed=int(seed),
                        topology_params=topology_params,
                        workload_params=workload_params,
                        scenario_name=scenario_name,
                        stress_profile=stress_profile,
                        applied_adjustments=applied_adjustments,
                        results_dir=run_dir,
                    )
                    runtime = time.perf_counter() - started
                    _generate_slo_outputs(
                        results_path=results_path,
                        top_n=int(manifest.get("top_n", 10)),
                        generate_reports=bool(manifest.get("generate_reports", True)),
                        stress_profile=stress_profile,
                    )
                    metrics = _summarize_run(
                        scenario_name=scenario_name,
                        scheduler_type=scheduler_type,
                        routing_policy=routing_policy,
                        seed=seed,
                        topology_seed=topology_seed,
                        results_path=results_path,
                        sim=sim,
                        runtime=runtime,
                    )
                    _write_json(run_metrics_path, metrics)
                except Exception as exc:
                    runtime = time.perf_counter() - started
                    status = "failed"
                    error = repr(exc)
                    print(f"Run failed: {error}")

                run_index_rows.append(
                    {
                        "scenario_name": scenario_name,
                        "scheduler_type": scheduler_type,
                        "routing_policy": routing_policy,
                        "seed": seed,
                        "topology_seed": topology_seed,
                        "results_path": str(run_dir),
                        "config_path": str(config_path),
                        "run_metrics_path": str(run_metrics_path),
                        "status": status,
                        "error": error,
                        "simulation_runtime_seconds": runtime,
                    }
                )

    run_index_path = results_root / "run_index.csv"
    _write_run_index(run_index_path, run_index_rows)
    aggregate_outputs = aggregate_results(results_root)
    return {"run_index": run_index_path, **aggregate_outputs}


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    required = [
        "scenario_name",
        "stop_time",
        "schedulers",
        "routing_policies",
        "seeds",
    ]
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"Manifest missing required keys: {missing}")

    manifest.setdefault("topology", {"with_gateways": True, "gateways_per_zone": 1})
    manifest.setdefault("topology_params", manifest.get("topology", {}))
    manifest.setdefault("workload_params", manifest.get("workload", {}))
    manifest.setdefault("stress_profile", {})
    manifest.setdefault("topology_seed", "same_as_seed")
    manifest.setdefault("top_n", 10)
    manifest.setdefault("generate_reports", True)
    return manifest


def _apply_overrides(
    manifest: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    if not overrides:
        return manifest

    updated = dict(manifest)
    if overrides.get("stop_time") is not None:
        updated["stop_time"] = int(overrides["stop_time"])
    if overrides.get("seeds") is not None:
        updated["seeds"] = [int(seed) for seed in overrides["seeds"]]
    if overrides.get("generate_reports") is not None:
        updated["generate_reports"] = bool(overrides["generate_reports"])
    return updated


def _resolve_topology_seed(manifest: dict[str, Any], seed: int) -> int:
    topology_seed = manifest.get("topology_seed", "same_as_seed")
    if topology_seed == "same_as_seed":
        return int(seed)
    return int(topology_seed)


def _run_dir_name(scheduler_type: str, routing_policy: str, seed: int) -> str:
    return f"{scheduler_type}_{routing_policy}_seed_{seed}"


def _manifest_topology_params(manifest: dict[str, Any]) -> dict[str, Any]:
    if "topology_params" in manifest:
        return dict(manifest.get("topology_params") or {})
    return dict(manifest.get("topology", {}) or {})


def _generate_slo_outputs(
    results_path: Path,
    top_n: int,
    generate_reports: bool,
    stress_profile: dict[str, Any] | None = None,
) -> None:
    slo_multiplier = _slo_multiplier(stress_profile)
    if generate_reports and abs(slo_multiplier - 1.0) < 1e-12:
        try:
            export_slo_outputs(results_path, window_size=250, top_n=top_n)
            return
        except pd.errors.EmptyDataError:
            pass

    try:
        events_df, _links_df = load_traces(results_path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        summary_df = _empty_slo_summary()
        save_summary(summary_df, results_path / "slo_summary.csv")
        save_summary(summary_df, results_path / "slo_summary_window_250.csv")
        return

    metadata = build_service_metadata()
    _apply_slo_multiplier(metadata, slo_multiplier)
    summary_df = compute_latency_metrics(events_df, service_metadata=metadata)
    window_df = compute_latency_metrics(
        events_df,
        service_metadata=metadata,
        window_size=250,
    )
    save_summary(summary_df, results_path / "slo_summary.csv")
    save_summary(window_df, results_path / "slo_summary_window_250.csv")
    if generate_reports:
        generate_report(
            results_dir=results_path,
            top_n=top_n,
            window_file=results_path / "slo_summary_window_250.csv",
            show=False,
        )


def _empty_slo_summary() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "app",
            "module",
            "message",
            "count",
            "mean_latency",
            "median_latency",
            "p95_latency",
            "p99_latency",
            "jitter",
            "latency_std",
            "max_latency",
            "min_latency",
            "slo_ms_p99",
            "slo_violated",
            "violation_rate",
        ]
    )


def _slo_multiplier(stress_profile: dict[str, Any] | None) -> float:
    stress_profile = stress_profile or {}
    return _positive_float(stress_profile.get("slo_multiplier", 1.0), 1.0)


def _apply_slo_multiplier(metadata: pd.DataFrame, multiplier: float) -> None:
    if abs(multiplier - 1.0) < 1e-12 or "slo_ms_p99" not in metadata.columns:
        return
    metadata["slo_ms_p99"] = pd.to_numeric(
        metadata["slo_ms_p99"],
        errors="coerce",
    ) * multiplier


def _apply_topology_stress(topology, stress_profile: dict[str, Any]) -> dict[str, Any]:
    applied: dict[str, Any] = {
        "node_multipliers": {},
        "edge_multipliers": {},
    }
    if not stress_profile:
        return applied

    node_specs = [
        ("fog_cpu_multiplier", "fog", "CPU"),
        ("fog_ram_multiplier", "fog", "RAM"),
        ("fog_bw_multiplier", "fog", "BW"),
    ]
    for param, node_type, attr in node_specs:
        multiplier = _optional_positive_float(stress_profile.get(param))
        if multiplier is None:
            continue
        changed = 0
        for _node_id, attrs in topology.G.nodes(data=True):
            if attrs.get("type") != node_type or attr not in attrs:
                continue
            attrs[attr] = _scale_numeric(attrs[attr], multiplier, minimum=1.0)
            changed += 1
        applied["node_multipliers"][param] = {
            "multiplier": multiplier,
            "nodes_changed": changed,
        }

    edge_specs = [
        ("gateway_bw_multiplier", "BW", _is_gateway_edge),
        ("gateway_pr_multiplier", "PR", _is_gateway_edge),
        ("inter_zone_bw_multiplier", "BW", _is_inter_zone_edge),
        ("inter_zone_pr_multiplier", "PR", _is_inter_zone_edge),
        ("cloud_pr_multiplier", "PR", _is_cloud_edge),
    ]
    for param, attr, predicate in edge_specs:
        multiplier = _optional_positive_float(stress_profile.get(param))
        if multiplier is None:
            continue
        changed = 0
        for src, dst, attrs in topology.G.edges(data=True):
            if attr not in attrs or not predicate(topology, src, dst):
                continue
            attrs[attr] = _scale_numeric(attrs[attr], multiplier, minimum=0.0)
            changed += 1
        applied["edge_multipliers"][param] = {
            "multiplier": multiplier,
            "edges_changed": changed,
        }

    if "slo_multiplier" in stress_profile:
        applied["slo_multiplier"] = _slo_multiplier(stress_profile)
    return applied


def _is_gateway_edge(topology, src, dst) -> bool:
    return (
        topology.G.nodes[src].get("type") == "gateway"
        or topology.G.nodes[dst].get("type") == "gateway"
    )


def _is_inter_zone_edge(topology, src, dst) -> bool:
    src_attrs = topology.G.nodes[src]
    dst_attrs = topology.G.nodes[dst]
    src_zone = src_attrs.get("zone")
    dst_zone = dst_attrs.get("zone")
    if src_zone in (None, 0) or dst_zone in (None, 0):
        return False
    return src_zone != dst_zone


def _is_cloud_edge(topology, src, dst) -> bool:
    return (
        topology.G.nodes[src].get("type") == "cloud"
        or topology.G.nodes[dst].get("type") == "cloud"
    )


def _scale_numeric(value, multiplier: float, minimum: float):
    try:
        scaled = float(value) * multiplier
    except (TypeError, ValueError):
        return value
    scaled = max(scaled, minimum)
    if isinstance(value, int):
        return int(round(scaled))
    return scaled


def _optional_positive_float(value) -> float | None:
    if value is None:
        return None
    return _positive_float(value, 1.0)


def _positive_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _summarize_run(
    scenario_name: str,
    scheduler_type: str,
    routing_policy: str,
    seed: int,
    topology_seed: int,
    results_path: Path,
    sim,
    runtime: float,
) -> dict[str, Any]:
    slo_path = results_path / "slo_summary.csv"
    trace_path = results_path / "sim_trace.csv"
    slo_df = _safe_read_csv(slo_path)
    trace_df = _safe_read_csv(trace_path)

    accounting_summary = ResourceAccounting(sim.topology).summary()
    scheduler = getattr(sim, "driftguard_scheduler", None)

    return {
        "scenario_name": scenario_name,
        "scheduler_type": scheduler_type,
        "routing_policy": routing_policy,
        "seed": seed,
        "topology_seed": topology_seed,
        "max_p99_latency": _numeric_max(slo_df, "p99_latency"),
        "mean_p99_latency": _numeric_mean(slo_df, "p99_latency"),
        "median_p99_latency": _numeric_median(slo_df, "p99_latency"),
        "max_p95_latency": _numeric_max(slo_df, "p95_latency"),
        "mean_p95_latency": _numeric_mean(slo_df, "p95_latency"),
        "max_jitter": _numeric_max(slo_df, "jitter"),
        "mean_jitter": _numeric_mean(slo_df, "jitter"),
        "total_slo_violated_groups": _bool_sum(slo_df, "slo_violated"),
        "mean_violation_rate": _numeric_mean(slo_df, "violation_rate"),
        "max_violation_rate": _numeric_max(slo_df, "violation_rate"),
        "total_events": int(len(trace_df)),
        "simulation_runtime_seconds": float(runtime),
        "scheduled_modules": len(getattr(scheduler, "_decisions", []) or []),
        "failed_modules": len(getattr(scheduler, "_failed_decisions", []) or []),
        "capacity_violations": len(accounting_summary["capacity_violations"]),
        "negative_usage_violations": len(
            accounting_summary["negative_usage_violations"]
        ),
    }


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _numeric_max(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    return float(values.max()) if len(values) else None


def _numeric_mean(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    return float(values.mean()) if len(values) else None


def _numeric_median(df: pd.DataFrame, column: str) -> float | None:
    values = _numeric_series(df, column)
    return float(values.median()) if len(values) else None


def _bool_sum(df: pd.DataFrame, column: str) -> int | None:
    if df.empty or column not in df.columns:
        return None
    return int(df[column].astype(bool).sum())


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_run_index(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RUN_INDEX_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in RUN_INDEX_COLUMNS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DriftGuard experiment batch.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--stop-time", type=int, default=None)
    parser.add_argument(
        "--seeds",
        default=None,
        help="Optional comma-separated seed override, e.g. 1,2",
    )
    parser.add_argument("--no-reports", action="store_true")
    args = parser.parse_args(argv)

    seed_override = None
    if args.seeds:
        seed_override = [
            int(seed.strip()) for seed in args.seeds.split(",") if seed.strip()
        ]
    outputs = run_batch(
        args.manifest,
        args.results_root,
        overrides={
            "stop_time": args.stop_time,
            "seeds": seed_override,
            "generate_reports": False if args.no_reports else None,
        },
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
