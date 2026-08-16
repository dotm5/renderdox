# RDX analysis service

This directory contains the out-of-process, read-only capture analysis tools for
the Windows analysis suite.

The host CLI runs on a normal system Python (3.8 or newer). Each capture is
opened in a separate QRenderDoc embedded-Python worker so the `renderdoc` module
always matches the built DLL and a replay failure cannot corrupt the batch
coordinator.

No command in this package launches or injects into a target program. The worker
only calls the public replay API on an existing capture.

## Capture health

```powershell
python tools\rdx-analysis-service\rdx-health.py health `
  --qrenderdoc D:\rdoc-port\dcomp-isolated\x64\Development\dgcoreui.exe `
  --input D:\captures `
  --output D:\reports\capture-health
```

Inputs may be individual `.rdc` files, directories, or JSON manifests. Add
`--recursive` to recurse into directories. Output is written atomically and
contains:

- `capture-health.json` and `capture-health.csv`
- `pass-graph.json`
- `action-signatures.json`
- `resource-summary.json`
- `shader-summary.json`
- `multiaction-action-map.json`
- `errors.log`

The command returns non-zero when any input cannot be analysed. Use
`--allow-partial` when a batch should return success while retaining per-capture
errors.

Every worker receives its script root through `RDX_ANALYSIS_ROOT`. DCompUI's
embedded `executeFile()` environment does not define `__file__`, so scripts must
not infer their import root from that name. `progress.log` records the last
completed replay stage and is included in timeout diagnostics.

`pass-graph.json` derives data-flow edges from resource usage and computes pass
signatures from shaders, pipeline state, resource sets, viewport, render-target
formats, action kind, and relative order. Marker text is intentionally excluded.

## Tests

Pure-data tests have no RenderDoc dependency:

```powershell
Push-Location tools\rdx-analysis-service
python -m unittest discover -s tests -v
Pop-Location
```

Replay integration tests are performed by running the CLI against the frozen
D3D11, D3D12, OpenGL, Vulkan, and UE5 captures.

## Local JSON-RPC service

`rdx-service.py` exposes the same analysis model plus bounded, isolated Replay
queries over newline-delimited JSON-RPC 2.0 on stdin/stdout:

```powershell
python tools\rdx-analysis-service\rdx-service.py `
  --qrenderdoc D:\rdoc-port\dcomp-isolated\x64\Development\dgcoreui.exe `
  --output-root D:\rdx-service-data
```

The service is local-only and capture-read-only. Binary resources are returned
as SHA-256 file references below `--output-root`; they are never embedded into
JSON. Requests support timeout and `$/cancelRequest`. See
`docs/rdx-service-api.md` and `schemas/rdx-protocol.schema.json`.
