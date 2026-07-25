# Windows Analysis Suite user guide

This guide covers the follow-up tools layered on the RenderTest v1.45 Windows
port. They inspect existing captures and do not launch, inject into, or modify
a target process. Visibility changes are replay-session state only; exported
files never modify the source RDC.

## Structured table export

Open a capture, focus a supported table, and select cells or rows. Use
`Tools > Analysis Suite`:

- **Copy Focused Table as TSV**
- **Copy Focused Table as TSV with Headers**
- **Export Focused Table to CSV...**
- **Export Focused Table to CSV without Headers...**
- **Export Focused Table to JSON...**

The active model supplies the rows, so current sorting and filtering are
preserved. CSV is UTF-8 and RFC 4180 quoted. JSON records both the display
string and a typed raw value when available. File exports are atomic.

## Action Visibility

Action Visibility is supported for D3D11, D3D12, and Vulkan direct leaf Draw,
DrawIndexed, and compute Dispatch actions.

In the Event Browser, select one or more eligible actions and open the context
menu:

- **Disable Selected Direct Actions**
- **Enable Selected Direct Actions**
- **Clear All Disabled Actions**
- **Save Capture-Bound Preset...**
- **Load Capture-Bound Preset...**
- **Export Disabled Action List...**

The UI confirms known outputs and later resource usage before applying a
counterfactual replay. Indirect/MultiAction children, mesh/ray dispatches,
barriers, render-pass boundaries, clears, copies, resolves, queries, and
presents are protected. Reopen the capture or clear the set to return to the
ordinary replay path.

Presets are bound to the RDC SHA-256 and rejected if loaded against a different
capture. A disabled-action report is deliberately not loadable as a preset.

## MultiAction and ExecuteIndirect overlay

Selecting a MultiAction or ExecuteIndirect parent retains its selected EID
while replay uses the effective child state. Drawcall and Wireframe overlays
collect only matching leaf draws that write the displayed target. Selecting an
individual child keeps the ordinary single-action overlay path.

The parent/child map is available as
`reports/multiaction-action-map.json`. Unsupported mixed work remains visible
as individual children instead of receiving a guessed parent state.

## Draw Evidence Package

Select a leaf Draw/Dispatch action, then use:

`Tools > Analysis Suite > Export Selected Action Evidence...`

Choose an existing output directory. The UI starts a dedicated qrenderdoc
worker and exposes Cancel. Installed layouts may set
`RENDERDOC_ANALYSIS_SUITE_ROOT` to the directory containing
`draw-evidence-package`.

Headless example:

```powershell
python tools\draw-evidence-package\draw-evidence.py `
  --qrenderdoc .\x64\Development\qrendertest.exe `
  --capture D:\captures\frame.rdc `
  --event 211 `
  --output D:\evidence `
  --timeout-seconds 60 `
  --max-resource-mib 64
```

The package contains versioned JSON, input/Post-VS GLB, raw geometry buffers,
shader reflection/disassembly, pipeline state, constants, lossless textures,
outputs, hashes, and provenance. Unknown semantics stay raw and are labelled;
they are not inferred.

Validate or optionally convert GLB outside RenderDoc:

```powershell
python tools\draw-package-converter\draw-package-converter.py validate `
  D:\evidence\frame_or_draw_capture_211

python tools\draw-package-converter\draw-package-converter.py fbx `
  --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' `
  --input D:\evidence\frame_or_draw_capture_211\geometry\post_vs.glb `
  --output D:\evidence\post_vs.fbx
```

FBX conversion uses an explicitly supplied Blender in background,
factory-startup, disabled-autoexec mode and never overwrites an existing FBX.

## Capture Health and Pass Graph

Analyse one RDC, a directory, or a JSON manifest:

```powershell
python tools\rdx-analysis-service\rdx-health.py health `
  --qrenderdoc .\x64\Development\qrendertest.exe `
  --input D:\captures `
  --output D:\capture-health
```

Use `--recursive` for nested directories and `--allow-partial` when a batch may
contain invalid captures. Outputs include capture health JSON/CSV, pass graph,
action signatures, resource/shader summaries, MultiAction maps, and an error
log. Pass identity is derived from data flow and pipeline structure, not only
marker text.

## Read-only RDX Analysis Service

Start the local newline-delimited JSON-RPC 2.0 stdio service:

```powershell
python tools\rdx-analysis-service\rdx-service.py `
  --qrenderdoc .\x64\Development\qrendertest.exe `
  --output-root D:\rdx-service-data
```

Send `initialize`, then `open_capture`; use the returned session ID with query
methods. Large buffers, textures, Post-VS data, and evidence packages are
returned as bounded file references below `--output-root`. The service has no
network listener and exposes no capture, injection, target-control, or mutation
method. Protocol details are in `docs/rdx-service-api.md`.

## Troubleshooting and rollback

- If the Evidence menu cannot find its worker, set
  `RENDERDOC_ANALYSIS_SUITE_ROOT` to the tools directory.
- If replay work times out, inspect the job `stderr.log`, `stdout.log`, and
  progress/result JSON below the selected output root.
- If Action Visibility output is unexpected, clear all disabled actions and
  replay the event again.
- External tools can be removed without changing RenderDoc. Structured export
  and menu actions can be reverted independently. Visibility and MultiAction
  Core changes are inactive on their empty/default state and introduce no RDC
  format change.
