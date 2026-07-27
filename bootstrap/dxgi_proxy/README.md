# DComp owned-application DXGI bootstrap

This project is an isolated DXGI proxy for applications owned by, or explicitly
authorised for testing by, the operator. It is built by the unified Windows
release script after the core solution; it remains separate from the default
`renderdoc.sln` project graph.

The bootstrap has three deliberate constraints:

1. `DllMain` only records its module handle and the original `GetProcAddress`
   pointer, then disables thread callbacks.
2. The first exported DXGI call loads the real system DXGI outside `DllMain`.
3. Core loading is opt-in through `UE_GRAPHICS_DEBUG=1`.

When enabled, the bootstrap loads the adjacent `dgcore.dll`, performs a
DComp API-version handshake, and then resolves its DXGI export targets.
The canonical-module resolver in the Core ensures that DComp's onward
calls target the real system DXGI rather than this proxy.

If the Core is absent, disabled, or fails the handshake, the proxy continues
as a plain System32 DXGI forwarder. It does not modify the PEB, rename files,
hard-code a target executable, load D3D12/D3D11, patch function entry points,
or include MinHook.

Optional diagnostics are written only when `UE_GRAPHICS_LOG` contains an
absolute log-file path.

For a normal UE deployment, use the DXGI proxy together with the proxy for the
selected RHI:

- D3D11: `dxgi.dll`, `d3d11.dll`, and `dgcore.dll`; launch with `-d3d11`.
- D3D12: `dxgi.dll`, `d3d12.dll`, and `dgcore.dll`; use the normal D3D12 launch.

All DLLs must come from the same architecture and release build. Do not deploy
both D3D11 and D3D12 proxies unless deliberately testing an application that
switches or loads both RHIs.

`util\buildscripts\build_windows_release.ps1` builds the core and all three
proxies. To build this proxy alone:

```powershell
MSBuild bootstrap\dxgi_proxy\dxgi_proxy.vcxproj `
  /p:Configuration=Development `
  /p:Platform=x64 `
  /p:PlatformToolset=v143 `
  /p:WindowsTargetPlatformVersion=10.0.26100.0
```

Build `dxgi_proxy_smoke.vcxproj` explicitly with the same configuration and
platform to place `dxgi_proxy_smoke.exe` in the same output directory. Smoke
tests must use a fresh owned-test directory and matching-architecture files.

The x64 and x86 definition files preserve the platform-specific export
ordinals observed for the 20-name Windows DXGI export set. Packaging for a
different Windows baseline must compare both names and ordinals against that
baseline before deployment.
