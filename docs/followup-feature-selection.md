# Windows analysis-suite feature selection

Status: implemented and integrated
Baseline: `25df92efcf0f5e138f3bc663fe54dcf4c8f72149`  
Official target: RenderDoc `v1.45` (`2fc0bc04cb95499635f63986a55bc6f67849dd9f`)

This document records the decision made before follow-up feature code is
written. Donor repositories are static evidence. No donor branch is merged,
no donor commit is cherry-picked, and no donor program, script, installer,
DLL, database, or captured binary is executed.

The detailed 224-commit classification is in
`audit/followup/donor-feature-matrix.csv`. Major source symbols and current
equivalents are in `audit/followup/donor-symbol-map.csv`.

## Selected scope

| Priority | Feature | Upstream status | Minimum layer | Decision |
| --- | --- | --- | --- | --- |
| P0 | Structured table export | Partially present as fixed-width clipboard copy and view-specific CSV | QRenderDoc utility and view adapters | Reimplement |
| P0 | Capture Health Checker | Not present as a stable batch artifact | External Python tool using the public Replay API | Reimplement |
| P0 | Action Visibility | Not present | QRenderDoc plus a narrow session-only Replay/Core override | Reimplement with stricter eligibility |
| P1 | MultiAction parent overlay | MultiAction children exist; parent overlay aggregation is absent | QRenderDoc selection propagation, Replay output, four replay backends | Reimplement |
| P1 | Draw Evidence Package | Replay primitives exist; unified package does not | External Python exporter plus a QRenderDoc entry point | Reimplement |
| P1 | Pass Graph and signatures | Resource usage exists; graph artifact does not | External Python tool | Reimplement |
| P2 | RDX Analysis Service | No upstream service | Isolated external process, JSON-RPC over stdio by default | Reimplement read-only subset |
| P2 | Draw package converter | No unified converter | External Python tool | Implement GLB validation and optional external FBX handoff |
| P3 | D3D12 compatibility changes | Most underlying mechanisms already exist; donor additions have no owned failing reproduction | None until a focused failure exists | Reference only |

## Feature decisions

### Structured table export

- User value: deterministic exchange of Mesh Viewer, Pipeline State, resource,
  descriptor, constant, action, texture, and buffer tables.
- Donor: `dlltools/8710666242a3c7e12245a2d4b0080635c4bc189c`.
- Confirmed donor behavior: adds extended row selection and builds a simple
  comma-delimited clipboard string.
- Gap in donor: quoting does not cover line breaks; sparse cell selection,
  JSON typing, metadata, failure recovery, and million-cell streaming are
  absent.
- Target implementation: one shared QRenderDoc serializer with CSV, TSV, and
  JSON writers. Views adapt their current proxy model so sorting and filtering
  are preserved.
- RDC format impact: none.
- Default replay impact: none.
- Test: RFC 4180 special characters, Unicode, empty cells, integer/float
  stability, `ResourceId`, proxy ordering, write failure, clipboard failure,
  cancellation, and a generated table larger than one million cells.
- Rollback: remove the view actions and shared serializer; existing copy and
  view-specific exports remain unchanged.

### Capture Health Checker and Pass Graph

- User value: reproducible triage of one capture, a directory, or a manifest
  without opening each capture manually.
- Donors: `agent/3f726986f167221a87e885161eb863d857a81704`
  for tool taxonomy and `jetbrains/e454210a4572ac631abd2744c65ad13f7c2f89eb`
  for out-of-process replay lifetime ideas.
- Target implementation: external Python package using only standard-library
  dependencies plus the RenderDoc Python Replay API supplied by the built
  product. It emits versioned JSON and CSV.
- Graph rule: edges derive from action resource reads/writes and relative
  order. Marker names are annotations, not graph identity.
- RDC format impact: none.
- Default replay impact: none.
- Test: all frozen D3D11, D3D12, OpenGL, Vulkan, and UE5 captures; invalid
  files; missing paths; cancellation; stable ordering; schema validation.
- Rollback: remove the external tool. No QRenderDoc/Core behavior changes.

### Action Visibility

- User value: counterfactual output analysis for individual or batched draw
  actions.
- Donor: `visibility/7ae99f5e53341a9a2b825f67b823a11c33ea4be1`
  and batch UI follow-up
  `visibility/140d1ba214be32b159317233d680561bd1bd6793`.
- Confirmed donor behavior: stores EIDs in the Event Browser and directly
  suppresses draw/dispatch calls in D3D11, D3D12, OpenGL, and Vulkan replay
  wrappers.
- Safety gap: the donor accepts all draw and dispatch flags, including indirect,
  mesh, ray, depth, stencil, and UAV-producing actions. It does not compute a
  dependency closure or preserve a documented safe-action policy.
- Target implementation:
  - only leaf, direct raster draw and compute-dispatch actions are eligible;
  - barriers, render-pass boundaries, clears, copies, resolves, queries,
    presents, ray/mesh dispatches, and MultiAction parents are never eligible
    in the first version;
  - actions with depth/stencil, writable storage/UAV, stream-out, or later
    resource consumers are classified risky and require an explicit session
    confirmation;
  - the replay override is session-only, disabled by default, and never
    serialised into the RDC;
  - presets are separate versioned JSON bound to capture SHA-256 and action
    signatures.
- Why Core is required: the public Replay API has no way to suppress a recorded
  draw while retaining surrounding state and resource transitions.
- RDC format impact: none.
- API impact: a session control method only; ordinary replay takes the exact
  existing path when its disabled-EID set is empty.
- Test: direct and indexed draws on D3D11/D3D12/Vulkan, depth-only and UAV
  classification, later-read classification, preset roundtrip, disable/enable
  output recovery, device-lost/error logs, and unchanged default replay.
- Rollback: clear the session override or build without the QRenderDoc actions;
  an empty override follows upstream replay.

### MultiAction and ExecuteIndirect overlay

- User value: a parent ExecuteIndirect/multi-draw selection displays the
  combined child draw overlay while an individual child remains individually
  selectable.
- Donor: `dlltools/9c5de35b5eeb19d0d96b156c53ad6451a72f3312`.
- Confirmed upstream state: v1.45 has parent/child action trees and separate
  selected/effective EIDs in `CaptureContext`, but the overlay replay call
  receives only the effective EID.
- Target implementation: propagate the selected parent EID to overlay refresh,
  derive a bounded list of drawable leaf children, and let each replay backend
  aggregate the Wireframe/Drawcall overlay with explicit state restoration.
- RDC format impact: none.
- Default impact: an empty child list runs the existing single-EID path.
- Test: owned D3D12 ExecuteIndirect, Vulkan multi-draw indirect, indexed
  indirect, instancing, parent/child map export, and individual-child parity.
- Rollback: omit selected-parent propagation or clear the aggregate list.

### Draw Evidence Package

- User value: one portable, versioned directory containing the geometry,
  shaders, pipeline, constants, texture bindings, outputs, and provenance for
  an action.
- Donors: `exporter/bb116a61d1747d82b386d332f972c99f98e31e34`
  and `exporter/0de72369916e34d0b23499eed4048b2ccc5cc833`.
- Donor limitations: application-specific automation, CSV round-trip, a direct
  FBX SDK dependency, machine assumptions, and incomplete provenance.
- Target implementation: external exporter using the public Replay API.
  Geometry is GLB plus raw buffers; unsupported or uncertain semantics remain
  raw and are labelled `unknown`. FBX conversion is a separate optional tool.
- Texture policy: analytical data is always lossless. PNG is used only for
  8-bit UNORM/SRGB or previews; float/depth data is EXR when supported or raw;
  BCn is DDS/raw; ASTC/ETC is KTX2/raw.
- RDC format impact: none.
- Test: schema, GLB validator, Blender background import, vertex/index parity,
  indexed/non-indexed, 16/32-bit indices, base vertex, instance, topology,
  texture format policy, and incomplete-data recovery.
- Rollback: remove the external package exporter and Tools menu registration.

### RDX Analysis Service

- User value: local LLMs and automation can inspect captures through a stable,
  auditable interface.
- Donor: `agent/3f726986f167221a87e885161eb863d857a81704`.
- Rejected donor surfaces: shader patching, experiment mutation, target
  process control, bundled databases/binaries, generated tool catalogs, and
  unbounded resource transfer.
- Target implementation: a read-only worker process. JSON-RPC over stdio is
  the default transport; optional loopback binding is explicit and localhost
  only. Large data is returned by file reference.
- Tools: open/close, summary, action listing/detail, pipeline, resource usage,
  shader/reflection, bounded buffer data, texture save, post-VS data, pass
  graph, evidence export, and signature comparison.
- RDC format impact: none.
- Test: protocol/schema validation, unknown method, invalid params, timeout,
  cancellation, maximum payload, worker crash, capture hash/EID provenance,
  and the read-only method allowlist.
- Rollback: stop/remove the service process. RenderDoc is unaffected.

## D3D12 compatibility decision

The donor commits
`51a21551a8465207ca8466c38be736cf395038a6`,
`e7047728dc49cddf531ee4a3dec06d72c33f9c93`, and
`c4d0181114d02352cdf363f9d3918e971b47a3a9` remain reference-only.

Confirmed in v1.45:

- capture and replay of embedded Agility SDK runtimes;
- `ID3D12SDKConfiguration1::CreateDeviceFactory`;
- hook-based fallback when the SDK selection interface is unavailable;
- pipeline-state stream and implicit-root-signature handling;
- ExecuteIndirect action expansion;
- enhanced barrier replay support.

Not confirmed:

- a failing owned capture requiring the donor device-version downgrade;
- a failing owned capture requiring the `SetSDKVersion` fallback;
- the donor commit's claimed root-signature alias-registration change (that
  code was not found in its diff);
- a valid case where broad NULL-PSO suppression is preferable to a surfaced
  replay failure.

No D3D12 behavior patch is selected without a minimal reproduction and
before/after evidence.

## Explicitly excluded

- hidden process/module behavior;
- remote DLL or function injection;
- thread-context/manual-map injection;
- configurable inline/IAT hook evasion;
- binary/PE identity replacement;
- Android/APK/emulator code in the Windows build;
- Autodesk FBX SDK in RenderDoc or QRenderDoc;
- shader/capture mutation in the RDX service;
- unknown donor binaries, databases, captured artifacts, and installers.
