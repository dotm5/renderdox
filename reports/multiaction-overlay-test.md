# MultiAction / ExecuteIndirect overlay validation

## Result

Status: **IMPLEMENTED; focused runtime gate pending the final Development build**

- Parent selection and effective replay EID are passed atomically.
- Only Drawcall and Wireframe overlays expand a parent into child draws.
- Only leaf Drawcall descendants that write the displayed color/depth target are included.
- D3D11, D3D12, OpenGL, and Vulkan retain the ordinary single-child path when the map is empty.
- D3D12 and Vulkan restore the overlay render state before each child replay.
- Action Visibility remains compatible because indirect and MultiAction descendants are protected.

## Evidence

The read-only analysis worker opened two owned captures and produced the full map in
`audit/followup/multiaction-overlay-map/multiaction-action-map.json`.
The committed, path-free review extract is `reports/multiaction-action-map.json`.

| Capture | SHA-256 | Parents | Child draws | Coverage |
| --- | --- | ---: | ---: | --- |
| D3D12 Execute Indirect | `CA6D84AC0BD7A19AFCDD85841ED5D921A4C3DE519D41ABDFB1B371B889F4B11A` | 14 | 25 | ExecuteIndirect, zero-count culling, 8-child batch, 1024 instances |
| Vulkan Indirect | `3619EFC9DA03142CE65B7C6033B280D2AEF40D09E9D038ADEED0717FF647BD3C` | 8 | 18 | indexed/non-indexed multi-draw indirect, count-buffer draws, multi-instance |

The pure mapping tests cover nested MultiAction nodes, exclusion of dispatches, target filtering,
ordinary child selection, and an unrelated effective EID. The C++ test mirrors the same invariants
inside `ReplayOutput`.

## Donor comparison

Source intent: `renderdoc-dllinject` commit
`9c5de35b5eeb19d0d96b156c53ad6451a72f3312`.

The donor used a separate mutable selected-EID setter and a public driver list. The new
implementation uses one atomic API call, encapsulates the transient driver list, validates that the
effective EID belongs to the selected parent, recursively collects leaf draws, filters by displayed
target, and clears the list immediately after overlay rendering.

## Rollback

Selecting a child uses the unchanged single-action path. Source rollback is confined to the
MultiAction feature commit; no RDC or preset conversion is required.
