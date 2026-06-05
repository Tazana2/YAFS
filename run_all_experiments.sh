#!/usr/bin/env bash

set -euo pipefail

RESULTS_DIR="results_experiments"

mkdir -p "$RESULTS_DIR"

echo "========================================"
echo "1. Running smoke tests"
echo "========================================"

uv run python -m fog_simulation.simulation.smoke_resource_accounting
uv run python -m fog_simulation.simulation.smoke_sink_registration
uv run python -m fog_simulation.simulation.smoke_transmission_units
uv run python -m fog_simulation.simulation.smoke_routing_policy
uv run python -m fog_simulation.simulation.smoke_scheduler_runs \
  --stop-time 300 \
  --results-root /tmp/yafs_scheduler_smoke

echo
echo "Smoke tests completed."
echo

echo "========================================"
echo "2. Running experiment scenarios"
echo "========================================"

for SCENARIO in \
  nominal \
  high_video_load \
  constrained_fog \
  degraded_gateway_link \
  cross_zone_congestion \
  strict_slo \
  burst_workload
do
  echo "----------------------------------------"
  echo "Running scenario: $SCENARIO"
  echo "----------------------------------------"

  uv run python -m fog_simulation.experiments.run_batch \
    --manifest "experiments/scenarios/${SCENARIO}.json" \
    --results-root "${RESULTS_DIR}/${SCENARIO}"

  uv run python -m fog_simulation.experiments.aggregate_results \
    --results-root "${RESULTS_DIR}/${SCENARIO}"

  echo "Finished: $SCENARIO"
  echo
done

echo "========================================"
echo "3. Consolidating global tables"
echo "========================================"

uv run python - <<'PY'
from pathlib import Path
import pandas as pd

root = Path("results_experiments")

for name in ["aggregate_summary.csv", "aggregate_comparison.csv"]:
    files = list(root.glob(f"*/{name}"))

    if files:
        df = pd.concat(
            [
                pd.read_csv(p).assign(source_scenario=p.parent.name)
                for p in files
            ],
            ignore_index=True
        )

        out = root / f"all_scenarios_{name}"
        df.to_csv(out, index=False)

        print("Wrote", out)
PY

echo
echo "All experiments completed successfully."