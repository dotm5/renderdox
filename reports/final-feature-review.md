# Final feature review

## Integration result

The follow-up suite is integrated above stable Windows port
`25df92efcf0f5e138f3bc663fe54dcf4c8f72149`. Donors were used only as static
specifications. No donor branch was merged, no donor commit was cherry-picked,
and no donor executable, DLL, installer, injector, capture, or script was run.

## Feature trace

| Feature | Donor / intent | Current implementation and layer | Test evidence | Rollback |
|---|---|---|---|---|
| Structured table export | `dlltools/8710666242a3`; expand selected table copy | `StructuredTableExport.*` plus focused-table actions in `MainWindow`; QRenderDoc because it operates on active proxy models and selection | 5 cases, 46 assertions earlier; final combined QRenderDoc gate included these in 73 assertions | Revert `7b5e48d49` and `90e9fbb43`; upstream copy remains |
| Capture Health / Pass Graph | `agent/3f726986f167` taxonomy and `jetbrains/e454210a4572` process-lifetime ideas | `tools/rdx-analysis-service/rdx_analysis`; external process because public Replay API is sufficient and failures stay out of UI/Core | 9 original unit/contract tests; five API/UE5 captures; deterministic UE5 artifacts | Remove external tool; no Core state |
| Action Visibility | `visibility/7ae99f5e5334`, batch UI `140d1ba214be`; skip selected work | Conservative session API in ReplayController/backends plus Event Browser UI/presets; Core is required because public Replay previously could not omit recorded direct work | 13 owned replay cases; 2 QRenderDoc cases/27 assertions earlier; final combined QRenderDoc gate passed | Clear state/reopen capture; revert `c68dc2533` and `9c7e2277b`; no RDC migration |
| MultiAction overlay | `dlltools/9c5de35b5eeb`; aggregate parent overlays | selected/effective EID propagation, bounded target-filtered child mapping, backend state restoration; Replay/Core required for aggregate overlay | D3D12 map 14 parents/25 children; Vulkan map 8/18; final C++ test 9 assertions | Select child for unchanged path; revert `bd1f98278` |
| Draw Evidence Package | `exporter/bb116a61d174` and `0de72369916e`; portable geometry/evidence | external Python exporter plus QRenderDoc menu entry; public Replay API avoids Core/RDC changes | 3 pure tests; final D3D12 EID 211 export; two valid GLBs with 6 vertices/indices | Remove exporter/menu entry; revert `0305472d9` and Qt fix `284363a9f` |
| Draw package converter | donor FBX work showed interchange demand; FBX SDK dependency rejected | isolated stdlib validator plus explicit Blender background conversion | 3 unit tests; both generated GLBs validated; Blender conversion untested | Remove `tools/draw-package-converter`; revert `2c5c02cb0` |
| RDX Analysis Service | `agent/3f726986f167`; read-only analysis boundary | versioned JSON-RPC 2.0 stdio service with child qrenderdoc queries and bounded file references | 4 original protocol tests, 15 final RDX tests, full D3D12 method exercise | Stop/remove service; revert `107ede818` and `d4dc4f75c` |
| D3D12 compatibility audit | `dlltools/51a21551a846`, `e7047728dc49`, `c4d0181114d0`; Agility/PSO/root-signature tolerance | report only; current upstream behavior retained because no missing reproducible failure exists | owned D3D12/UE5 replay, ExecuteIndirect evidence, source history audit | No code to roll back; revert report `47a6f8099` if obsolete |

## Final shortened gate

- `git diff --check`: PASS.
- Python compileall: PASS.
- JSON/Schema parse: 6 files, PASS.
- Python unit tests: RDX 15, Evidence 3, Converter 3, PASS.
- QRenderDoc focused C++ tests: 73 assertions in 7 cases, PASS.
- RenderDoc MultiAction C++ test: 9 assertions in 1 case, PASS.
- Development x64 v143 Build: PASS, zero warnings/errors.
- Release x64 v143 Build: PASS, zero warnings/errors.
- Development qrenderdoc startup: PASS.
- D3D12 EID 211 replay and Evidence export: PASS in 2.392 seconds.

The earlier two-hour cross-API matrix was not repeated, per user direction.
This does not erase its stored baseline/feature evidence and does not turn
UNTESTED surfaces into passes.

## Security and dependency boundary

The 21 `SECURITY_SPECIFIC_QUARANTINE` classifications remain outside the
default build. Remote injection, hidden process/module behavior, evasion,
manual mapping, binary identity replacement, Android/emulator code, bundled
donor binaries/databases, and mutable agent tools were not integrated. No new
third-party runtime dependency was added to RenderDoc/Core; Blender remains an
optional external converter executable.

