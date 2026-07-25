# Known issues and UNKNOWN register

| Area | Status | Evidence gap / consequence |
|---|---|---|
| Blender GLB import | UNTESTED | Blender is not installed or registered on this machine. Both GLBs pass the built-in structural/accessor validator, but the Blender acceptance line remains open. |
| FBX conversion | UNTESTED | Converter code and failure boundaries are unit-tested; no Blender executable was supplied, and no Autodesk FBX SDK is linked. |
| Original DXBC/DXIL container bytes | UNKNOWN | v1.45 public Replay API exposes reflection/disassembly, not the exact original container. Exported `raw/*.json` records this boundary. |
| Full D3D12 command signature | PARTIALLY_CONFIRMED | Child indirect parameters are exported, but public pipeline state does not expose the complete `ID3D12CommandSignature` declaration. |
| RDX Post-VS count parity | CONFLICTING | A service raw query reported `numIndices=3` at EID 211 while the Evidence exporter and GLB reported 6. The service method returns raw Replay metadata; no geometry corruption was observed. Investigate before clients treat this count as final geometry cardinality. |
| Capture format version | UNKNOWN | Public v1.45 CaptureFile API does not expose the RDC format version. Replay/product version is 1.45. |
| Enhanced barriers | PARTIALLY_CONFIRMED | v1.45 code paths exist, but no dedicated owned edge-case capture was included. |
| Mesh shaders | UNTESTED | v1.45 supports the relevant paths; no owned mesh-shader capture was supplied. |
| Ray tracing | UNTESTED | v1.45 supports AS/state-object/DispatchRays paths; no owned DXR capture was supplied. |
| Old-Windows Agility fallback | UNTESTED | Donor fallback/device-downgrade changes had no failing owned reproduction and were not ported. |
| Final cross-API pixel matrix | NOT REPEATED | User explicitly selected a short final gate. Earlier baseline and Action Visibility matrices are retained; only D3D12 was replayed after the final build. |

None of these items is silently promoted to `PASS`. The first release-blocking
follow-up should be Blender import if GLB-to-DCC delivery is required; D3D12
feature work should wait for a minimal owned failing capture.

