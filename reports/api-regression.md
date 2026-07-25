# API regression record

## Scope decision

The final gate was deliberately shortened at user request. The earlier frozen
baseline and feature-specific cross-API evidence remain authoritative; the
final integration did not repeat the approximately two-hour capture matrix.
It ran one static/unit round, both x64 builds, one UI startup, and one
representative D3D12 replay/export.

## Evidence matrix

| API / surface | Frozen baseline | Feature-specific evidence | Final short gate | Status |
|---|---|---|---|---|
| D3D11 | Existing capture opened/replayed | Action Visibility direct draw/indexed/dispatch/stream-out cases passed | Not repeated | PASS with retained evidence |
| D3D12 | Existing capture and owned UE5 capture opened/replayed | Action Visibility, ExecuteIndirect map, Capture Health, RDX service passed | EID 211 replay/evidence export passed | PASS |
| Vulkan | Existing capture opened/replayed | Action Visibility and multi-draw indirect map passed | Not repeated | PASS with retained evidence |
| OpenGL | Existing capture opened/replayed | Capture Health batch passed; no Visibility support by design | Not repeated | PASS with retained baseline evidence |
| UE5 D3D12 owned | 927 actions, 43 draws, 48 dispatches, 12 ExecuteIndirect names, 6 MultiAction; replay passed | Capture Health/Pass Graph deterministic across two workers | Not repeated | PASS with retained evidence |

The final D3D12 action was EID 211 under ExecuteIndirect parent EID 210 in
capture SHA-256
`CA6D84AC0BD7A19AFCDD85841ED5D921A4C3DE519D41ABDFB1B371B889F4B11A`.
Replay and export succeeded, and the source RDC remained read-only.

## UI/Core contract

Development qrenderdoc reached an input-idle, responding state in 1.242
seconds. Final builds emitted `rendertest.dll`, `qrendertest.exe`,
`rendertestcmd.exe`, `rendertestshim64.dll`, and matching Python bindings under
both x64 configurations. The follow-up changes do not change the product
identity manifest or RDC serialization.

## Result boundary

No final claim is made that every cross-API pixel output was rechecked after
the documentation-only final commit. That expensive matrix was intentionally
omitted; retained feature evidence and the final D3D12 gate are reported
separately so the boundary is explicit.
