"""Aggregate DriftGuard batch experiment outputs.

Run with:
    python -m fog_simulation.experiments.aggregate_results \
        --results-root results_experiments/nominal
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


AGGREGATE_METRICS = [
    "max_p99_latency",
    "mean_p99_latency",
    "median_p99_latency",
    "max_p95_latency",
    "mean_p95_latency",
    "max_jitter",
    "mean_jitter",
    "total_slo_violated_groups",
    "mean_violation_rate",
    "max_violation_rate",
    "total_events",
    "simulation_runtime_seconds",
    "scheduled_modules",
    "failed_modules",
    "capacity_violations",
    "negative_usage_violations",
]


GROUP_COLUMNS = ["scenario_name", "scheduler_type", "routing_policy"]


def aggregate_results(results_root) -> dict[str, Path]:
    """Create raw, summary, markdown, and comparison aggregate outputs."""
    results_root = Path(results_root)
    run_index_path = results_root / "run_index.csv"
    if not run_index_path.exists():
        raise FileNotFoundError(f"run_index.csv not found: {run_index_path}")

    run_index = pd.read_csv(run_index_path)
    raw_rows = []
    for row in run_index.to_dict(orient="records"):
        if str(row.get("status", "")).lower() != "success":
            continue
        raw_rows.append(_load_run_metrics(row))

    raw_df = pd.DataFrame(raw_rows)
    raw_path = results_root / "aggregate_raw.csv"
    raw_df.to_csv(raw_path, index=False)

    summary_df = _build_summary(raw_df)
    summary_path = results_root / "aggregate_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    summary_md_path = results_root / "aggregate_summary.md"
    _write_summary_markdown(summary_df, summary_md_path)

    comparison_df = _build_comparison(raw_df)
    comparison_path = results_root / "aggregate_comparison.csv"
    comparison_df.to_csv(comparison_path, index=False)

    return {
        "aggregate_raw": raw_path,
        "aggregate_summary": summary_path,
        "aggregate_summary_md": summary_md_path,
        "aggregate_comparison": comparison_path,
    }


def _load_run_metrics(index_row: dict[str, Any]) -> dict[str, Any]:
    result_path = Path(str(index_row["results_path"]))
    metrics_path = result_path / "run_metrics.json"
    config_path = result_path / "experiment_config.json"

    metrics = _read_json(metrics_path)
    config = _read_json(config_path)

    row = {
        "scenario_name": index_row.get("scenario_name") or config.get("scenario_name"),
        "scheduler_type": index_row.get("scheduler_type") or config.get("scheduler_type"),
        "routing_policy": index_row.get("routing_policy") or config.get("routing_policy"),
        "seed": index_row.get("seed") or config.get("seed"),
        "topology_seed": index_row.get("topology_seed"),
        "results_path": str(result_path),
    }
    row.update(metrics)

    # Fallbacks keep aggregation usable if a run directory was produced before
    # Phase 1 started writing run_metrics.json.
    if not metrics:
        row.update(_summarize_run_from_outputs(result_path))
    return row


def _summarize_run_from_outputs(result_path: Path) -> dict[str, Any]:
    slo_path = result_path / "slo_summary.csv"
    trace_path = result_path / "sim_trace.csv"
    slo_df = pd.read_csv(slo_path) if slo_path.exists() else pd.DataFrame()
    trace_df = pd.read_csv(trace_path) if trace_path.exists() else pd.DataFrame()
    return {
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
    }


def _build_summary(raw_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if raw_df.empty:
        return pd.DataFrame(
            columns=[
                *GROUP_COLUMNS,
                "metric",
                "n",
                "mean",
                "std",
                "min",
                "max",
                "ci95_half_width",
            ]
        )

    for group_key, group in raw_df.groupby(GROUP_COLUMNS, dropna=False):
        group_values = dict(zip(GROUP_COLUMNS, group_key))
        for metric in AGGREGATE_METRICS:
            if metric not in group.columns:
                continue
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            n = int(len(values))
            if n == 0:
                mean = std = min_value = max_value = ci95 = None
            else:
                mean = float(values.mean())
                min_value = float(values.min())
                max_value = float(values.max())
                if n < 2:
                    std = None
                    ci95 = None
                else:
                    std = float(values.std(ddof=1))
                    ci95 = 1.96 * std / math.sqrt(n)
            rows.append(
                {
                    **group_values,
                    "metric": metric,
                    "n": n,
                    "mean": mean,
                    "std": std,
                    "min": min_value,
                    "max": max_value,
                    "ci95_half_width": ci95,
                }
            )
    return pd.DataFrame(rows)


def _build_comparison(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()

    rows = []
    grouped = (
        raw_df.groupby(GROUP_COLUMNS, dropna=False)
        .agg(
            mean_p99_latency=("mean_p99_latency", "mean"),
            mean_jitter=("mean_jitter", "mean"),
            mean_violation_rate=("mean_violation_rate", "mean"),
        )
        .reset_index()
    )

    for (scenario_name, routing_policy), group in grouped.groupby(
        ["scenario_name", "routing_policy"], dropna=False
    ):
        baseline = group[group["scheduler_type"] == "default"]
        candidate = group[group["scheduler_type"] == "latency_resource"]
        if baseline.empty or candidate.empty:
            continue

        base = baseline.iloc[0]
        cand = candidate.iloc[0]
        rows.append(
            {
                "scenario_name": scenario_name,
                "routing_policy": routing_policy,
                "baseline_scheduler": "default",
                "candidate_scheduler": "latency_resource",
                "baseline_mean_p99_latency": base["mean_p99_latency"],
                "candidate_mean_p99_latency": cand["mean_p99_latency"],
                "p99_change_pct": _change_pct(
                    cand["mean_p99_latency"], base["mean_p99_latency"]
                ),
                "baseline_mean_jitter": base["mean_jitter"],
                "candidate_mean_jitter": cand["mean_jitter"],
                "jitter_change_pct": _change_pct(
                    cand["mean_jitter"], base["mean_jitter"]
                ),
                "baseline_mean_violation_rate": base["mean_violation_rate"],
                "candidate_mean_violation_rate": cand["mean_violation_rate"],
                "violation_rate_change_pct": _change_pct(
                    cand["mean_violation_rate"], base["mean_violation_rate"]
                ),
            }
        )
    return pd.DataFrame(rows)


def _write_summary_markdown(summary_df: pd.DataFrame, output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as fh:
        fh.write("# Aggregate Summary\n\n")
        if summary_df.empty:
            fh.write("No successful runs were available for aggregation.\n")
            return
        columns = list(summary_df.columns)
        fh.write("| " + " | ".join(columns) + " |\n")
        fh.write("| " + " | ".join(["---"] * len(columns)) + " |\n")
        for row in summary_df.to_dict(orient="records"):
            values = [_format_markdown_value(row.get(column)) for column in columns]
            fh.write("| " + " | ".join(values) + " |\n")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


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


def _change_pct(candidate, baseline) -> float | None:
    try:
        candidate = float(candidate)
        baseline = float(baseline)
    except (TypeError, ValueError):
        return None
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return 100.0 * (candidate - baseline) / baseline


def _format_markdown_value(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate DriftGuard batch results.")
    parser.add_argument("--results-root", required=True)
    args = parser.parse_args(argv)

    outputs = aggregate_results(args.results_root)
    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
