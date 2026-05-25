"""Visual SLO report generation for DriftGuard post-run metrics.

This module only reads generated CSV summaries and traces.  It does not alter
placement, scheduling, migration, or runtime simulation behavior.
"""

from __future__ import annotations

import argparse
import html
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


FIGURE_NAMES = {
    "top_p99": "top_p99_latency.png",
    "p99_vs_slo": "p99_vs_slo.png",
    "slo_margin": "slo_margin.png",
    "jitter": "jitter_by_service.png",
    "violation_rate": "violation_rate_by_service.png",
    "window_p99": "window_p99_latency.png",
    "window_heatmap": "window_slo_violation_heatmap.png",
    "top_link": "top_link_latency.png",
}


def generate_report(
    results_dir,
    top_n: int = 10,
    window_file=None,
    show: bool = False,
) -> dict[str, object]:
    """Generate PNG figures and an HTML report for SLO summary CSVs."""
    results_dir = Path(results_dir)
    figures_dir = results_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    summary_path = results_dir / "slo_summary.csv"
    window_path = Path(window_file) if window_file else results_dir / "slo_summary_window_250.csv"
    link_path = results_dir / "sim_trace_link.csv"

    warnings: list[str] = []
    summary_df = _read_csv(summary_path, "global SLO summary", warnings)
    window_df = _read_csv(window_path, "window SLO summary", warnings)
    links_df = _read_csv(link_path, "YAFS link trace", warnings)

    figure_paths: dict[str, Path] = {}
    if not summary_df.empty:
        _add_slo_margin(summary_df)
        figure_paths["top_p99"] = _plot_top_p99(summary_df, figures_dir, top_n, warnings)
        figure_paths["p99_vs_slo"] = _plot_p99_vs_slo(summary_df, figures_dir, top_n, warnings)
        figure_paths["slo_margin"] = _plot_slo_margin(summary_df, figures_dir, top_n, warnings)
        figure_paths["jitter"] = _plot_jitter(summary_df, figures_dir, top_n, warnings)
        figure_paths["violation_rate"] = _plot_violation_rate(summary_df, figures_dir, top_n, warnings)
    else:
        warnings.append(f"Missing or empty {summary_path}; skipped global SLO plots.")

    if not window_df.empty:
        _add_slo_margin(window_df)
        figure_paths["window_p99"] = _plot_window_p99(
            window_df,
            summary_df,
            figures_dir,
            top_n=min(5, max(1, top_n)),
            warnings=warnings,
        )
        figure_paths["window_heatmap"] = _plot_window_heatmap(
            window_df,
            summary_df,
            figures_dir,
            top_n=min(10, max(1, top_n)),
            warnings=warnings,
        )
    else:
        warnings.append(f"Missing or empty {window_path}; skipped window plots.")

    if not links_df.empty:
        figure_paths["top_link"] = _plot_top_link_latency(
            links_df,
            figures_dir,
            top_n=top_n,
            warnings=warnings,
        )
    else:
        warnings.append(f"Missing or empty {link_path}; skipped link-latency plot.")

    html_path = results_dir / "slo_report.html"
    _write_html_report(
        html_path=html_path,
        figures_dir=figures_dir,
        figure_paths=figure_paths,
        input_files={
            "Global SLO summary": summary_path,
            "Window SLO summary": window_path,
            "Link trace": link_path,
        },
        summary_df=summary_df,
        warnings=warnings,
        top_n=top_n,
    )

    if show:
        webbrowser.open(html_path.resolve().as_uri())

    return {
        "summary_path": summary_path,
        "window_path": window_path,
        "link_path": link_path,
        "figures_dir": figures_dir,
        "figure_paths": figure_paths,
        "html_path": html_path,
        "warnings": warnings,
    }


def _read_csv(path: Path, label: str, warnings: list[str]) -> pd.DataFrame:
    if not path.exists():
        warnings.append(f"WARNING: {label} not found: {path}")
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception as exc:
        warnings.append(f"WARNING: could not read {label} at {path}: {exc}")
        return pd.DataFrame()


def _add_slo_margin(df: pd.DataFrame) -> None:
    if {"slo_ms_p99", "p99_latency"}.issubset(df.columns):
        df["slo_margin"] = df["slo_ms_p99"] - df["p99_latency"]


def _plot_top_p99(
    df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["p99_latency"]
    if not _has_columns(df, required, "top_p99_latency", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["top_p99"], "Missing p99_latency")

    top = df.sort_values("p99_latency", ascending=False).head(top_n).copy()
    labels = [_service_label(row) for _, row in top.iterrows()]
    y = range(len(top))

    fig, ax = plt.subplots(figsize=(11, max(4.5, 0.46 * len(top) + 1.6)))
    ax.barh(y, top["p99_latency"], color="#3274a1")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlabel("p99 latency (simulation time units)")
    ax.set_title(f"Top {len(top)} Services by p99 Latency")
    ax.grid(axis="x", alpha=0.25)

    if "slo_ms_p99" in top.columns:
        x_pad = max(float(top["p99_latency"].max()) * 0.02, 1.0)
        for idx, (_, row) in enumerate(top.iterrows()):
            if pd.notna(row.get("slo_ms_p99")):
                ax.text(
                    float(row["p99_latency"]) + x_pad,
                    idx,
                    f"SLO {float(row['slo_ms_p99']):.0f}",
                    va="center",
                    fontsize=8,
                    color="#555555",
                )

    return _save(fig, figures_dir / FIGURE_NAMES["top_p99"])


def _plot_p99_vs_slo(
    df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["p99_latency", "slo_ms_p99"]
    if not _has_columns(df, required, "p99_vs_slo", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["p99_vs_slo"], "Missing p99/SLO columns")

    data = df[df["slo_ms_p99"].notna()].copy()
    if data.empty:
        return _placeholder(figures_dir / FIGURE_NAMES["p99_vs_slo"], "No SLO values available")
    data["slo_ratio"] = data["p99_latency"] / data["slo_ms_p99"].replace(0, pd.NA)
    if "slo_margin" not in data.columns:
        data["slo_margin"] = data["slo_ms_p99"] - data["p99_latency"]
    data = data.sort_values(
        ["slo_margin", "slo_ratio"],
        ascending=[True, False],
    ).head(top_n)
    labels = [_service_label(row) for _, row in data.iterrows()]
    y = range(len(data))

    fig, ax = plt.subplots(figsize=(11, max(4.5, 0.46 * len(data) + 1.6)))
    ax.barh(y, data["slo_ms_p99"], color="#d8dee6", label="SLO p99")
    ax.barh(y, data["p99_latency"], color="#e07647", label="Observed p99")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlabel("latency (simulation time units)")
    ax.set_title("Observed p99 Latency vs p99 SLO")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="lower right")

    for idx, (_, row) in enumerate(data.iterrows()):
        ratio = row.get("slo_ratio")
        if pd.notna(ratio):
            ax.text(
                float(row["p99_latency"]),
                idx,
                f" {float(ratio) * 100:.1f}% of SLO",
                va="center",
                fontsize=8,
                color="#3d3d3d",
            )

    return _save(fig, figures_dir / FIGURE_NAMES["p99_vs_slo"])


def _plot_slo_margin(
    df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["slo_margin"]
    if not _has_columns(df, required, "slo_margin", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["slo_margin"], "Missing slo_margin")

    data = df[df["slo_margin"].notna()].sort_values("slo_margin", ascending=True).head(top_n)
    if data.empty:
        return _placeholder(figures_dir / FIGURE_NAMES["slo_margin"], "No SLO margin values available")
    labels = [_service_label(row) for _, row in data.iterrows()]
    colors = ["#bb3e3e" if value < 0 else "#5f9e6e" for value in data["slo_margin"]]
    y = range(len(data))

    fig, ax = plt.subplots(figsize=(11, max(4.5, 0.46 * len(data) + 1.6)))
    ax.barh(y, data["slo_margin"], color=colors)
    ax.axvline(0, color="#333333", linewidth=1.2)
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlabel("SLO margin = slo_ms_p99 - p99_latency")
    ax.set_title("SLO Margin, Riskiest Services First")
    ax.grid(axis="x", alpha=0.25)
    return _save(fig, figures_dir / FIGURE_NAMES["slo_margin"])


def _plot_jitter(
    df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["jitter"]
    if not _has_columns(df, required, "jitter_by_service", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["jitter"], "Missing jitter")

    data = df.sort_values("jitter", ascending=False).head(top_n)
    if data.empty:
        return _placeholder(figures_dir / FIGURE_NAMES["jitter"], "No jitter rows available")
    labels = [_service_label(row) for _, row in data.iterrows()]
    y = range(len(data))

    fig, ax = plt.subplots(figsize=(11, max(4.5, 0.46 * len(data) + 1.6)))
    ax.barh(y, data["jitter"], color="#7b6aa8")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlabel("jitter: mean absolute consecutive latency delta")
    ax.set_title("Jitter by Service")
    ax.grid(axis="x", alpha=0.25)
    return _save(fig, figures_dir / FIGURE_NAMES["jitter"])


def _plot_violation_rate(
    df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["violation_rate"]
    if not _has_columns(df, required, "violation_rate_by_service", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["violation_rate"], "Missing violation_rate")

    data = df.sort_values(["violation_rate", "p99_latency"], ascending=[False, False]).head(top_n)
    if data.empty:
        return _placeholder(figures_dir / FIGURE_NAMES["violation_rate"], "No violation-rate rows available")
    labels = [_service_label(row) for _, row in data.iterrows()]
    y = range(len(data))

    fig, ax = plt.subplots(figsize=(11, max(4.5, 0.46 * len(data) + 1.6)))
    ax.barh(y, data["violation_rate"], color="#b84a62")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max(1.0, float(data["violation_rate"].max()) if len(data) else 1.0))
    ax.set_xlabel("violation rate")
    title = "SLO Violation Rate by Service"
    if float(pd.to_numeric(data["violation_rate"], errors="coerce").fillna(0).max()) == 0.0:
        title += " (Nominal: No SLO Violations)"
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.25)
    return _save(fig, figures_dir / FIGURE_NAMES["violation_rate"])


def _plot_window_p99(
    window_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["window_start", "p99_latency"]
    if not _has_columns(window_df, required, "window_p99_latency", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["window_p99"], "Missing window/p99 columns")

    selected = _select_window_services(window_df, summary_df, top_n)
    fig, ax = plt.subplots(figsize=(12, 6.5))
    plotted = 0
    for key, group in window_df.groupby(_group_cols(window_df), dropna=False):
        label = _key_to_label(key)
        if label not in selected:
            continue
        ordered = group.sort_values("window_start")
        ax.plot(
            ordered["window_start"],
            ordered["p99_latency"],
            marker="o",
            linewidth=1.8,
            label=label,
        )
        plotted += 1

    if plotted == 0:
        plt.close(fig)
        return _placeholder(figures_dir / FIGURE_NAMES["window_p99"], "No selected window rows")

    ax.set_xlabel("window start")
    ax.set_ylabel("p99 latency")
    ax.set_title("Windowed p99 Latency")
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    return _save(fig, figures_dir / FIGURE_NAMES["window_p99"])


def _plot_window_heatmap(
    window_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["window_start"]
    if not _has_columns(window_df, required, "window_slo_violation_heatmap", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["window_heatmap"], "Missing window_start")

    value_col = "violation_rate" if "violation_rate" in window_df.columns else "slo_violated"
    if value_col not in window_df.columns:
        return _placeholder(
            figures_dir / FIGURE_NAMES["window_heatmap"],
            "Missing violation columns",
        )

    selected = _select_window_services(window_df, summary_df, top_n)
    data = window_df.copy()
    data["service_label"] = [_service_label(row) for _, row in data.iterrows()]
    data = data[data["service_label"].isin(selected)]
    if data.empty:
        return _placeholder(figures_dir / FIGURE_NAMES["window_heatmap"], "No window rows")

    pivot = data.pivot_table(
        index="service_label",
        columns="window_start",
        values=value_col,
        aggfunc="max",
        fill_value=0,
    )
    pivot = pivot.reindex(selected)

    fig, ax = plt.subplots(figsize=(12, max(4.5, 0.38 * len(pivot) + 1.8)))
    image = ax.imshow(pivot.values, aspect="auto", cmap="Reds", vmin=0, vmax=max(1.0, pivot.values.max()))
    ax.set_yticks(range(len(pivot.index)), pivot.index)
    ax.set_xticks(range(len(pivot.columns)), [f"{float(x):.0f}" for x in pivot.columns], rotation=45, ha="right")
    title = "Windowed SLO Violation Heatmap"
    if float(pivot.values.max()) == 0.0:
        title += " (Nominal: No Violations)"
    ax.set_title(title)
    ax.set_xlabel("window start")
    ax.set_ylabel("service/message")
    fig.colorbar(image, ax=ax, label=value_col)
    return _save(fig, figures_dir / FIGURE_NAMES["window_heatmap"])


def _plot_top_link_latency(
    links_df: pd.DataFrame,
    figures_dir: Path,
    top_n: int,
    warnings: list[str],
) -> Path:
    required = ["src", "dst", "latency"]
    if not _has_columns(links_df, required, "top_link_latency", warnings):
        return _placeholder(figures_dir / FIGURE_NAMES["top_link"], "Missing link columns")

    df = links_df.copy()
    df["latency"] = pd.to_numeric(df["latency"], errors="coerce")
    group_cols = ["src", "dst"]
    if "message" in df.columns:
        group_cols.append("message")
    grouped = (
        df.dropna(subset=["latency"])
        .groupby(group_cols, dropna=False)["latency"]
        .agg(
            count="count",
            mean_latency="mean",
            p95_latency=lambda s: s.quantile(0.95),
            p99_latency=lambda s: s.quantile(0.99),
        )
        .reset_index()
        .sort_values("p95_latency", ascending=False)
        .head(top_n)
    )
    if grouped.empty:
        return _placeholder(figures_dir / FIGURE_NAMES["top_link"], "No link latency rows available")
    labels = [
        f"{_display_value(row.src)} -> {_display_value(row.dst)}"
        + (f" | {_display_value(row.message)}" if "message" in grouped.columns else "")
        for _, row in grouped.iterrows()
    ]
    y = range(len(grouped))

    fig, ax = plt.subplots(figsize=(11, max(4.5, 0.46 * len(grouped) + 1.6)))
    ax.barh(y, grouped["p95_latency"], color="#4d8f8f", label="p95")
    ax.scatter(grouped["mean_latency"], list(y), color="#1f2a36", s=28, label="mean")
    ax.scatter(grouped["p99_latency"], list(y), color="#b84a62", s=28, label="p99")
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlabel("link latency")
    ax.set_title("Top Link Hops by p95 Latency")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="lower right")
    return _save(fig, figures_dir / FIGURE_NAMES["top_link"])


def _write_html_report(
    html_path: Path,
    figures_dir: Path,
    figure_paths: dict[str, Path],
    input_files: dict[str, Path],
    summary_df: pd.DataFrame,
    warnings: list[str],
    top_n: int,
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = _summary_counts(summary_df)
    top_p99 = _table_html(
        summary_df.sort_values("p99_latency", ascending=False).head(top_n)
        if "p99_latency" in summary_df.columns
        else pd.DataFrame(),
        ["app", "module", "message", "count", "p95_latency", "p99_latency", "jitter", "slo_ms_p99"],
    )
    riskiest_margin = _table_html(
        summary_df[summary_df["slo_margin"].notna()]
        .sort_values("slo_margin", ascending=True)
        .head(top_n)
        if "slo_margin" in summary_df.columns
        else pd.DataFrame(),
        ["app", "module", "message", "count", "p99_latency", "slo_ms_p99", "slo_margin", "violation_rate"],
    )
    violations = summary_df
    if "slo_violated" in summary_df.columns:
        violations = summary_df[summary_df["slo_violated"].astype(bool)]
    else:
        violations = pd.DataFrame()
    violation_html = (
        _table_html(
            violations.sort_values("violation_rate", ascending=False),
            ["app", "module", "message", "count", "p99_latency", "slo_ms_p99", "violation_count", "violation_rate"],
        )
        if len(violations)
        else "<p class=\"nominal\">No SLO violations found.</p>"
    )
    interpretation = (
        "No SLO violations were found. This is a nominal scenario; stress "
        "scenarios will be needed before evaluating DriftGuard corrections."
        if summary["violated_groups"] == 0
        else "One or more service/message groups exceeded their p99 SLO."
    )

    image_blocks = []
    for key in FIGURE_NAMES:
        path = figure_paths.get(key)
        if path is None:
            continue
        rel = path.relative_to(html_path.parent)
        image_blocks.append(
            f"<section><h2>{html.escape(path.stem.replace('_', ' ').title())}</h2>"
            f"<img src=\"{html.escape(str(rel))}\" alt=\"{html.escape(path.stem)}\"></section>"
        )

    warning_html = ""
    if warnings:
        warning_html = "<h2>Warnings</h2><ul>" + "".join(
            f"<li>{html.escape(w)}</li>" for w in warnings
        ) + "</ul>"

    input_files_html = "<ul>" + "".join(
        "<li>"
        f"{html.escape(label)}: "
        f"{html.escape(str(path))}"
        f"{' (found)' if path.exists() else ' (missing)'}"
        "</li>"
        for label, path in input_files.items()
    ) + "</ul>"

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>DriftGuard SLO Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #1f2a36; background: #f7f8fa; }}
    h1, h2 {{ color: #1d3557; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .metric {{ background: white; border: 1px solid #dde3ea; border-radius: 6px; padding: 12px; }}
    .metric strong {{ display: block; font-size: 1.45rem; margin-top: 4px; }}
    table {{ border-collapse: collapse; width: 100%; background: white; margin: 12px 0 24px; font-size: 0.92rem; }}
    th, td {{ border: 1px solid #d8dee6; padding: 7px 9px; text-align: left; }}
    th {{ background: #e9eef5; }}
    img {{ max-width: 100%; background: white; border: 1px solid #dde3ea; border-radius: 6px; margin-bottom: 20px; }}
    .note, .nominal {{ background: #edf7ef; border-left: 4px solid #5f9e6e; padding: 12px; }}
    li {{ margin-bottom: 4px; }}
  </style>
</head>
<body>
  <h1>DriftGuard SLO / Latency Report</h1>
  <p>Generated: {html.escape(timestamp)}</p>
  <div class="summary">
    <div class="metric">Service/message groups<strong>{summary['groups']}</strong></div>
    <div class="metric">Total requests/events<strong>{summary['events']}</strong></div>
    <div class="metric">SLO-violated groups<strong>{summary['violated_groups']}</strong></div>
    <div class="metric">Maximum p99 latency<strong>{summary['max_p99']:.2f}</strong></div>
    <div class="metric">Maximum jitter<strong>{summary['max_jitter']:.2f}</strong></div>
    <div class="metric">Maximum violation rate<strong>{summary['max_violation_rate']:.3f}</strong></div>
  </div>
  <h2>Input Files Used</h2>
  {input_files_html}
  <h2>Interpretation</h2>
  <p class="note">{html.escape(interpretation)}</p>
  {warning_html}
  <h2>Top p99 Latency</h2>
  {top_p99}
  <h2>Riskiest SLO Margins</h2>
  {riskiest_margin}
  <h2>SLO Violations</h2>
  {violation_html}
  {''.join(image_blocks)}
</body>
</html>
"""
    html_path.write_text(html_text, encoding="utf-8")


def _summary_counts(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {
            "groups": 0,
            "events": 0,
            "violated_groups": 0,
            "max_p99": 0.0,
            "max_jitter": 0.0,
            "max_violation_rate": 0.0,
        }
    return {
        "groups": int(len(df)),
        "events": int(pd.to_numeric(df.get("count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "violated_groups": int(df["slo_violated"].astype(bool).sum()) if "slo_violated" in df.columns else 0,
        "max_p99": _numeric_max(df, "p99_latency"),
        "max_jitter": _numeric_max(df, "jitter"),
        "max_violation_rate": _numeric_max(df, "violation_rate"),
    }


def _numeric_max(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return 0.0
    return float(values.max())


def _table_html(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "<p>No rows available.</p>"
    visible = [col for col in columns if col in df.columns]
    table = df[visible].copy()
    for col in table.columns:
        if pd.api.types.is_float_dtype(table[col]):
            table[col] = table[col].map(lambda value: f"{value:.3f}" if pd.notna(value) else "")
    return table.to_html(index=False, escape=True)


def _select_window_services(
    window_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    top_n: int,
) -> list[str]:
    if not summary_df.empty and "p99_latency" in summary_df.columns:
        return [
            _service_label(row)
            for _, row in summary_df.sort_values("p99_latency", ascending=False).head(top_n).iterrows()
        ]
    data = window_df.copy()
    data["service_label"] = [_service_label(row) for _, row in data.iterrows()]
    return (
        data.groupby("service_label")["p99_latency"]
        .mean()
        .sort_values(ascending=False)
        .head(top_n)
        .index.tolist()
    )


def _group_cols(df: pd.DataFrame) -> list[str]:
    return [col for col in ["app", "module", "message"] if col in df.columns]


def _key_to_label(key) -> str:
    if not isinstance(key, tuple):
        key = (key,)
    values = [str(value) for value in key if pd.notna(value)]
    return " / ".join(values)


def _service_label(row: pd.Series) -> str:
    parts = []
    for col in ["app", "module", "message"]:
        if col in row and pd.notna(row[col]):
            parts.append(str(row[col]))
    return " / ".join(parts) or "all"


def _display_value(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _has_columns(
    df: pd.DataFrame,
    required: list[str],
    plot_name: str,
    warnings: list[str],
) -> bool:
    missing = [col for col in required if col not in df.columns]
    if missing:
        warnings.append(f"WARNING: skipped {plot_name}; missing columns: {missing}")
        return False
    return True


def _placeholder(path: Path, message: str) -> Path:
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12)
    return _save(fig, path)


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate DriftGuard SLO HTML report.")
    parser.add_argument("--results-dir", default="results_fog_simulation")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--window-file", default=None)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)

    report = generate_report(
        results_dir=args.results_dir,
        top_n=args.top_n,
        window_file=args.window_file,
        show=args.show,
    )
    for warning in report["warnings"]:
        print(warning)
    print(f"Generated report: {report['html_path']}")
    print("Generated figures:")
    for path in report["figure_paths"].values():
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
