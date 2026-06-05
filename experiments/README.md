# DriftGuard Experiments

This folder contains reproducible experiment manifests for the YAFS
DriftGuard smart-city simulation.

## Scenarios

Available manifests live in `experiments/scenarios/`:

- `nominal.json`: baseline smart-city workload with no induced degradation.
- `high_video_load.json`: increases video source rate and video payload size.
- `constrained_fog.json`: reduces fog CPU, RAM, and node bandwidth.
- `degraded_gateway_link.json`: reduces gateway-link bandwidth and increases gateway-link propagation delay.
- `cross_zone_congestion.json`: reduces inter-zone bandwidth and increases inter-zone propagation delay.
- `strict_slo.json`: halves post-run SLO thresholds for stricter violation analysis.
- `burst_workload.json`: applies a deterministic high-rate burst window to all sources.

## Run one scenario

From the repository root:

```bash
python -m fog_simulation.experiments.run_batch \
  --manifest experiments/scenarios/nominal.json \
  --results-root results_experiments/nominal
```

To run another scenario, switch both the manifest and results folder:

```bash
python -m fog_simulation.experiments.run_batch \
  --manifest experiments/scenarios/high_video_load.json \
  --results-root results_experiments/high_video_load
```

For quick validation:

```bash
python -m fog_simulation.experiments.run_batch \
  --manifest experiments/scenarios/degraded_gateway_link.json \
  --results-root /tmp/yafs_degraded_gateway_smoke \
  --stop-time 300 \
  --seeds 1,2 \
  --no-reports
```

Each manifest runs both current non-RL schedulers across multiple seeds using
the configured routing policies.

## Results layout

The batch runner writes one deterministic directory per run:

```text
results_experiments/nominal/
  manifest.json
  run_index.csv
  aggregate_raw.csv
  aggregate_summary.csv
  aggregate_summary.md
  aggregate_comparison.csv
  default_latency_seed_1/
  latency_resource_latency_seed_1/
```

Each run directory contains the normal YAFS traces, SLO summaries,
`experiment_config.json`, and `run_metrics.json`.

## Re-aggregate existing results

```bash
python -m fog_simulation.experiments.aggregate_results \
  --results-root results_experiments/nominal
```

## Interpreting aggregate_summary.csv

`aggregate_summary.csv` is a long-form table grouped by:

- `scenario_name`
- `scheduler_type`
- `routing_policy`

For each metric it reports `n`, `mean`, `std`, `min`, `max`, and
`ci95_half_width`, where:

```text
ci95_half_width = 1.96 * std / sqrt(n)
```

`aggregate_comparison.csv` compares `latency_resource` against `default`
for each scenario and routing policy.

Stress results should be read comparatively: use the same scenario, routing
policy, seed set, and topology seed behavior when comparing schedulers.
Negative percentage deltas in `aggregate_comparison.csv` mean the candidate
`latency_resource` scheduler reduced the metric relative to `default`.

## Post-run metrics

The current SLO, p95/p99 latency, jitter, and violation metrics are computed
after each simulation from generated CSV traces. They do not feed back into
placement, routing, migration, or scheduling decisions at runtime.

## Limitations

This phase does not add RL, PPO, DQN, Gymnasium, runtime migration,
rescheduling, or scheduler scoring changes. Stress knobs are applied before a
simulation starts; they do not model runtime failures or live recovery.
`strict_slo` changes post-run SLO thresholds only, so it affects violation
analysis rather than service execution. Burst windows use source-local elapsed
time in the arrival distribution, not a global event controller.
