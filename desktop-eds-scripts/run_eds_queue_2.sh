#!/bin/bash
set -e

cd /home/jovyan/work-easi-eds
mkdir -p logs
rm -f nohup.out

MAX_JOBS=2

wait_for_slot () {
  while [ "$(jobs -rp | wc -l)" -ge "$MAX_JOBS" ]; do
    sleep 30
  done
}

run_eds () {
  tile="$1"
  start="$2"
  end="$3"
  mode="$4"

  wait_for_slot

  echo "Starting $tile | $mode | $start to $end"

  nohup python /home/jovyan/work-easi-eds/scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py \
    --tile "$tile" \
    --start-date "$start" \
    --end-date "$end" \
    --s3-bucket dcceew-eds-data \
    --s3-prefix "AROAZ6PFZYT4B4C7MNRHV:robotmcgregor/eds" \
    --work-dir "/home/jovyan/scratch/eds-work-processing-${tile}-${mode}" \
    --cloud-max 40 \
    --lookback 10 \
    --copy-to-home \
    --verbose \
    --diagnostics \
    --dlj-troubleshoot \
    $( [ "$mode" = "run-no-auto-sr-scale" ] && echo "--legacy-no-auto-sr-scale" ) \
    $( [ "$mode" = "run-forced-10000" ] && echo "--legacy-sr-scale 10000" ) \
    $( [ "$mode" = "run-baseline-include-nodata" ] && echo "--legacy-baseline-include-nodata" ) \
    --run-id "${mode}-${tile}" \
    > "logs/eds_${tile}_${mode}.log" 2>&1 &

  sleep 2
}

# ==========================
# TILE QUEUE
# ==========================

run_eds p089r078 2025-07-01 2026-01-17 run-no-auto-sr-scale
run_eds p089r078 2025-07-01 2026-01-17 run-auto-scale
run_eds p089r078 2025-07-01 2026-01-17 run-forced-10000
run_eds p089r078 2025-07-01 2026-01-17 run-baseline-include-nodata

run_eds p089r079 2025-06-07 2026-01-25 run-no-auto-sr-scale
run_eds p089r079 2025-06-07 2026-01-25 run-auto-scale
run_eds p089r079 2025-06-07 2026-01-25 run-forced-10000
run_eds p089r079 2025-06-07 2026-01-25 run-baseline-include-nodata

run_eds p089r080 2025-06-07 2026-01-25 run-no-auto-sr-scale
run_eds p089r080 2025-06-07 2026-01-25 run-auto-scale
run_eds p089r080 2025-06-07 2026-01-25 run-forced-10000
run_eds p089r080 2025-06-07 2026-01-25 run-baseline-include-nodata

wait
echo "All queued EDS jobs completed."
