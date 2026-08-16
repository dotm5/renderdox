# D3D11 bootstrap proxy

This proxy is for applications owned by, or explicitly authorised for testing
by, the operator. It forwards the complete operating-system D3D11 export
surface and activates capture hooks only after the DComp core API handshake
succeeds.

For a normal UE D3D11 deployment, place these matching-build x64 files next to
the game executable:

- `bootstrap\dxgi_proxy\dxgi.dll`
- `bootstrap\d3d11_proxy\d3d11.dll`
- `dgcore.dll`

Launch UE with `-d3d11`. The DXGI proxy is part of the supported UE path:
deploying only `d3d11.dll` and `dgcore.dll` does not cover UE's DXGI
initialisation path.

`DllMain` performs no module loads. It records the proxy module and original
`GetProcAddress`, disables thread callbacks, and defers system-DLL/core loading
until the first exported call. Before loading the core, the proxy caches direct
targets from the real System32 D3D11 DLL. A failed handshake or target
verification restores those cached targets and leaves a plain forwarder.

Set `DCOMP_BOOTSTRAP_ENABLE=1` to enable the bootstrap.
`DCOMP_BOOTSTRAP_LOG` may contain an absolute log-file path. The historical
`UE_GRAPHICS_DEBUG` and `UE_GRAPHICS_LOG` names remain compatibility aliases.

The optional `util\buildscripts\build_windows_release.ps1 -IncludeBootstrap`
release flow builds this proxy after the core solution.
