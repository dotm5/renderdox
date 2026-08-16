# RenderDoc v1.45 full Windows Release and conflict audit

Date: 2026-08-16

Official source baseline: `2fc0bc04cb95499635f63986a55bc6f67849dd9f`

Target: Windows x64 Release, MSVC v143 and ClangCL, one-generation child propagation

## Outcome

The full `renderdoc.sln` graph now builds and packages as two runnable portable
Release distributions. Each distribution contains the GUI, command-line tool,
capture DLL, injection shim and stub, Qt runtime and plugins, embedded Python,
`renderdoc.pyd`, `qrenderdoc.pyd`, symbol helpers, Vulkan descriptor, public
application header, and the matching v143 redistributable runtime.

The matrix build entry point is:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\util\buildscripts\build_windows_release_matrix.ps1 `
  -Target Rebuild -ChildPropagation OneGeneration
```

The output directory is created below `D:\rdoc-port\artifacts` and records the
exact source commit, toolchain, file sizes, and SHA-256 values in `manifest.json`.

## Toolchain boundary

| Package | Main compiler/linker | Deliberate compatibility boundary |
| --- | --- | --- |
| `msvc-release` | MSVC v143 | Complete MSVC build |
| `clangcl-release` | ClangCL and LLD | MSVC frontend is selected only for `renderdoc_d3d11`, `renderdoc_d3d12`, `renderdoc_vulkan`, `renderdoccmd`, and `NV`, whose upstream sources or resources do not parse reliably under the installed ClangCL; the core DLL, GUI, Python modules, and remaining projects use ClangCL |

The capture core and its static project graph use `/MT`. The Qt, Python, GUI,
CLI, and Python-extension boundary retains upstream's `/MD` ABI because the
distributed Qt and Python binaries use that ABI. The package therefore bundles
the exact matching v143 `msvcp140`, `msvcp140_1`, `vcruntime140`, and
`vcruntime140_1` DLLs. `version.obj` omits CRT default-library directives because
it contains only the Git hash constant; this removes the former `LNK4098`
conflict without changing the Qt/Python ABI.

## Official-delta classification

### Necessary project modifications

- Runtime product identity: `dgcore.dll`, `dgcoreui.exe`, `dgcorecmd.exe`,
  `dgcorestub.exe`, `dgcoreshim64.dll`, `dgcore.json`, and the private `DComp`
  configuration/log namespace.
- Public injected API identity: `DCOMP_GetAPI`; the official
  `RENDERDOC_GetAPI` export is intentionally absent.
- Native DXGI/D3D entry-hook path, MinHook integration, and the selected
  one-generation child-injection policy.
- Existing analysis-suite additions in replay, QRenderDoc, and external tools.
- ClangCL compatibility properties, per-toolchain output isolation, static core
  runtime policy, and reproducible package scripts.
- Vendored AMD RGP source required by the current full solution build.

### Official compatibility contracts intentionally retained

- `.rdc` file format, serialisation, target-control and remote wire protocols.
- `renderdoc_app.h`, `renderdoc.pyd`, and `qrenderdoc.pyd` filenames and Python
  module names. These are API/ABI contracts, not injected-DLL identities.
- Internal `RenderDoc` C++ type names and `RENDERDOC_*` public data types where
  renaming would break source, wire, or capture compatibility.
- Canonical `qrenderdoc.exe`, `renderdoccmd.exe`, and `renderdocui.exe` names in
  the child-tool exclusion list. Keeping them excluded prevents accidental
  recursive injection if an official GUI is used with the target.
- Upstream Qt and Python runtime filenames.

### Unintended drift removed in this audit

- Restored the official Qt, Python, SWIG, dbghelp/symsrv, Breakpad, and GUI build
  dependencies removed by the earlier DLL-only cleanup.
- Restored unrelated official Win32 demo and clang-format files byte-for-byte.
- Removed tracked generated `x64` outputs and ignored toolchain output roots.
- Removed stale runtime references to `dcomp.dll`, `dcompui.exe`,
  `dcompcmd.exe`, and `dcomp.json`; the old DLL name would also collide with the
  Windows DirectComposition component.
- Aligned CMake Vulkan input, build scripts, portable package scripts, process
  injector references, and installer file-source names to the `dgcore` output.
- Made capture/injection macros project-wide so PCH and translation units have
  identical semantics under both compilers.
- Limited runtime packaging to runnable files; `.lib`, `.exp`, and `.pdb`
  intermediates are no longer copied into the portable distribution.
- Restored all upstream files unrelated to an intentional rename. A no-renames
  comparison now reports only `renderdoc.version` and `renderdoc.json`, both
  replaced by their `dgcore` counterparts.

## Remaining boundary that is not shipped

The legacy WiX files under `util/installer` still carry official RenderDoc MSI
product identity, UpgradeCode, component GUIDs, file-association ProgIDs, and
registry paths. Although their binary source filenames were updated, building
and installing those MSI definitions would conflict with an official RenderDoc
installation. They are deliberately excluded from this portable Release.

Before producing an MSI, assign a new product name, UpgradeCode, component GUID
set, installation directory, Start Menu identity, and independent ProgIDs. Do
not ship the current WiX output.

PySide2 is not present in the official dependency snapshot, so
`PYSIDE2_ENABLED=0`. Embedded Python and both replay modules are included, but
Qt widgets are not exposed to Python scripts. This does not affect capture,
replay, GUI, CLI, or RDC compatibility. The delivered packages are x64-only.

## Verification evidence

- Build-contract audit: 20 solution projects and 27 project files inspected;
  Release/x64 contract passed.
- Both final build logs: zero compiler errors, zero fatal errors, zero
  `LNK4098`, and zero PCH macro-mismatch warnings.
- Each package contains 29 runtime files and has a complete package manifest.
- `dgcore.dll`: exports `DCOMP_GetAPI` and `INTERNAL_SetCaptureFile`; does not
  export `RENDERDOC_GetAPI`; has no MSVCP, VCRUNTIME, or UCRT import.
- GUI smoke test: both executables stayed alive for five seconds, loaded Qt,
  Python, and `dgcore.dll`, then closed normally with exit code 0.
- CLI smoke test: both `version` and `test unit` commands returned exit code 0.
- Native graphics test for each package: all 10 tested DXGI/D3D entry points
  were detoured, D3D11 created a swap chain and wrote one RDC, and D3D12 created
  a device successfully.
- Child-process test for each package: root loaded, direct child loaded, and
  grandchild did not load, proving the one-generation policy.
- The MSVC and ClangCL RDCs were converted to XML by both package CLIs. A clean
  v1.45 reference `renderdoccmd` also read both captures successfully, proving
  retained RDC compatibility.

## Final assessment

The portable MSVC and ClangCL Release packages are suitable for the established
manual-injection and official-GUI attach workflow. Product-name isolation no
longer removes upstream capture/replay compatibility contracts. The only known
official installation collision is confined to the unshipped WiX source and is
explicitly outside this delivery.
