# Draw Evidence Package validation

## Focused validation

The exporter was run once against the owned RenderDoc test capture below. This
is the representative fast gate requested for this iteration; the earlier
multi-hour API smoke matrix was not repeated.

| Field | Result |
|---|---|
| Capture | `D3D12_Execute_Indirect.rdc` |
| Capture SHA-256 | `CA6D84AC0BD7A19AFCDD85841ED5D921A4C3DE519D41ABDFB1B371B889F4B11A` |
| Action | child Draw EID `211` of ExecuteIndirect parent EID `210` |
| Worker wall time | `2125 ms` |
| Exporter time | `187 ms` |
| Package | `D:\rdoc-port\audit\followup\draw-evidence-validation\run-20260726\frame_or_draw_D3D12_Execute_Indirect_211` |
| Result | PASS |

Both `geometry/input.glb` and `geometry/post_vs.glb` passed the built-in GLB 2
structural validator. Each contains 6 vertices and 6 indices, equal to the
selected RenderDoc action count. Input geometry fidelity is `exact`; Post-VS
geometry is `approximation` because clip positions are explicitly perspective
divided for interchange.

The package contains action/resource-usage documents, raw input and Post-VS
buffers, shader reflection and disassembly, shader/disassembly hashes, D3D12
root-signature and resource-state documents, PSO-related state, the partial
ExecuteIndirect record, a lossless output PNG, preview PNG, and SHA-256 for
every published artifact. Publication used a staging directory followed by an
atomic rename.

## Boundaries

- Exact original DXBC/DXIL container bytes: UNKNOWN; the public Replay API
  exposes reflection and disassembly but not the original container.
- Full `ID3D12CommandSignature` declaration: PARTIALLY_CONFIRMED; child action
  parameters are available but the public pipeline state does not expose the
  complete declaration.
- Blender import: UNTESTED on this machine because no Blender executable is
  installed or registered. GLB byte structure and accessor bounds passed; the
  separate converter provides a background Blender import path when Blender is
  supplied.
- Only the selected leaf action was exported. The original capture was opened
  read-only and its SHA-256 remained unchanged.
