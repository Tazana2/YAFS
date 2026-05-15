"""Post-run latency and SLO analysis for YAFS traces.

This module is intentionally offline-only.  It reads the CSV files produced by
YAFS after a run and computes global or fixed-window summaries; it does not
change placement, migration, or scheduling decisions.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from yafs.application import Application

from fog_simulation.applications.iot_monitoring import create_iot_application
from fog_simulation.applications.parking_intelligence import (
    create_parking_intelligence_app,
)
from fog_simulation.applications.parking_security import create_parking_security_app
from fog_simulation.applications.platform_lifecycle import (
    create_platform_lifecycle_app,
)
from fog_simulation.applications.sensor_climatology import (
    create_sensor_climatology_app,
)
from fog_simulation.applications.video_analytics import create_video_analytics_app
from fog_simulation.simulation.service_metadata import normalize_service_profile


DEFAULT_APP_FACTORIES: tuple[Callable[[], Application], ...] = (
    create_video_analytics_app,
    create_sensor_climatology_app,
    create_platform_lifecycle_app,
    create_parking_intelligence_app,
    create_parking_security_app,
    create_iot_application,
)


def load_traces(results_dir_or_event_path, link_path=None):
    """Load YAFS event and link traces.

    ``results_dir_or_event_path`` can be a directory containing
    ``sim_trace.csv`` or a direct path to an event CSV.  If ``link_path`` is
    omitted, ``sim_trace_link.csv`` or ``<event_stem>_link.csv`` is used when
    present.  Missing link traces return an empty DataFrame.
    """
    path = Path(results_dir_or_event_path)
    if path.is_dir():
        event_path = path / "sim_trace.csv"
        inferred_link_path = path / "sim_trace_link.csv"
    else:
        event_path = path
        inferred_link_path = event_path.with_name(
            f"{event_path.stem}_link{event_path.suffix}"
        )

    if link_path is not None:
        inferred_link_path = Path(link_path)

    events_df = pd.read_csv(event_path)
    links_df = (
        pd.read_csv(inferred_link_path)
        if inferred_link_path.exists()
        else pd.DataFrame()
    )
    return events_df, links_df


def build_service_metadata(
    app_factories: tuple[Callable[[], Application], ...] = DEFAULT_APP_FACTORIES,
) -> pd.DataFrame:
    """Return normalized service metadata for known application factories."""
    rows: list[dict[str, Any]] = []
    for factory in app_factories:
        app = factory()
        for entry in getattr(app, "data", []) or []:
            module_name = list(entry.keys())[0]
            attrs = list(entry.values())[0]
            profile = normalize_service_profile(app.name, module_name, attrs)
            rows.append(
                {
                    "app": app.name,
                    "module": module_name,
                    "module_type": attrs.get("Type"),
                    "CPU_req": profile.get("CPU_req"),
                    "RAM_req": profile.get("RAM_req"),
                    "BW_req": profile.get("BW_req"),
                    "service_class": profile.get("service_class"),
                    "slo_ms_p99": profile.get("slo_ms_p99"),
                    "allowed_layers": ",".join(profile.get("allowed_layers") or []),
                    "preferred_role": profile.get("preferred_role"),
                    "priority": profile.get("priority"),
                    "cooldown_windows": profile.get("cooldown_windows"),
                }
            )
    return pd.DataFrame(rows)


def compute_latency_metrics(
    events_df,
    service_metadata=None,
    window_size=None,
):
    """Compute per app/module/message latency, jitter, and optional SLO fields.

    Latency is ``time_out - time_emit`` when both columns exist.  Fallbacks are
    ``time_out - time_reception`` and then ``time_out - time_in``.

    Jitter is the mean absolute difference between consecutive latencies within
    each group after sorting by ``time_emit``, ``time_reception``, or
    ``time_in``.  ``latency_std`` is also reported as the standard deviation of
    latency values in the same group.
    """
    if events_df is None or len(events_df) == 0:
        return pd.DataFrame()

    df = events_df.copy()
    df = _coerce_numeric_columns(
        df,
        [
            "time_out",
            "time_emit",
            "time_reception",
            "time_in",
            "service",
        ],
    )

    latency_col, latency_basis = _event_latency_series(df)
    df["latency"] = latency_col
    df["latency_basis"] = latency_basis

    if {"time_reception", "time_emit"}.issubset(df.columns):
        df["network_time"] = df["time_reception"] - df["time_emit"]
    if {"time_out", "time_in"}.issubset(df.columns):
        df["service_time"] = df["time_out"] - df["time_in"]
    elif "service" in df.columns:
        df["service_time"] = df["service"]
    if {"time_in", "time_reception"}.issubset(df.columns):
        df["wait_time"] = df["time_in"] - df["time_reception"]

    df = df[df["latency"].notna()]
    group_cols = _available_group_columns(df, ["app", "module", "message"])
    sort_col = _first_present(df, ["time_emit", "time_reception", "time_in"])

    if window_size is not None:
        window_source = sort_col or _first_present(df, ["time_out"])
        if window_source is None:
            raise ValueError("window_size requires a time column in the event trace")
        window_size = float(window_size)
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        df["window_start"] = (df[window_source] // window_size) * window_size
        df["window_end"] = df["window_start"] + window_size
        group_cols = ["window_start", "window_end", *group_cols]

    rows = []
    for group_key, group in df.groupby(group_cols, dropna=False):
        row = _group_key_to_row(group_cols, group_key)
        ordered = group.sort_values(sort_col) if sort_col is not None else group
        latency = ordered["latency"]
        diffs = latency.diff().abs().dropna()
        row.update(
            {
                "count": int(latency.count()),
                "mean_latency": float(latency.mean()),
                "median_latency": float(latency.median()),
                "p95_latency": float(latency.quantile(0.95)),
                "p99_latency": float(latency.quantile(0.99)),
                "jitter": float(diffs.mean()) if len(diffs) else 0.0,
                "latency_std": float(latency.std(ddof=0)) if len(latency) else 0.0,
                "max_latency": float(latency.max()),
                "min_latency": float(latency.min()),
                "latency_basis": latency_basis,
            }
        )
        _add_optional_mean(row, group, "network_time")
        _add_optional_mean(row, group, "service_time")
        _add_optional_mean(row, group, "wait_time")
        rows.append(row)

    metrics = pd.DataFrame(rows)
    metrics = _attach_service_metadata(metrics, service_metadata)
    metrics = _add_slo_columns(metrics, df, group_cols)
    return _order_columns(metrics)


def compute_link_metrics(links_df, window_size=None):
    """Compute link-hop latency summaries from the YAFS link trace."""
    if links_df is None or len(links_df) == 0:
        return pd.DataFrame()
    if "latency" not in links_df.columns:
        return pd.DataFrame()

    df = links_df.copy()
    df = _coerce_numeric_columns(df, ["latency", "ctime", "size", "buffer"])
    df = df[df["latency"].notna()]
    group_cols = _available_group_columns(df, ["app", "message", "src", "dst"])
    sort_col = _first_present(df, ["ctime"])

    if window_size is not None:
        if sort_col is None:
            raise ValueError("window_size requires ctime in the link trace")
        window_size = float(window_size)
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        df["window_start"] = (df[sort_col] // window_size) * window_size
        df["window_end"] = df["window_start"] + window_size
        group_cols = ["window_start", "window_end", *group_cols]

    rows = []
    for group_key, group in df.groupby(group_cols, dropna=False):
        row = _group_key_to_row(group_cols, group_key)
        latency = group["latency"]
        row.update(
            {
                "count": int(latency.count()),
                "mean_link_latency": float(latency.mean()),
                "median_link_latency": float(latency.median()),
                "p95_link_latency": float(latency.quantile(0.95)),
                "p99_link_latency": float(latency.quantile(0.99)),
                "max_link_latency": float(latency.max()),
                "min_link_latency": float(latency.min()),
            }
        )
        _add_optional_mean(row, group, "size", output_name="mean_size")
        _add_optional_mean(row, group, "buffer", output_name="mean_buffer")
        rows.append(row)

    return pd.DataFrame(rows)


def summarize_slo_violations(latency_metrics_df):
    """Return rows whose p99 latency exceeds their ``slo_ms_p99`` target."""
    if latency_metrics_df is None or len(latency_metrics_df) == 0:
        return pd.DataFrame()
    required = {"slo_ms_p99", "slo_violated"}
    if not required.issubset(latency_metrics_df.columns):
        return pd.DataFrame()

    violations = latency_metrics_df[
        latency_metrics_df["slo_ms_p99"].notna()
        & latency_metrics_df["slo_violated"].astype(bool)
    ].copy()
    if len(violations) == 0:
        return violations
    violations["p99_slo_gap"] = (
        violations["p99_latency"] - violations["slo_ms_p99"]
    )
    return violations.sort_values(
        ["p99_slo_gap", "violation_rate"],
        ascending=[False, False],
    )


def save_summary(metrics_df, output_path):
    """Save a metrics DataFrame to CSV and return the output path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_df.to_csv(output_path, index=False)
    return output_path


def _event_latency_series(df: pd.DataFrame) -> tuple[pd.Series, str]:
    if {"time_out", "time_emit"}.issubset(df.columns):
        return df["time_out"] - df["time_emit"], "time_out-time_emit"
    if {"time_out", "time_reception"}.issubset(df.columns):
        return df["time_out"] - df["time_reception"], "time_out-time_reception"
    if {"time_out", "time_in"}.issubset(df.columns):
        return df["time_out"] - df["time_in"], "time_out-time_in"
    raise ValueError(
        "Cannot compute latency. Need time_out plus one of "
        "time_emit, time_reception, or time_in."
    )


def _attach_service_metadata(metrics: pd.DataFrame, service_metadata) -> pd.DataFrame:
    if len(metrics) == 0:
        return metrics
    if service_metadata is None:
        service_metadata = build_service_metadata()
    if isinstance(service_metadata, dict):
        service_metadata = pd.DataFrame(
            [
                {"app": app, "module": module, **metadata}
                for (app, module), metadata in service_metadata.items()
            ]
        )
    if service_metadata is None or len(service_metadata) == 0:
        return metrics

    metadata_df = service_metadata.copy()
    merge_cols = [col for col in ["app", "module"] if col in metrics.columns]
    merge_cols = [col for col in merge_cols if col in metadata_df.columns]
    if not merge_cols:
        return metrics

    metadata_cols = [
        col
        for col in [
            "app",
            "module",
            "service_class",
            "slo_ms_p99",
            "priority",
            "preferred_role",
            "allowed_layers",
            "cooldown_windows",
        ]
        if col in metadata_df.columns
    ]
    metadata_df = metadata_df[metadata_cols].drop_duplicates(merge_cols)
    return metrics.merge(metadata_df, on=merge_cols, how="left")


def _add_slo_columns(
    metrics: pd.DataFrame,
    events: pd.DataFrame,
    group_cols: list[str],
) -> pd.DataFrame:
    if "slo_ms_p99" not in metrics.columns:
        metrics["slo_ms_p99"] = pd.NA

    metrics["slo_violated"] = False
    metrics["violation_count"] = 0
    metrics["violation_rate"] = 0.0

    if len(metrics) == 0 or metrics["slo_ms_p99"].isna().all():
        return metrics

    merged = events.merge(
        metrics[[*group_cols, "slo_ms_p99"]],
        on=group_cols,
        how="left",
    )
    merged["slo_event_violated"] = (
        merged["slo_ms_p99"].notna() & (merged["latency"] > merged["slo_ms_p99"])
    )
    violation_counts = (
        merged.groupby(group_cols, dropna=False)["slo_event_violated"]
        .sum()
        .reset_index(name="violation_count")
    )
    metrics = metrics.drop(columns=["violation_count"]).merge(
        violation_counts,
        on=group_cols,
        how="left",
    )
    metrics["violation_count"] = metrics["violation_count"].fillna(0).astype(int)
    metrics["violation_rate"] = metrics["violation_count"] / metrics["count"]
    metrics["slo_violated"] = (
        metrics["slo_ms_p99"].notna()
        & (metrics["p99_latency"] > metrics["slo_ms_p99"])
    )
    return metrics


def _order_columns(metrics: pd.DataFrame) -> pd.DataFrame:
    first = [
        "window_start",
        "window_end",
        "app",
        "module",
        "message",
        "service_class",
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
        "violation_count",
        "violation_rate",
        "network_time_mean",
        "service_time_mean",
        "wait_time_mean",
        "latency_basis",
    ]
    ordered = [col for col in first if col in metrics.columns]
    ordered.extend(col for col in metrics.columns if col not in ordered)
    return metrics[ordered]


def _available_group_columns(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    cols = [col for col in candidates if col in df.columns]
    if cols:
        return cols
    df["group"] = "all"
    return ["group"]


def _first_present(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _group_key_to_row(group_cols: list[str], group_key) -> dict[str, Any]:
    if len(group_cols) == 1:
        group_key = (group_key,)
    return dict(zip(group_cols, group_key))


def _coerce_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _add_optional_mean(
    row: dict[str, Any],
    group: pd.DataFrame,
    col: str,
    output_name: Optional[str] = None,
) -> None:
    if col in group.columns:
        row[output_name or f"{col}_mean"] = float(group[col].mean())


def _print_cli_table(df: pd.DataFrame, columns: list[str], limit: int) -> None:
    if df is None or len(df) == 0:
        print("  none")
        return
    available = [col for col in columns if col in df.columns]
    print(df[available].head(limit).to_string(index=False))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze YAFS SLO metrics.")
    parser.add_argument(
        "results",
        nargs="?",
        default="results_fog_simulation",
        help="Results directory or direct sim_trace.csv path.",
    )
    parser.add_argument("--link-path", default=None)
    parser.add_argument("--window-size", type=float, default=None)
    parser.add_argument(
        "--output",
        default=None,
        help="Summary CSV path. Defaults to <results_dir>/slo_summary.csv.",
    )
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    events_df, links_df = load_traces(args.results, args.link_path)
    metrics_df = compute_latency_metrics(
        events_df,
        service_metadata=build_service_metadata(),
        window_size=args.window_size,
    )
    compute_link_metrics(links_df, window_size=args.window_size)

    result_path = Path(args.results)
    if args.output is not None:
        output_path = Path(args.output)
    elif result_path.is_dir():
        output_path = result_path / "slo_summary.csv"
    else:
        output_path = result_path.with_name("slo_summary.csv")

    save_summary(metrics_df, output_path)
    top_p99 = metrics_df.sort_values("p99_latency", ascending=False)
    violations = summarize_slo_violations(metrics_df)

    print("Event columns:", list(events_df.columns))
    print("Link columns:", list(links_df.columns))
    print(f"Saved SLO summary: {output_path}")
    print("\nTop services by p99 latency:")
    _print_cli_table(
        top_p99,
        [
            "app",
            "module",
            "message",
            "count",
            "p95_latency",
            "p99_latency",
            "jitter",
            "slo_ms_p99",
            "slo_violated",
        ],
        args.top,
    )
    print("\nServices with SLO violations:")
    _print_cli_table(
        violations,
        [
            "app",
            "module",
            "message",
            "count",
            "p99_latency",
            "slo_ms_p99",
            "violation_count",
            "violation_rate",
            "p99_slo_gap",
        ],
        args.top,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
