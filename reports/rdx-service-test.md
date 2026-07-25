# RDX Analysis Service focused validation

The service was validated over JSON-RPC 2.0 stdio against the owned
`D3D12_Execute_Indirect.rdc` capture. Its SHA-256 was
`CA6D84AC0BD7A19AFCDD85841ED5D921A4C3DE519D41ABDFB1B371B889F4B11A`.
This was one focused protocol pass, not a repeated cross-API smoke matrix.

| Check | Result |
|---|---|
| initialize/version/limits | PASS |
| required method count | 15 |
| open/close session | PASS |
| list/get action EID 211 | PASS |
| D3D12 pipeline state | PASS |
| Vertex shader reflection | PASS (`confirmed`) |
| bounded buffer file reference | PASS (64 bytes plus SHA-256) |
| lossless texture file reference | PASS (PNG, 6671 bytes) |
| Post-VS raw file reference | PASS |
| cached pass graph | PASS |
| same-action signature comparison | PASS (`equal: true`) |
| action evidence export | PASS |
| service exit after stdin EOF | PASS (`0`) |

Four pure protocol/session tests cover initialization, all required method
advertisements, session operations, query routing, stdio framing, and
pre-cancelled requests. Replay queries use a dedicated qrenderdoc child,
enforce timeout/resource bounds, and return files below the configured output
root instead of embedding binary data.

The service is a JSON-RPC 2.0 stdio endpoint, suitable for a local MCP bridge;
it is not itself exposed on a network interface. No target control, capture,
injection, or capture-mutation method is present.
