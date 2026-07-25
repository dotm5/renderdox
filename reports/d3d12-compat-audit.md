# D3D12 follow-up compatibility audit

## Decision

No additional D3D12 compatibility patch is justified in this follow-up.
Every candidate first had to show a current v1.45 failure in an owned capture.
The owned D3D12 and UE5 D3D12 captures open and replay, the UE5 capture reports
DXIL use, and the focused ExecuteIndirect capture exposes all child actions.
No candidate below met the missing-and-reproducible threshold.

This decision applies to compatibility changes only. The separately committed
MultiAction overlay work adds parent/child presentation and replay selection;
it does not replace D3D12 capture/replay compatibility code.

## Matrix

| Area | Donor evidence | Current v1.45 evidence | Status | Decision |
|---|---|---|---|---|
| Agility SDK | dlltools `51a21551a846` device downgrade and `c4d0181114d0` `SetSDKVersion` fallback | `d3d12_sdk_select.cpp` already extracts/selects capture SDKs and uses `ID3D12SDKConfiguration1::CreateDeviceFactory`; hooks retain fallback paths | PARTIALLY_CONFIRMED | REFERENCE_ONLY. The older-Windows `SetSDKVersion` path has no owned failing reproduction; do not alter device selection globally. |
| Replay device creation | dlltools `51a21551a846` changes maximum interface/device selection | v1.45 probes supported interfaces/features and the baseline D3D12/UE5 captures replay successfully | UPSTREAMED for the observed requirement | Use upstream. A device downgrade is behavior-changing and needs a specific failing runtime/capture pair. |
| Root-signature deduplication | dlltools `e7047728dc49` claims replay alias registration | Its actual `d3d12_manager.cpp` hunk only skips NULL deferred wrappers. v1.45 capture deduplicates with `HasWrapper`, and replay uses `OverrideWrapper` before registering the replay root signature | CONFLICTING | REFERENCE_ONLY. The claimed alias fix is not present as described in the donor hunk, and no lookup failure reproduces. |
| PSO creation tolerance | dlltools `e7047728dc49` omits NULL root-signature subobjects, tries stream PSOs, and suppresses NULL PSO use | v1.45 supports pipeline-state streams and implicit serialized root signatures; ordinary failures remain explicit | PARTIALLY_CONFIRMED | REJECT the broad NULL guards. Silently skipping `SetPipelineState` or deferred wrappers can turn a replay failure into misleading output. Require a minimal failing PSO first. |
| ExecuteIndirect | dlltools MultiAction/compat history | v1.45 contains focused fixes `2795df7dd`, `42ffc71a0`, `715fce0b5`, `b6925a64f`, `be10d6102`, `469cbc0e3`, and `2b10586ba`; owned map has 14 parents/25 children | UPSTREAMED; presentation gap separately fixed | Use upstream compatibility. Keep only the clean-room MultiAction overlay mapping already committed. |
| DXIL/DXBC | exporter/gdtools contain large version-divergent shader debugger diffs | v1.45 has DXBC/DXIL reflection, disassembly, shader debugging, post-VS DXIL editing, and the owned UE5 capture reports `Capture used DXIL` | UPSTREAMED for tested reflection/replay | REFERENCE_ONLY. Exact donor debugger deltas lack a focused current failure. Exact original shader container export remains an API UNKNOWN, not a replay fix. |
| Descriptor heaps | no isolated donor commit with a current minimal failure | v1.45 exposes descriptor heaps/root tables and maintains descriptor/resource state; focused evidence export succeeds | UPSTREAMED for tested pipeline inspection | No Core change. Full descriptor evidence is exported through the public Replay state. |
| Enhanced barriers | no isolated donor fix selected | v1.45 serialises `ID3D12GraphicsCommandList7::Barrier`, uses `BarrierSet`, and includes `30daa3833` for new-barrier buffer reset | UPSTREAMED in code; capture coverage PARTIAL | Use upstream. A dedicated enhanced-barrier owned capture is still needed before claiming full runtime coverage. |
| Mesh shaders | no isolated donor fix selected | v1.45 serialises/replays `DispatchMesh`, includes indirect mesh dispatch and Post-VS mesh paths | UPSTREAMED in code; UNTESTED locally | No patch. Add an owned mesh-shader capture if this becomes a release requirement. |
| Ray tracing | no isolated donor fix selected | v1.45 serialises AS build/copy, state objects and `DispatchRays`, including indirect ray dispatch | UPSTREAMED in code; UNTESTED locally | No patch. Add an owned DXR capture before any donor-specific change. |

## Donor claims that were not accepted

The `e7047728dc49` commit mixes several independent policies: implicit-root
fallback, broad NULL tolerance, AGS requirement suppression, and deferred
wrapper behavior. Its commit message also states that a deduplicated root
signature is registered as an alias, while the inspected manager hunk only
adds a NULL guard. This mismatch is `CONFLICTING`, not evidence for a port.

The `51a21551a846` and `c4d0181114d0` Agility changes may help a specific old
Windows/runtime pair, but the current machine and captures do not reproduce
that problem. Selecting a lower device interface or changing SDK fallback
globally without such a reproduction could remove supported capabilities.

## Evidence and remaining UNKNOWN

- Current target: official v1.45 `2fc0bc04cb95499635f63986a55bc6f67849dd9f`.
- D3D12 ExecuteIndirect capture SHA-256:
  `CA6D84AC0BD7A19AFCDD85841ED5D921A4C3DE519D41ABDFB1B371B889F4B11A`.
- Owned UE5 D3D12 capture SHA-256:
  `0D7E5BA79EEEE1EAD9282BE448BA47BAFF44627EF4F5E814EF9336EA727CB8A3`.
- Current baseline proves replay for ordinary D3D12, UE5 D3D12, DXIL, and
  ExecuteIndirect. It does not prove old-Windows Agility fallback, embedded
  root-signature failure recovery, enhanced-barrier edge cases, mesh shaders,
  or DXR. These remain UNTESTED rather than being guessed as fixed.

Rollback is therefore trivial: there is no D3D12 compatibility commit to
revert. If a future owned capture reproduces one of these failures, implement
one minimal fix against the current structure with its own before/after log
and commit.
