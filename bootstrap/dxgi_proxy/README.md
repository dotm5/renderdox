# RenderTest owned-application DXGI bootstrap

This project is an isolated DXGI proxy for applications owned by, or explicitly
authorised for testing by, the operator. It is not part of the default
`renderdoc.sln` build.

The bootstrap has three deliberate constraints:

1. `DllMain` only records its module handle and disables thread callbacks.
2. The first exported DXGI call loads the real system DXGI outside `DllMain`.
3. Core loading is opt-in through `RENDERTEST_BOOTSTRAP_ENABLE=1`.

When enabled, the bootstrap loads the adjacent `rendertest.dll`, performs a
RenderDoc API-version handshake, and then resolves its DXGI export targets.
The canonical-module resolver in the Core ensures that RenderDoc's onward
calls target the real system DXGI rather than this proxy.

If the Core is absent, disabled, or fails the handshake, the proxy continues
as a plain System32 DXGI forwarder. It does not modify the PEB, rename files,
hard-code a target executable, load D3D12/D3D11, patch function entry points,
or include MinHook.

Optional diagnostics are written only when
`RENDERTEST_BOOTSTRAP_LOG` contains an absolute log-file path.

Build the project explicitly:

```powershell
MSBuild bootstrap\dxgi_proxy\dxgi_proxy.vcxproj `
  /p:Configuration=Development `
  /p:Platform=x64 `
  /p:PlatformToolset=v143 `
  /p:WindowsTargetPlatformVersion=10.0.26100.0
```

Build `dxgi_proxy_smoke.vcxproj` explicitly with the same configuration and
platform to place `dxgi_proxy_smoke.exe` in the same output directory. Test
deployment must copy both files, and optionally the matching-architecture
`rendertest.dll`, into a fresh owned-test directory.

The x64 and x86 definition files preserve the platform-specific export
ordinals observed for the 20-name Windows DXGI export set. Packaging for a
different Windows baseline must compare both names and ordinals against that
baseline before deployment.
