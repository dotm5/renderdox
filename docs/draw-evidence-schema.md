# Draw Evidence Package schema

Draw Evidence Package is a read-only, action-scoped export assembled from the
public RenderDoc Replay API. The capture is opened in a dedicated qrenderdoc
child process and is never rewritten. Schema version `1` is defined by
`schemas/draw-evidence.schema.json`.

## Identity and provenance

`manifest.json` is the package index. Its stable identity is the tuple
`captureSHA256`, `eventId`, and `instance`. `provenance.json` records the
RenderDoc version, API, tool version, source interface, resource limit, and
the facts that the operation is read-only and did not modify the capture.
Every artifact published in the package is listed with its byte length and
SHA-256.

## Fidelity vocabulary

- `exact`: bytes or values were read directly without a lossy conversion.
- `approximation`: useful interchange representation whose transform is
  recorded. Post-VS GLB positions use perspective divide and therefore use
  this status.
- `unknown`: the public API cannot prove or expose the requested fact.
- `not-applicable`: the artifact does not apply to the selected action/API.

Input and Post-VS geometry are separate. A legal GLB 2 is generated only when
a POSITION semantic and supported topology/format can be decoded. Otherwise
raw buffer windows and `layout.json` are retained; the exporter does not
invent semantics. Indexed and non-indexed actions, base/first offsets,
instances, 16/32-bit indices, triangle strips, and primitive restart are
handled by the geometry reader.

## Shader and pipeline boundaries

Reflection, UTF-8 disassembly, stage/resource identity, and hashes are
exported. The exact original shader container is `unknown` because the public
Replay API does not expose original DXBC, DXIL, or SPIR-V container bytes.
D3D12 root parameters, descriptor tables, static samplers, bound heaps,
resource states, PSO identity, and predication are recorded when exposed.
The full `ID3D12CommandSignature` declaration is explicitly `partial`; child
action arguments remain available through `action.json`.

## Lossless texture policy

- integer, UNORM, and sRGB resources: PNG;
- floating-point and depth resources: EXR;
- BCn resources: DDS;
- ASTC, ETC, and EAC: raw bytes because v1.45 has no KTX2 destination;
- previews: PNG and always marked as an approximation.

Mip, slice, sample, format, sRGB, resource identity, binding EID, and
descriptor-stage information are recorded. The default per-resource limit is
256 MiB. Files are built in a staging directory and published with one atomic
rename; an exception removes only that unpublished staging directory.
