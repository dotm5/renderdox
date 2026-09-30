# Optional Windows graphics bootstrap

These standalone projects provide a loader-safe bootstrap for an owned or
explicitly authorised Windows application whose graphics imports must be
intercepted before normal DComp injection or attachment can run.

The bootstrap is intentionally separate from `renderdoc.sln` and is not
installed or enabled by default. The three system-DLL proxies perform these
steps:

1. `DllMain` records its own module and the original `GetProcAddress`, then
   disables thread notifications.
2. The first exported call loads the matching DLL from System32 and caches its
   real export table outside the loader lock.
3. With `DCOMP_BOOTSTRAP_ENABLE=1`, it loads the adjacent `dgcore.dll`, checks
   the DComp 1.6.0 API, and resolves the export table again through active
   graphics hooks.
4. If loading, the API handshake, or hook verification fails, it restores the
   cached System32 targets and remains a plain forwarder.

After initialization, the system-DLL proxies publish their resolved export
targets and forward subsequent calls through assembly jump paths. Export
resolution and Core activation are initialization work rather than repeated
per-call work.

The Aftermath proxy loads a renamed original from its own directory and starts
the optional Core on a worker thread. Its forwarding path does not depend on
the Core handshake. Deployment requires renaming the original DLL; see the
[Aftermath deployment guide](aftermath_proxy/README.md) for activation and names.

## Build

Add `-IncludeBootstrap` to either Windows release command:

```powershell
util\buildscripts\build_windows_release.ps1 -Toolchain MSVC -Platform x64 `
  -IncludeBootstrap

util\buildscripts\build_windows_release_matrix.ps1 -IncludeBootstrap
```

MSVC and ClangCL outputs are isolated under the normal configuration root:

- `bootstrap\dxgi_proxy\dxgi.dll`
- `bootstrap\d3d11_proxy\d3d11.dll`
- `bootstrap\d3d12_proxy\d3d12.dll`
- `bootstrap\aftermath_proxy\GFSDK_Aftermath_Lib.x64.dll` (see below)

All bootstrap DLLs use the static MSVC runtime. They are built after the Core, but
remain standalone projects so an ordinary solution build stays aligned with
upstream RenderDoc.

MSBuild CI includes all four outputs in both the MSVC and ClangCL portable
archives. They are optional deployment files: choose the proxy matching the
application's import path rather than copying every proxy into one directory.

## Deployment

Set `DCOMP_BOOTSTRAP_ENABLE=1`, then copy matching-architecture files next to
the application executable:

- D3D11: `dxgi.dll`, `d3d11.dll`, and `dgcore.dll`.
- D3D12: `dxgi.dll`, `d3d12.dll`, and `dgcore.dll`.
- Aftermath slot: rename the application's own `GFSDK_Aftermath_Lib.x64.dll` to
  `GFSDK_Aftermath_Lib_orig.dll`, then copy the built
  `GFSDK_Aftermath_Lib.x64.dll` and `dgcore.dll` beside it.

The Aftermath proxy uses an application-local original. Rename that original
beside the proxy so forwarding resolves it without searching System32. It
covers 43 names found across the inspected original
libraries. A called name absent from the installed original fails explicitly.
Its output is therefore not compared against System32 by the export check.

The three system-DLL proxies accept `DCOMP_BOOTSTRAP_LOG` for diagnostics.
`UE_GRAPHICS_DEBUG` and `UE_GRAPHICS_LOG` remain compatibility aliases.

System-DLL proxy export names and ordinals are tied to a Windows SDK/runtime baseline.
Compare them with the target machine's System32 and SysWOW64 DLLs before using
the binaries on a different Windows generation. Release builds that include
the bootstrap run `check_windows_bootstrap_exports.ps1` against the build
machine automatically.
