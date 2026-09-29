# GFSDK Aftermath bootstrap (non-system proxy slot)

A proxy for the NVIDIA Aftermath DLL that the application loads from its own
tree, used as the capture foothold for an application that cannot be injected
into.  It replaces `GFSDK_Aftermath_Lib.x64.dll` in place, forwards the nine
`GFSDK_Aftermath_*` exports to the renamed original, and - only when enabled -
loads the adjacent `dgcore.dll`.

This is the "non-system slot" route: the DLL is not a Windows component, so it
is loaded from the application directory by the application itself, and no
cross-process operation is required at any point.

## Contract

1. `DllMain` stays minimal: record module handles, write a load marker, probe
   the VC runtime modules already present, start the DX-module observer and the
   core-load thread.  Nothing that can deadlock under the loader lock.
2. Every export is a **real function**, not a linker forwarder, so call timing
   can be logged (`aftermath_forward.asm` saves RCX/RDX/R8/R9 around the log
   call and jumps to the original).  Export **names and ordinals match the
   original 1:1** - verified against the deployed original.
3. Core loading is opt-in: `DCOMP_BOOTSTRAP_ENABLE=1`, or the adjacent marker
   file `dgcore.enable`.  The marker is preferred: Steam does not forward
   newly-set user environment variables to an already-running parent.
4. Without the marker the stub is a pure forwarder and does nothing else.
5. Static CRT (`/MT`).  A dynamic runtime that is not resolvable next to the
   deployed stub fails the load *before* `DllMain`, which is silent and has
   been misread as "the proxy was blocked".

## Build

```powershell
MSBuild bootstrap\gfsdk_aftermath_stub\gfsdk_aftermath_stub.vcxproj `
  /p:Configuration=Release /p:Platform=x64 /p:PlatformToolset=v143 `
  /p:WindowsTargetPlatformVersion=10.0.26100.0
```

Output: `x64\Release\bootstrap\gfsdk_aftermath_stub\GFSDK_Aftermath_Lib.x64.dll`
(imports `KERNEL32.dll` + `USER32.dll` only).

## Deploy

In the application directory that holds the real Aftermath DLL:

```
GFSDK_Aftermath_Lib.x64.dll   <- this stub
GFSDK_Aftermath_Lib_orig.dll  <- the real DLL, renamed
dgcore.dll                    <- the capture core
dgcore.enable                 <- marker (empty file) to enable the core
```

Diagnostics (fixed paths, so they survive environment-inheritance problems):

- `C:\rdoc_probe\gfsdk_aftermath_loaded.txt` - pid and load timestamp
- `C:\rdoc_probe\gfsdk_bootstrap.log` - enable decision, core load attempts,
  `ProbeLoadedVcRuntime` results
- `C:\rdoc_probe\aftermath_calls.log` - every forwarded call with a timestamp,
  which also dates the RHI/Aftermath initialisation ordering
