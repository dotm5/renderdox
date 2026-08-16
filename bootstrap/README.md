# Optional Windows graphics bootstrap

These standalone projects provide a loader-safe bootstrap for an owned or
explicitly authorised Windows application whose graphics imports must be
intercepted before normal DComp injection or attachment can run.

The bootstrap is intentionally separate from `renderdoc.sln` and is not
installed or enabled by default. Each proxy performs only these steps:

1. `DllMain` records its own module and the original `GetProcAddress`, then
   disables thread notifications.
2. The first exported call loads the matching DLL from System32 and caches its
   real export table outside the loader lock.
3. With `DCOMP_BOOTSTRAP_ENABLE=1`, it loads the adjacent `dgcore.dll`, checks
   the DComp 1.6.0 API, and resolves the export table again through active
   graphics hooks.
4. If loading, the API handshake, or hook verification fails, it restores the
   cached System32 targets and remains a plain forwarder.

No executable-specific checks, PEB edits, file renaming, entry-point patches,
or bundled detour library are part of this implementation.

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

All three DLLs use the static MSVC runtime. They are built after the Core, but
remain standalone projects so an ordinary solution build stays aligned with
upstream RenderDoc.

## Deployment

Set `DCOMP_BOOTSTRAP_ENABLE=1`, then copy matching-architecture files next to
the application executable:

- D3D11: `dxgi.dll`, `d3d11.dll`, and `dgcore.dll`.
- D3D12: `dxgi.dll`, `d3d12.dll`, and `dgcore.dll`.

Set `DCOMP_BOOTSTRAP_LOG` to an absolute path for diagnostics. The historical
`UE_GRAPHICS_DEBUG` and `UE_GRAPHICS_LOG` names remain compatibility aliases.

Proxy export names and ordinals are tied to a Windows SDK/runtime baseline.
Compare them with the target machine's System32 and SysWOW64 DLLs before using
the binaries on a different Windows generation. Release builds that include
the bootstrap run `check_windows_bootstrap_exports.ps1` against the build
machine automatically.
