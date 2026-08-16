# D3D12 bootstrap proxy

This proxy is for applications owned by, or explicitly authorised for testing
by, the operator. It forwards the complete public D3D12 loader export surface.
Private Agility SDK implementations remain in `D3D12Core.dll` and are selected
by the operating-system loader.

For a normal UE D3D12 deployment, place these matching-build x64 files next to
the game executable:

- `bootstrap\dxgi_proxy\dxgi.dll`
- `bootstrap\d3d12_proxy\d3d12.dll`
- `dgcore.dll`

Use the game's normal D3D12 launch. The DXGI proxy handles UE's swap-chain
initialisation while this proxy handles the public D3D12 loader calls.

`DllMain` performs no module loads. It records the proxy module and original
`GetProcAddress`, disables thread callbacks, and defers system-DLL/core loading
until the first exported call. Before loading the core, the proxy caches direct
targets from the real System32 D3D12 DLL. A failed handshake or target
verification restores those cached targets and leaves a plain forwarder.

Set `DCOMP_BOOTSTRAP_ENABLE=1` to enable the bootstrap.
`DCOMP_BOOTSTRAP_LOG` may contain an absolute log-file path. The historical
`UE_GRAPHICS_DEBUG` and `UE_GRAPHICS_LOG` names remain compatibility aliases.

The optional `util\buildscripts\build_windows_release.ps1 -IncludeBootstrap`
release flow builds this proxy after the core solution. Its definition files
mirror the current 18-name public System32 D3D12 loader export surface and do
not retain the historical private ordinal 99 entry.
