# Capture Health Checker and Pass Graph validation

## Scope

- Feature branch: `feature/capture-health`
- Feature base: `63aadb68947c1b13325cc88aa93edb69d5896360`
- Replay host: Development x64 `qrendertest.exe`, RenderTest v1.45
- Host coordinator: CPython 3.12
- Replay worker: QRenderTest embedded Python 3.6 and the matching
  `rendertest.dll`
- Access mode: existing RDC files through public, read-only Replay API calls

The coordinator never launches or injects into a target process. Every capture
gets a separate replay worker, a bounded timeout, provenance validation against
the input SHA-256, atomic output files, and an isolated failure result.

## Unit and contract tests

Nine tests passed:

- deterministic canonical hashes and UTF-8 atomic JSON;
- RFC 4180 CSV handling for Unicode, commas, quotes, and newlines;
- health document status validation and stable input ordering;
- directory/manifest expansion, pairing metadata, and de-duplication;
- timeout termination and structured timeout failure;
- marker-independent action ownership and write-to-read dependencies;
- stable `ResourceFormat.Name()` serialization instead of SWIG pointer text;
- versioned capture-health and pass-graph JSON Schemas.

Evidence:

- `audit/followup/capture-health-unit-tests-final.log`
- `audit/followup/capture-health-error-paths.log`

The error-path integration run confirmed both a missing file
(`invalid-input`) and an invalid RDC (`FileUnrecognised`) are reported without
crashing the coordinator.

## Replay integration matrix

| Capture | SHA-256 prefix | Status | Actions | Draw | Dispatch | ExecuteIndirect | MultiAction | Shaders | Textures | Buffers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D3D11 baseline | `3FCD9528` | healthy | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| D3D12 baseline | `FA4729D7` | healthy | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| OpenGL baseline | `948ADBE9` | healthy | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| Vulkan baseline | `307461A7` | healthy | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| UE5 D3D12 owned | `0D7E5BA7` | healthy | 927 | 43 | 48 | 12 | 6 | 89 | 114 | 207 |

The UE5 main output was confirmed as 640x360
`R10G10B10A2_UNORM`. Its analysis produced 91 work-action signatures,
78 inferred passes, 377 action dependency edges, and 125 cross-pass edges.
The public API does not expose the RDC format version, so that field is
explicitly `unknown`; Replay version is confirmed as 1.45.

Evidence:

- `audit/followup/capture-health-dev-d3d11-fixed/`
- `audit/followup/capture-health-dev-api-batch/`
- `audit/followup/capture-health-dev-ue5-determinism-a/`
- `audit/followup/capture-health-dev-ue5-determinism-b/`
- `audit/followup/capture-health-ue5-determinism.json`

## Determinism and performance

Two independent UE5 replay workers produced semantically identical
`action-signatures.json`, `pass-graph.json`, `resource-summary.json`, and
`shader-summary.json` after removing only the generation timestamp. No marker
name participates in pass signatures.

- Three small API captures: 7.379 seconds wall-clock total.
- UE5 analysis: 22.2 to 29.0 seconds in-worker.
- UE5 peak process memory: approximately 1.02 GB.
- Worker startup and D3D11 analysis: 0.296 seconds in-worker.

Raw artifact file hashes differ between runs only because each envelope records
its own `generatedAt` timestamp. The contained capture analysis objects compare
identically.

## Resolved startup defect

QRenderTest's embedded `executeFile()` environment does not define
`__file__`. The first integration attempt therefore raised `NameError`, did not
emit `SystemExit`, and entered the normal UI event loop until the parent timeout
terminated it. The launcher now passes `RDX_ANALYSIS_ROOT` explicitly. A
progress journal makes the last completed replay stage visible in timeout
reports. The 30-second and 120-second failed attempts left no worker process
behind.

## Result

PASS. Capture Health Checker and marker-independent Pass Graph are suitable for
integration. Capture-format version remains a documented `UNKNOWN` because the
v1.45 public CaptureFile API does not expose it.
