# Aftermath slot bootstrap

A drop-in replacement for a game-local `GFSDK_Aftermath_Lib.x64.dll`, built as one
of the optional bootstrap proxies.

Unlike the system-DLL proxies (`dxgi`, `d3d11`, `d3d12`), this one replaces a file
that ships *inside* the application's own directory, so the real library cannot be
reached from System32. The original is renamed and left beside the proxy; calls
to its available exports are forwarded unchanged.

## Export surface

The proxy exports the union of 43 names found in the three inspected Aftermath
libraries. Those applications import by name; ordinals differ between their
original libraries and are not emulated.

Each wrapper jumps to the resolved original. On its first call, it preserves the
integer and floating point argument registers while a synchronized resolver loads
the renamed sibling DLL. There is no per-call logging. If the original DLL or a
called export is absent, the proxy fails explicitly rather than returning a value
that could be misread as SDK success.

## Build

```powershell
util\buildscripts\build_windows_release.ps1 -Toolchain MSVC -Platform x64 -IncludeBootstrap
```

Output: `bootstrap\aftermath_proxy\GFSDK_Aftermath_Lib.x64.dll`

The standalone smoke test checks the 43-name export contract, concurrent first
calls, integer and floating point arguments, and all three original file names:

```powershell
bootstrap\aftermath_proxy\tests\run_proxy_smoke.ps1 -Toolchain MSVC
bootstrap\aftermath_proxy\tests\run_proxy_smoke.ps1 -Toolchain ClangCL
```

## Deployment

1. Rename the original in the application's Aftermath directory to
   `GFSDK_Aftermath_Lib_orig.dll` (the proxy also tries `.x64.orig.dll` and
   `_orig.x64.dll`).
2. Copy `GFSDK_Aftermath_Lib.x64.dll` and `dgcore.dll` beside it.
3. Enable with `DCOMP_BOOTSTRAP_ENABLE=1`, or by dropping an empty `dgcore.enable`
   next to the proxy. The marker is the one that works for a store-launched game.

The forwarding path is independent of the optional core. If the core is disabled
or cannot be loaded, the proxy continues forwarding to the original.

## Scope

x64 only, matching the `GFSDK_Aftermath_Lib.x64.dll` layout. A 32-bit
`GFSDK_Aftermath_Lib.dll` slot is not covered.
