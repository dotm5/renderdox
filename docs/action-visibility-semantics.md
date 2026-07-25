# Action Visibility replay semantics

Action Visibility is a replay-only counterfactual analysis feature. It does not edit, annotate, or
re-serialise the capture. The disabled set starts empty for every capture and exists only in the
active replay controller unless the user explicitly saves a capture-bound JSON preset.

## Supported work

The public `ReplayController::SetDisabledActions` API accepts exact event IDs only when
`ActionDescription::IsActionVisibilityEligible()` returns true. Eligibility is intentionally
conservative:

- a leaf `Drawcall` or compute `Dispatch` is eligible;
- an action with children is not eligible;
- `Indirect`, `MultiAction`, `Auto`, `MeshDispatch`, and `DispatchRay` are not eligible;
- a child under an `Indirect` or `MultiAction` ancestor is not eligible;
- D3D11, D3D12, and Vulkan replay drivers support the feature;
- other APIs reject the requested set without changing replay.

Clear, copy, resolve, barriers/layout transitions, render-pass begin/end, queries, timestamps, and
present are never omitted.

## Backend invariants

D3D11 tests the current replay EID immediately around the direct draw/dispatch call. D3D12 and
Vulkan resolve the current serialised chunk through the existing `ActionUse` map, so the decision
does not depend on an `ActionCallback`. This matters because ordinary replay has no callback and the
older donor implementation consequently observed EID zero.

The wrappers still deserialise the command, advance replay bookkeeping, execute state-management
commands, and run normal callback handling. Only the underlying direct work submission is skipped.
Calling `SetFrameEvent(..., force=true)` after changing the set refreshes all viewers.

## UI contract

The Event Browser `Action` column shows `Enabled` or `Disabled` only for eligible exact actions.
Users may click a cell, press Space for the selected rows, or use the Action Visibility context
submenu to:

- disable or enable one or more selected direct actions;
- clear the complete disabled set;
- save or load a capture-bound preset;
- export a non-loadable disabled-action report.

Disabling prompts with the known color/depth outputs and whether those resources have later usage.
The prompt explicitly states that UAV/storage, stream-output, depth/stencil, and downstream effects
may extend beyond the enumerated outputs. Selection and scroll position are restored after replay.

## Presets and provenance

Presets conform to `schemas/action-visibility-preset.schema.json`. They contain schema version,
capture SHA-256, capture filename (not an absolute path), API, RenderDoc version, port commit, UTC
timestamp, disabled EIDs, action names/flags, and known color/depth outputs.

Loading requires:

- schema version 1;
- kind `renderdoc-action-visibility-preset`;
- `loadable: true`;
- exact SHA-256 match with the open RDC;
- integral event IDs in the unsigned 32-bit range;
- backend revalidation of every event ID.

Writes use `QSaveFile`, so cancellation or an I/O failure cannot publish a partial preset. Exported
reports use a different kind and are deliberately rejected by the preset loader.

## Known limits

- Indirect and multi-action children remain protected until their per-child replay semantics are
  proven by dedicated overlay tests.
- Mesh and ray dispatches are not yet supported.
- `ActionDescription` directly identifies color and depth outputs, but not every UAV/storage or
  stream-output binding. The confirmation is conservative and calls this limitation out.
- Visibility state is local to one replay controller; two QRenderDoc instances do not share it.

## Rollback

At runtime, use **Clear All Disabled Actions** or reopen the capture. At source level, revert the
Action Visibility commits; no RDC migration or data cleanup is required.
