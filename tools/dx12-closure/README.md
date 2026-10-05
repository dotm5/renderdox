# DX12 capture closure probe

The default probe preserves the bootstrap policy. The core now excludes the private
D3D12Core GetInterface provider, deduplicates live DXGI factory wrappers, and supports
the direct public DeviceFactory root. Swapchain GetDevice returns the matching device
wrapper and balances the consumed native reference. Build the core with
the normal Release settings and `DCompInlineGraphicsHooks=1`. The runtime diagnostics
are disabled unless `DCOMP_DX_CLOSURE=1` at process startup. An optional
`DCOMP_DX_CLOSURE_LOG` absolute filename prefix writes independent per-PID logs; normal
core logs can be deleted on clean shutdown. The prefix's directory must exist.

Diagnostics add temporary balanced IUnknown queries, a weak identity index, and synchronous
logging. They do not retain objects, replace wrappers, or change QI results. Do not use
diagnostic-on timings as a capture performance benchmark. Absence of an event only applies
to exercised and instrumented paths, not all private/vendor interfaces or external writes.

```powershell
msbuild tools/dx12-closure/sample.vcxproj -p:Configuration=Release -p:Platform=x64
python -X utf8 tools/dx12-closure/run.py `
  --sample tools/dx12-closure/bin/dx12-closure-sample.exe `
  --bin x64/Release --output D:/rdoc-port/tmp-rel/closure-new-run `
  --agility C:/path/to/existing/D3D12/x64
```

The output directory must be new. Each case runs with diagnostics off/on, producing two
captures and replay fingerprints (actions, draw parameters, shader bytes, render-target
format/dimensions/data hashes, texture/buffer counts, debug messages). This is scoped
sample correctness evidence, not exhaustive descriptor/resource/fence closure validation.
`second` creates a second factory, repeats singleton device creation, and creates a distinct
WARP device/queue. Its second frame is rendered and captured on that device.
`agility-second` does the same through a second SDK DeviceFactory. These do not test a
second hardware adapter or cross-device data sharing.
`resize` captures before/after resizing. `agility` requests SDKConfiguration before loading
the SDK; `--modes agility-preload` reverses that order as a root-path regression probe.
`factory-root` uses public D3D12GetInterface(CLSID_D3D12DeviceFactory). Parent tests cover
Factory4, IUnknown, IDXGIObject, concurrent lookups, original-root release, and weak-cache
retirement/recreation. Every default mode verifies GetDevice(IUnknown) and typed-device
canonical identity, 64 repeated returns with balanced device/queue reference counts, and
a queue created through the returned device that records and submits work.
`getdevice-probe` remains available as a focused positive regression fixture.
The sample watchdog terminates its own process after 20 seconds. The capture CLI exit code
is a launcher result, so capture presence and sample output determine case success.

`probe_agility.py --core C:/path/to/D3D12Core.dll` checks native SDKConfiguration,
SDKConfiguration1 and DeviceFactory creation in an uninjected process. It changes no
developer-mode, SDK or OS configuration.

Inventory separates actual inline installs/removals, distinct IAT writes, export hook
registrations and dynamic-resolution redirections. Registrations and COM wrapper methods
are not binary patches. IAT writes include normal/delay tables and are not a live-slot census
after module unload. Core and proxy export forwarding are not EAT patching. Logs are
per-process; never add together the injecting/replay process and target process counts.

The diagnostic index reports `duplicate_candidate`, not an automatic correctness verdict:
multiple wrappers can be intentional interface aliases. The sample tests application-visible
canonical identity for device versions, queue.GetDevice, swapchain versions and factory parents.

For an owned client, `replay_worker.py` also accepts a `CLOSURE_JOB` JSON containing
`unreal: true`, `exe`, `capturePrefix`, and `output`. It injects that executable with DX12,
triggers a capture after eight seconds and stops only the returned target PID. Normal replay
jobs contain `captures: [absolute RDC paths]` and `output`. Launch with matching
`dgcoreui --python tools/dx12-closure/replay_worker.py`.

Explicit A/B experiments use `DCOMP_DX_CLOSURE_AB=loader-iat` or `system-dxgi` at
process startup. The first skips the five loader/GetProcAddress IAT families; the second
skips a System32 DXGI inline entry only when its matching app-local inline entry already
exists. Empty is the default. These experiments are not enabled as a production policy.
Loader skipping loses UE capture in the measured deployment; sample-only passing results
must not be used to approve it. The bounded UE A/A and A/B comparison did not establish
semantic equivalence for System DXGI skipping. Keep the default coverage; this experiment
does not authorize deletion.

`run_ue.py --exe <owned exe> --bin x64/Release --output <new dir> [--ab <mode>]`
launches the owned package without deploying files, queues frame 300 with fixed benchmark
arguments, replays the result, and inventories only the launched target PID. Fixed frame
numbers do not guarantee identical UE scheduling, timestamps, or resource/resolve state.

Diagnostics additionally record canonical identities on successful GetParent/GetDevice/
GetBuffer returns, untracked successful returns, native rejected QIs, SDK selection,
provider exclusion and native graphics GetProcAddress resolution. They cover exercised
paths and do not observe arbitrary caller-side PE export parsing, every vendor interface,
or every object returned from private APIs. Diagnostic-on timings include synchronous
logging and temporary QIs; benchmark default-off builds separately.

With `CLOSURE_SEMANTICS=1`, replay also summarizes structured API chunk counts,
submission/fence fields, resource types, and dependency edge type counts without resource
IDs. This bounded summary can detect differences but cannot prove graph equivalence.
The UE runner enables it. See `RESULTS-20261006.md` for the convergence decision.
