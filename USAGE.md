# Using RenderDox

[Back to the project showcase](README.md) · [Bootstrap reference](bootstrap/README.md) · [MCP reference](tools/renderdoc-mcp/README.md) · [Build scripts](util/buildscripts/README.md)

This guide covers portable setup, Windows capture activation, MCP configuration and build workflows. For features and screenshots, see the [project README](README.md).

[First run](#first-run) · [Package layout](#portable-package-layout) · [Capture workflows](#capture-workflows) · [MCP](#3-mcp-control-and-analysis) · [Builds](#builds) · [API support](#api-support)

Use RenderDox with software you own or are explicitly authorised to analyse. It does not provide or document protection bypasses.

## First run

1. Download either complete `renderdox-<commit>-windows-x64-msvc-release.zip` or `renderdox-<commit>-windows-x64-clangcl-release.zip` asset from a release and extract it into its own directory.
2. Open `dgcoreui.exe`, then open an existing `.rdc` or use the launch/attach controls to capture an application.
3. For an MCP client, run `.\renderdoc-mcp.exe config` in the extracted directory and copy the printed server entry into the client's MCP configuration. The client launches the stdio service when needed.

Both compiler variants contain the same desktop and MCP features. Keep the runtime folders and DLLs alongside their entry points.


## Portable package layout

```text
RenderDox/
├── dgcoreui.exe                 Desktop capture and replay
├── dgcorecmd.exe                Command-line capture tools
├── dgcore.dll                   Capture runtime
├── renderdoc-mcp.exe            MCP client entry point
├── mcp-runtime/                 Bundled service interpreter and libraries
├── mcp/
│   ├── worker-runtime/          Interpreter matching the native replay bindings
│   ├── source/                  Worker, adapters and optional GUI bridge
│   └── component-manifest.json  MCP version and runtime provenance
├── bootstrap/                  DXGI, D3D11, D3D12 and Aftermath proxy folders
├── pymodules/                  Native Python bindings
├── PySide2/                    Desktop Python modules
├── qtplugins/                  Qt platform and other plugins
└── manifest.json               Package inventory and hashes
```

This is a shortened layout; the package also includes Python, Qt, Shiboken, OpenSSL and other runtime DLLs in its root. Copy the entire extracted package when moving it to another machine.

Capture workflows
-----------------

RenderDox supports two distinct Windows activation routes. Use one route per run so that loading and hook timing remain easy to diagnose.

### 1. Import proxy bootstrap

This route is useful when an owned application follows the normal Windows DLL search path and must load the capture runtime before its first DXGI/D3D call. The bootstrap DLLs are optional, are not part of the default solution graph, and remain plain System32 forwarders unless explicitly enabled.

Build a package with the bootstrap projects:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\util\buildscripts\build_windows_release_matrix.ps1 `
  -Target Rebuild -ChildPropagation AllGenerations -IncludeBootstrap
```

Copy matching-architecture files from one package next to the application executable:

| RHI | Required files |
| --- | --- |
| D3D11 | `bootstrap\dxgi_proxy\dxgi.dll`, `bootstrap\d3d11_proxy\d3d11.dll`, and `dgcore.dll` |
| D3D12 | `bootstrap\dxgi_proxy\dxgi.dll`, `bootstrap\d3d12_proxy\d3d12.dll`, and `dgcore.dll` |
| Aftermath x64 slot | `bootstrap\aftermath_proxy\GFSDK_Aftermath_Lib.x64.dll`, `dgcore.dll`, and the application's original renamed to `GFSDK_Aftermath_Lib_orig.dll` |

Enable the bootstrap in the environment inherited by the application:

```powershell
$env:DCOMP_BOOTSTRAP_ENABLE = '1'
$env:DCOMP_BOOTSTRAP_LOG = 'C:\Temp\dcomp-bootstrap.log' # optional absolute path
.\OwnedApplication.exe
```

After DComp reports an active graphics API, open `dgcoreui.exe` and attach to the running instance. Remove the local proxy DLLs and environment variables when the test is complete.

This workflow only applies when the target actually resolves the local DXGI/D3D import path. A custom loader, private graphics function table, or different RHI path can bypass the bootstrap; use direct injection instead of adding application-specific logic to the proxies. Export names and ordinals are tied to the build machine's Windows baseline, so packages for a different Windows generation must be revalidated against its System32 DLLs.

See [bootstrap/README.md](bootstrap/README.md) for the loader-safety and fallback contracts.
The [Aftermath guide](bootstrap/aftermath_proxy/README.md) describes its sibling-original layout and the optional `dgcore.enable` activation marker.

### 2. Early direct injection

This route loads `dgcore.dll` into the real rendering process with an existing user-mode loader, debugger, or suspended-start launcher. The portable package does not require a particular injector.

1. Select a `dgcore.dll` whose architecture and source build match the DCompUI package.
2. Start or suspend the real rendering process early enough that DXGI/D3D factory, device, queue, and swap-chain creation have not completed.
3. Load `dgcore.dll`, verify that the operation succeeded, and then resume the process.
4. Start `dgcoreui.exe` from the same package and attach to the running instance.
5. Confirm an active API or overlay and a working control connection before requesting a capture.

The default `AllGenerations` build supports launchers that create an intermediate shell before the rendering process. Use `OneGeneration` only when the direct child is known to be the final renderer:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\util\buildscripts\build_windows_release_matrix.ps1 `
  -Target Rebuild -ChildPropagation OneGeneration
```

A loaded module is not proof that capture is ready: the graphics hooks, target-control channel, active API registration, and replayable `.rdc` output are separate checkpoints. Cross-bitness child injection also requires the matching 32-bit components.

### 3. MCP control and analysis

The portable MCP service can discover and connect to RenderDoc-enabled targets, launch an application or inject a process, request one capture or a timed sequence, collect the resulting RDC files, and open them for analysis.

```powershell
.\renderdoc-mcp.exe config
.\renderdoc-mcp.exe config --format codex
.\renderdoc-mcp.exe serve --stdio
```

The complete package carries both the service runtime and the native worker interpreter. End users do not need a system Python installation, pip, or an MSI installer. Keep the package together, and regenerate the client configuration if its location changes.

For a captured frame, the tools can inspect actions, bindings, constants, shaders, geometry, textures and pixel history; visualize a draw's output contribution; trace resource dependencies; and fetch replay GPU counters. Capture collections support scored EID and resource candidates, explicit alignment anchors, output Diff and constant timelines. Notes and evidence can be exported as Markdown, JSON and ZIP.

### Investigation examples

Once the client has connected to the MCP service, try requests such as:

- **Capture a sequence:** "List available targets, connect to my application, and capture three frames at one-second intervals. Save the RDCs and report the actual frame numbers."
- **Find a draw's contribution:** "Open this RDC, find the main geometry pass, and show which pixels a selected draw changes. Include its output, shader bindings and related geometry candidates."
- **Compare captures:** "Align the main rendering passes in these RDCs, show ambiguous matches, and compare the corresponding outputs and shader constants."
- **Investigate GPU work:** "Rank replay events by GPU duration, group them by pass, and export the results with annotated event evidence."

Long operations return a job ID; the client follows `get_job` to completion before using the resulting session or artifacts. GPU timings describe replay measurements. Cross-capture comparisons use matching evidence rather than assuming equal EIDs refer to the same draw.

See [tools/renderdoc-mcp/README.md](tools/renderdoc-mcp/README.md) for tool parameters, asynchronous jobs, concurrency behavior and the optional GUI bridge.

Builds
------

The supported downstream Windows release boundary is the complete x64 MSVC/ClangCL matrix:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\util\buildscripts\build_windows_release_matrix.ps1 `
  -Target Rebuild -ChildPropagation AllGenerations
```

Unless `-OutputDirectory` is supplied, the script creates a timestamped directory under the sibling `artifacts` directory. It produces:

- `msvc-release` — Visual C++ v143 Release package.
- `clangcl-release` — ClangCL Release package with isolated outputs.
- `manifest.json` — source commit, toolchain, file size, and SHA-256 inventory.

Each native package contains the GUI, command-line tools, capture runtime, injection shim, Qt plugins, Python runtime, Python modules, Vulkan descriptor, and symbol helpers. `-IncludeBootstrap` adds the optional DXGI, D3D11, D3D12 and x64 Aftermath bootstrap outputs. The MSBuild workflow then bundles `renderdoc-mcp.exe`, its service runtime and an ABI-compatible native worker into both packages, before creating and verifying the final archives. Local native build scripts can use the separate [MCP packaging step](tools/renderdoc-mcp/README.md#开发和云端打包).

For a single toolchain, use `util/buildscripts/build_windows_release.ps1`. The scripts validate product identity, exports, embedded DXIL, static-runtime requirements for injected components, Vulkan descriptor identity, required runtime files, and optional bootstrap exports before declaring success.

Code pushes to `dgcore-main` are released automatically after both the CMake and MSBuild workflows validate the same commit. The [continuous pre-release](https://github.com/dotm5/renderdox/releases) contains matching x64 MSVC and ClangCL archives, a complete manifest, SHA-256 checksums, and GitHub build-provenance attestations. Changes confined to Markdown files and `docs/` do not trigger builds. Pull requests and manually dispatched builds remain validation-only and never publish a release.

See [Compiling.md](docs/CONTRIBUTING/Compiling.md) for upstream prerequisites and platform notes.

API support
-----------

The table below describes the upstream-derived capture API coverage. The portable release matrix described here targets Windows x64; it does not distribute Linux or Android packages.

| | Windows | Linux | Android |
| --- | --- | --- | --- |
| Vulkan | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| OpenGL ES 2.0 - 3.2 | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |
| OpenGL 3.2 - 4.6 Core | :heavy_check_mark: | :heavy_check_mark: | N/A |
| D3D11 & D3D12 | :heavy_check_mark: | N/A | N/A |
| OpenGL 1.0 - 2.0 Compat | :heavy_multiplication_x: | :heavy_multiplication_x: | N/A |
| D3D9 & D3D10 | :heavy_multiplication_x: | N/A | N/A |
| Metal | N/A | N/A | N/A |

Nintendo Switch&trade; support is distributed separately to authorised developers as part of the NintendoSDK. Consult the Nintendo Developer Portal for details.

What differs from upstream RenderDoc
------------------------------------

The graphics capture and replay implementation remains upstream-derived. The main downstream differences are deliberately concentrated around Windows identity, deployment, build reproducibility, and analysis presentation.

| Area | Upstream RenderDoc | RenderDox / DComp |
| --- | --- | --- |
| Baseline | General-purpose upstream project | RenderDoc v1.46 compatibility with reviewed post-release maintenance fixes |
| Runtime identity | `renderdoc.dll`, `qrenderdoc.exe`, `renderdoccmd.exe` | `dgcore.dll`, `dgcoreui.exe`, `dgcorecmd.exe`, `dgcorestub.exe`, and `dgcoreshim32/64.dll` |
| Runtime API | `RENDERDOC_GetAPI` | Isolated `DCOMP_GetAPI` entry point; the upstream runtime export is intentionally absent |
| Windows releases | Upstream build and installer layouts | Complete x64 MSVC and ClangCL portable packages from one source commit, with manifests and contract checks |
| Injected runtime | Upstream configuration | Static MSVC runtime for `dgcore.dll`, the injection shim, and optional bootstrap DLLs |
| Early capture | Standard launch, inject, and attach paths | Standard paths plus opt-in DXGI/D3D and Aftermath proxies, and tool-agnostic direct DLL injection |
| Child processes | Standard capture option | All-generation propagation by default, with a bounded one-generation build option |
| Desktop UI | Upstream QRenderDoc interface | DComp identity, Modern Light styling, modern icon states, Chinese localisation, and compact pipeline/capture summaries |
| Analysis extensions | Built-in replay UI and APIs | Capture health/pass analysis, structured export, action visibility, evidence packages, and a portable MCP service |

The `.rdc` format, Qt/Python replay components, and most user-facing replay concepts intentionally stay close to upstream. A capture should still be replayed with a compatible DComp or RenderDoc build; downstream and future upstream versions are not assumed to be interchangeable without testing.

Repository lines
----------------

- `dgcore-main` is the maintained RenderDox branch and the default branch of this repository.
- `v1.x` follows the upstream RenderDoc line without downstream product changes.
- `archive/fullstack-v145` preserves the earlier full-stack implementation as reference material.

Downstream changes should remain reviewable as focused commits on top of the upstream baseline. Product identity is generated from [build/product_identity.json](build/product_identity.json); new code should consume that contract instead of scattering additional names through the tree.

## Related guides

- [Project showcase](README.md): features, screenshots and downloads.
- [Bootstrap reference](bootstrap/README.md): proxy activation, forwarding and deployment details.
- [Aftermath deployment](bootstrap/aftermath_proxy/README.md): renamed original and activation marker.
- [Portable MCP reference](tools/renderdoc-mcp/README.md): capture jobs, analysis tools, Diff, alignment and GUI bridge.
- [Windows release scripts](util/buildscripts/README.md): build and packaging commands.
- [Upstream compilation notes](docs/CONTRIBUTING/Compiling.md): prerequisites and platform notes.
