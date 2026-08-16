# RDX Analysis Service API

RDX Analysis Service is a local, out-of-process, read-only JSON-RPC 2.0
interface to existing RDC files. It uses newline-delimited requests and
responses over stdin/stdout. It does not listen on a TCP interface, launch a
target, inject a process, modify a capture, or expose donor debug-agent code.
Protocol schema version `1` is defined in `schemas/rdx-protocol.schema.json`.

```powershell
python tools\rdx-analysis-service\rdx-service.py `
  --qrenderdoc D:\rdoc-port\dcomp-isolated\x64\Development\dgcoreui.exe `
  --output-root D:\rdx-service-data
```

Call `initialize` first. It reports the method list and active request,
resource, timeout, and session limits. `open_capture` accepts a local `path`
and returns an opaque `sessionId`, capture SHA-256, Replay version, and health
summary. All later capture calls require that session ID. `close_capture`
drops the in-memory session but retains generated evidence for auditability.

## Methods

| Method | Main parameters | Result |
|---|---|---|
| `open_capture` | `path` | session, provenance, health summary |
| `close_capture` | `sessionId` | closed state |
| `get_capture_summary` | `sessionId` | bounded health/identity summary |
| `list_actions` | session, offset/limit, optional name/flag | action page |
| `get_action` | session, `eventId` | one action |
| `get_pipeline_state` | session, EID | generic state plus D3D12 summary |
| `get_resource_usage` | session, optional EID/resource | filtered usages |
| `get_shader` | session, EID, stage | identity, reflection, disassembly |
| `get_shader_reflection` | session, EID, stage | reflection without disassembly |
| `get_buffer_data` | session, resource, offset/length | bounded file reference and hash |
| `save_texture` | session, resource, PNG/DDS/EXR and subresource | file reference and hash |
| `get_post_vs_data` | session, EID, instance/view/stage | raw file references and mesh metadata |
| `build_pass_graph` | session | cached resource-derived pass graph |
| `export_action_evidence` | session, EID, optional instance | Draw Evidence package reference |
| `compare_action_signatures` | session plus other session/EIDs | structural differences |

Every capture result contains `protocolVersion`, `schemaVersion`,
`captureSHA256`, EID where applicable, and the source Replay version. Large
binary values are never embedded in JSON. They are written below the
configured output root and returned as file references with size and SHA-256.

## Cancellation and isolation

Requests execute in dedicated qrenderdoc child processes. The service enforces
a timeout and per-resource byte limit. Send a JSON-RPC `$/cancelRequest`
notification with the original request ID to terminate its worker. EOF or
service shutdown cancels remaining requests. A worker failure returns an
error response and cannot take down qrenderdoc or the service coordinator.

The transport is intentionally stdio-only. If another application bridges it
to MCP or a network transport, that application owns authentication, path
policy, and exposure; the default service must not be bound publicly.
