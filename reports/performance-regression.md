# Performance regression record

## Measurements

| Operation | Baseline / earlier | Final | Observation |
|---|---:|---:|---|
| Development qrenderdoc startup | 0.395 s | 1.242 s | Both ready/responding. Single samples under different cache/system state; not a controlled regression comparison. |
| D3D12 Evidence worker | 2.125 s | 2.281 s | +0.156 s; within one-run noise and still a short bounded operation. |
| D3D12 Evidence exporter body | 0.187 s | 0.203 s | +0.016 s. |
| Final D3D12 Evidence command | not recorded in earlier report | 2.392 s | Open, replay, export, and atomic publication all included. |
| Action Visibility owned cases | n/a | 1.662-2.123 s per process | 13/13 passed earlier; mean approximately 1.89 s. |
| Three small Capture Health inputs | n/a | 7.379 s total | Existing feature validation. |
| UE5 Capture Health | n/a | 22.2-29.0 s | Existing deterministic two-worker validation. |
| UE5 analysis peak memory | n/a | approximately 1.02 GB | Replay worker measurement. |

No continuous profiling or statistically controlled benchmark was run. The
startup values are single observations and must not be presented as a proven
3.1x regression. The final Evidence run remained near the earlier focused
run and produced identical vertex/index counts.

## Build time

Development incremental build took 20.507 seconds. Release took 926.168
seconds because this worktree had no usable Release IPDB/IOBJ and performed
full LTCG; the prior clean stable-port Release rebuild took 661.37 seconds.
This comparison measures build cache state and added compilation units, not
runtime replay performance.

## Gate decision

No measured runtime operation showed a material, reproducible regression that
justifies blocking the integration. Startup performance should be measured
with a controlled repeated cold/warm protocol only if it becomes a release
criterion.

