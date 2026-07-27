# Windows analysis-suite architecture

## Design constraints

The stable Windows port remains the base. New behavior is layered above the
existing Core/UI/CMD/Shim identity contract and official v1.45 replay code.

The architecture follows five rules:

1. prefer an external tool over QRenderDoc, and QRenderDoc over Replay/Core;
2. use the public Replay API whenever it can express the operation;
3. keep session overrides disabled by default and outside RDC serialisation;
4. isolate capture replay and large export work from the UI process;
5. keep every artifact versioned, deterministic, and tied to a capture hash.

## Components

```text
QRenderDoc
  ├─ StructuredTableExport
  ├─ Analysis Suite menu
  ├─ ActionVisibilityController
  └─ selected-parent EID propagation
          │
          ▼
ReplayController / ReplayOutput
  ├─ session-only action visibility set
  └─ bounded MultiAction overlay child list
          │
          ▼
D3D11 / D3D12 / Vulkan / OpenGL replay backends

qrenderdoc --python / RenderDoc Python Replay API
          │
          ▼
rdx-analysis worker process
  ├─ capture-health
  ├─ pass-graph and action signatures
  ├─ draw-evidence exporter
  └─ read-only JSON-RPC dispatcher
          │
          ├─ versioned JSON/CSV/GLB/raw artifacts
          └─ stdio JSON-RPC to local clients

draw-package-converter
  ├─ validates evidence package and GLB
  ├─ prepares Blender import validation
  └─ optional explicit FBX handoff outside RenderDoc
```

## Trust and process boundaries

| Boundary | Allowed | Not allowed |
| --- | --- | --- |
| RenderDoc replay process | Open and replay an RDC, inspect resources, save requested outputs | Target launch/injection, donor binaries, capture mutation |
| QRenderDoc UI | User-triggered exports, session-only visibility state, progress/cancel | Silent background mutation, hidden network listener |
| Analysis worker | Read-only public Replay API calls, bounded file output | Public network bind, target control, shader replacement |
| Client protocol | Versioned small JSON requests/responses, file references for large data | Inline unbounded binary payloads |
| Converter | Read package files and write a separate conversion directory | Load FBX SDK into RenderDoc/QRenderDoc |

The default transport is newline-delimited JSON-RPC 2.0 over inherited stdio.
No listener is created by default. If loopback transport is enabled in the
future it must bind only to `127.0.0.1`/`::1`, require an explicit random token,
and remain off in default builds.

## Structured table export

`StructuredTableExport` accepts a `QAbstractItemModel`, an ordered selection,
visible column mapping, options, and provenance metadata.

Writers:

- TSV clipboard writer: tab/newline escaped for spreadsheet paste;
- RFC 4180 CSV writer: CRLF records, quotes fields containing comma, quote,
  CR, or LF, and doubles quotes;
- JSON writer: keeps `display` and a JSON-compatible `raw` value when the model
  exposes one;
- file writer: `QSaveFile` atomic commit, UTF-8 without locale dependence.

Sorting and filtering are preserved by serialising from the active proxy model.
Large exports stream rows and report progress/cancellation. UI collection of
model data occurs on the UI thread; file encoding/writing uses bounded chunks.

Provenance includes schema version, capture SHA-256, EID, API, product version,
port commit, UTC timestamp, selected rows/columns, and whether headers are
present.

## Action Visibility

Visibility state is a replay-session property:

```text
capture SHA-256
  └─ visibility preset
       ├─ schema version
       ├─ action signatures
       ├─ disabled EIDs
       └─ explicit risk acknowledgements
```

The state is never written into an RDC. The empty set is a fast, exact upstream
path.

Eligibility is calculated before the action can be toggled:

| Action/property | Default policy |
| --- | --- |
| Leaf direct Draw / DrawIndexed | Eligible after resource-side-effect check |
| Depth/stencil write | Risky; explicit session confirmation |
| Writable UAV/storage or stream-out | Risky; explicit session confirmation |
| Output later read by another action | Risky; explicit session confirmation |
| Leaf direct compute dispatch | Eligible after resource-side-effect confirmation |
| Mesh dispatch, ray dispatch | Ineligible in first version |
| ExecuteIndirect/MultiAction parent | Ineligible; choose a verified child |
| Barrier/layout transition | Ineligible |
| Begin/end render pass | Ineligible |
| Clear/copy/resolve | Ineligible |
| Query/timestamp/present | Ineligible |

Replay retains all state-setting, barrier, render-pass, clear/copy/resolve, and
query operations. Only the final eligible draw command is suppressed. Backend
draw callbacks and overlay callbacks receive consistent EIDs. Every applied
override logs its capture hash, EID, action signature, eligibility result, and
acknowledged risks.

## MultiAction overlay

The UI already tracks a selected EID and an effective EID. Overlay refresh is
extended to receive both. When the selected EID names a `MultiAction` parent,
ReplayController resolves only drawable leaf descendants within that parent.

Guards:

- maximum child count is bounded;
- every child must be inside the selected parent's subtree;
- mixed draw/dispatch parents reject unsupported children;
- individual child selection leaves the existing single-EID path untouched;
- API backends save/restore render state around aggregate replay;
- errors identify the parent and child EID rather than silently showing an
  empty overlay.

The child mapping can be exported independently for test and evidence use.

## External analysis package

The Python package is split into pure-data code and a thin RenderDoc adapter:

```text
tools/rdx-analysis-service/
  rdx_analysis/
    protocol.py
    worker.py
    replay.py
    health.py
    pass_graph.py
    evidence.py
    glb.py
    schema.py
    cli.py
  tests/
```

Pure-data modules are tested with the system Python. Replay integration runs
inside the current product's Python environment so the exact `renderdoc` module
matches the built binaries.

The worker owns at most one replay controller per session and always calls
`Shutdown()` in a `finally` path. The parent process enforces timeouts and may
terminate only its own worker. Requests carry cancellation IDs; file exports
write to a temporary sibling directory and atomically rename on success.

## Evidence package

The package is immutable after a successful atomic commit. Every JSON file has
`schemaVersion`; `provenance.json` binds:

- package ID;
- capture absolute path recorded only in local provenance;
- capture SHA-256 and byte size;
- API and driver;
- RenderDoc/product version and commit;
- EID and action signature;
- export options;
- start/end UTC timestamps;
- warnings, unknowns, and fidelity classifications.

GLB is the portable geometry representation. Input and post-VS streams are
separate scenes/files. Raw buffers and layout metadata remain the source of
truth when semantics are uncertain. No normal, tangent, UV, color, coordinate
space, or transform is invented.

## Schemas and compatibility

The initial schema family uses major version `1`. Readers:

- must reject an unsupported major version;
- may ignore unknown fields in a supported major version;
- must not reinterpret `unknown` as an empty/zero value;
- must validate relative package paths and reject traversal;
- must use UTF-8 JSON;
- must keep capture hashes and EIDs in responses.

No new RDC chunk or serialised API field is introduced.

## Failure and rollback

| Failure | Behavior |
| --- | --- |
| UI export write fails | Keep original file, show/log path and OS error |
| Clipboard unavailable | Keep generated data available for file export; log failure |
| Analysis worker crashes | Parent reports structured worker failure; QRenderDoc remains alive |
| Replay fails | Close controller/capture and record the RenderDoc result |
| Evidence sub-export fails | Abort atomic package commit, retain an error log in a separate failed-work directory |
| Visibility replay fails | Clear override, replay the baseline event, and surface the backend error |
| Aggregate overlay fails | Fall back to individual effective-EID overlay and report unsupported parent |

Each feature is removable independently. External tools have no load-time
effect on RenderDoc. The two Core features use empty/default state to preserve
the existing path.
