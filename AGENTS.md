# DComp Project — Agent Context Document

> Handoff date: 2026-07-27  
> Primary workspace: `D:\rdoc-port\wt-followup` (branch `feature/ace-evasion-fullstack`)  
> Isolated evidence: `D:\dcomp-isolated\` (bypass docs, tools, reports)  
> Research reference: `D:\rdoc-port\3dmigoto-ref\` (3DMigoto source + prototypes)

---

## 1. What This Project Is

A modified RenderDoc v1.45 designed for frame capture of UE4/UE5 games. Forked from `LLMGraphicRenderStudy/renderdoc-ue5` (ACE-bypass reference), then heavily rearchitected.

**Core goal**: Capture full D3D11/D3D12 render pipelines (draw calls, shaders, textures, meshes) from Unreal Engine games without triggering anti-tamper detection.

**Current status**: Actively implementing Phase 0-2 evasion features (see `D:\rdoc-port\reports\下一步计划.md`):
- ✅ Development build passes (0 errors, 0 warnings)
- ✅ Release fast-build passes (WPO disabled via `Directory.Build.targets`)
- ✅ D3D11 proxy chain verified end-to-end (UE 5.7 test program, F12 capture + replay)
- ✅ Successfully tested on `Wuthering Waves` (鸣潮) UE4 D3D12 mode
- 🔄 Restoring PEB masquerade in all 3 proxy DLLs (validated by renderdoc-ue5 10-iteration bypass process)
- 🔄 Restoring disk rename (MoveFileW self-rename to .tmp)
- 🔄 Creating monolithic d3d11 project (`bootstrap/d3d11_mono/`)
- ❌ Blocked on other ACE-protected games that now explicitly scan for `dxgi.dll` in game directory

---

## 2. Architecture (Current)

```
Game directory deployment:
  Win64\
  ├── dxgi.dll        ← 141KB DXGI proxy (20 exports, lazy init)
  ├── d3d12.dll       ← 141KB D3D12 proxy (19 exports, lazy init)
  ├── d3d11.dll       ← 148KB D3D11 proxy (51 exports, lazy init)
  └── dgcore.dll      ← 26MB Core engine (was "dcomp.dll", renamed from conflict with Windows DirectComposition)

Activation:  set UE_GRAPHICS_DEBUG=1  (user-level env var)

Proxy → Core chain:
  Game LoadLibrary("dxgi.dll")
    → InitOnce: LoadLibrary(System32\dxgi.dll) — real system DLL
    → Check env var
    → LoadLibrary("dgcore.dll")  ← RDOC_CORE_FILENAME_W = L"dgcore.dll"
    → GetProcAddress("DCOMP_GetAPI") → handshake
    → ResolveExports → forward all DXGI exports to System32
  
  Game LoadLibrary("d3d11.dll" / "d3d12.dll")
    → Same pattern, but Core already loaded → reuse existing handshake
```

---

## 3. Security Layer (What We Built)

### 3.1 Completed & Verified

| Feature | Where | Purpose |
|---------|-------|---------|
| **Export rename** | `renderdoc/replay/app_api.cpp` | `RENDERDOC_GetAPI` → `DCOMP_GetAPI` (and 60+ other exports) |
| **Replay marker rename** | `renderdoc/api/replay/renderdoc_replay.h` | `renderdoc__replay__marker` → `dcomp__replay__marker` |
| **Vulkan layer rename** | `renderdoc/driver/vulkan/dgcore.json` | `VK_LAYER_RENDERDOC_*` → `VK_LAYER_DCOMP_*` |
| **VirtualProtect elimination** | `renderdoc/os/win32/win32_hook.cpp` | Replaced with `NtProtectVirtualMemory` (GetProcAddress from ntdll) |
| **ProxyOnly mode** | `renderdoc/os/win32/win32_hook.cpp` | `DCOMP_SetHookMode(0)` skips ALL IAT patches |
| **Core DLL rename** | `build/product_identity.json/props/pri` | `dcomp.dll` → `dgcore.dll` (avoid Windows DirectComposition conflict) |
| **Log silencing** | All proxy .cpp | `DCOMP_PROXY_VERBOSE_LOGGING=0` (default), `OutputDebugStringW` gated |
| **Product identity** | `build/product_identity.*` + `renderdoc/generated/` | All `dcomp` → `dgcore` namespacing |

### 3.2 Previously Deleted — Now Restoring (Phase 0-2)

Decision REVERSED. PEB masquerade and disk rename were deleted but are now being RESTORED based on new evidence:

| Feature | Original Reason for Deletion | Why Restoring |
|---------|------------------------------|---------------|
| **PEB BaseDllName masquerade** | Kernel-PEB naming mismatch — cross-verification exposes it | ACE-BASE.sys does NOT register `PsSetLoadImageNotifyRoutine` (confirmed by IDA dumpbin analysis), so kernel view of loaded modules is limited. ACE-Base64 Rust (70MB) includes YARA PE scanning that detects unsigned DLLs by binary patterns — filename alone IS a detection vector. renderdoc-ue5 author's 10-iteration bypass process proved PEB masquerade was necessary for consistent bypass. |
| **MoveFileW disk rename** | Detected by ACE minifilter (`tpstackflt.sys`) | ACE-DFS (file system scanner) finds unknown DLLs via `FindFirstFileW` regardless. Disk rename to `.tmp` reduces static file-name signature matching. Validated by zhihu article "魔改RenderDoc截帧PC端《鸣潮》" by 次次先生 — confirms rename + DLL proxy is the only viable approach. |

### 3.3 Permanently Deleted

| Feature | Why Removed |
|---------|-------------|
| **MinHook inline hooks** | Modifies System32 DLL `.text` sections — code integrity check catches it. |
| **process_injector** | `SetThreadContext` shellcode + `CreateRemoteThread` — textbook detection signatures. |
| **MasqueradeModuleName function** | Dead code (being replaced with restored PEB masquerade implementation). |

### 3.4 Current Exposure

| Vector | Severity | Notes |
|--------|----------|-------|
| ACE scans `dxgi.dll` in game dir | 🔴 | Explicitly detected ("非法劫持模块"). This is THE blocker for D3D12 games. |
| LoadLibrary("dgcore.dll") triggers PsSetLoadImageNotifyRoutine | 🟡 | Kernel callback. dgcore.dll has no signature. |
| DCOMP_GetAPI export can be enumerated | 🟡 | ACE can GetProcAddress every loaded module. |
| dgcore.dll unsigned | 🟡 | Requires EV code signing certificate (~$300-500/year). |

---

## 4. Research — What We Studied

### 4.1 SSMT4-Alpha (StarBobis)
- Closed-source 3DMigoto wrapper with WinDivert kernel driver backdoor
- Uses `WinDivert64.sys` (legitimate signed network driver) for kernel-level IOCTL
- CVE-2024-22830 in ACE-BASE.sys for privilege escalation
- .NET 8.0 + WinDivert.dll + FFmpeg + UPX packing
- **Key insight**: WinDivert is a legal driver with a valid signature — ACE can't ban it without breaking network tools

### 4.2 3DMigoto (bo3b/3Dmigoto, MIT license)
- Open-source D3D11 proxy with COM object wrapping (HackerDevice/HackerContext/HackerSwapChain)
- Shader Hunting: numpad cycling through shaders/VB/IB with green overlay text
- Frame Analysis (F8): dumped entire frame to disk (shaders as .bin+.txt, textures as .dds)
- F10 hot-reload shaders from ShaderFixes/
- CRC32C shader fingerprinting
- **Key insight**: D3D11CreateDeviceAndSwapChain gives Device + SwapChain in ONE call. Single d3d11.dll proxy covers everything.

### 4.3 GIMI / XXMI (SilentNightSound / SpectrumQT)
- GIMI: 3DMigoto fork for Genshin Impact (ACE). Millions of users. Uses d3d11.dll ONLY.
- XXMI: Unified launcher for GIMI/SRMI/ZZZMI/WWMI. Added ShellExecute mode to avoid ACE flags.
- **Key insight**: ACE explicitly detects `dxgi.dll` but NOT `d3d11.dll` (false positive risk from Steam/Discord/OBS overlays).
- When detected: replace d3d11.dll with updated version. Cat-and-mouse game.

### 4.4 RenderDoc Pro
- Commercial RenderDoc fork with signed kernel driver
- "Hand-shakes with ACE instead of racing against it"
- Redirects buffer copies, throttles capture frequency, sandboxes calling context

### 4.5 NvAPI GPU Scanout (TheCruZ/nvidiaCapture)
- `NvAPI_D3D11_WksReadScanout` (interface `0xBCB1C536`) reads GPU scanout buffer directly
- Below ALL user-mode hooks. Zero kernel code.
- **Limitation**: Pixel-level only — no draw calls, no shaders, no mesh data. Useless for pipeline analysis.

### 4.6 NtGdiDdDDI (secret.club)
- `NtGdiDdDDISubmitCommand` → win32kbase function pointer table → `dxgkrnl!DxgkSubmitCommand`
- Table is RW, undocumented, unexported — ACE doesn't check it
- Replacing pointer requires kernel access (susceptible to PatchGuard)
- **Limitation**: Would need to parse GPU DMA buffer command streams = writing a GPU debugger from scratch. Not feasible.

### 4.7 ACE Detection Mechanisms (from reverse engineering / UnknownCheats)
- `ACE-BASE.sys` (kernel, WDF altitude 366669.6) + `ACE-GAME.sys` (kernel, 366669.5)
- `Game-Base.dll` (user-mode, injected into game process)
- Detection layers: PEB module enumeration, digital signature verification, IAT integrity, VAD tree scanning, code section hashing, ObRegisterCallbacks handle stripping, filesystem minifilter (tpstackflt.sys)

### 4.8 "魔改RenderDoc截帧PC端《鸣潮》" (次次先生, Zhihu)
- Validates our rename + DLL proxy approach on Wuthering Waves (ACE-protected)
- Confirms DLL proxy is the only viable approach, racing against ACE
- Provides external confirmation that MoveFileW rename + DLL sideloading work in practice

### 4.9 ACE Analysis — 卡拉比丘 (15-Chapter Report)
- Comprehensive reverse engineering report: `D:\rdoc-port\reports\ACE分析-卡拉比丘.md`
- ACE-Base64 Rust (70MB) with YARA PE scanning — can detect unsigned DLLs by binary patterns
- ACE-DFS file system scanner uses `FindFirstFileW` to enumerate unknown DLLs
- ACE-BASE.sys does NOT register `PsSetLoadImageNotifyRoutine` (confirmed by IDA dumpbin)
- ACE-ATS64.dll contains `FileMemIATChecker` and `MemoryChecker` — keep ProxyOnly mode active
- Key finding: DLL proxy is the only viable approach; kernel view of loaded modules is limited

---

## 5. Key Technical Decisions & Rationale

| Decision | Why |
|----------|-----|
| **DLL Sideloading over injection** | No cross-process operation. Game loads DLL itself via Windows search order. |
| **Restore MoveFileW disk rename** | Previously dropped (minifilter concern), but ACE-DFS uses `FindFirstFileW` to find unknown DLLs regardless. Renaming to `.tmp` reduces static file-name signature. Validated by zhihu article and renderdoc-ue5 10-iteration bypass. |
| **Restore PEB masquerade** | Previously dropped (kernel-PEB mismatch concern), but ACE-BASE.sys does NOT register `PsSetLoadImageNotifyRoutine` (IDA confirmed), so kernel module view is limited. ACE-Base64 Rust YARA PE scanning detects unsigned DLLs by binary patterns — filename IS a detection vector. renderdoc-ue5 proved PEB masquerade was necessary for consistent bypass. |
| **NtProtectVirtualMemory over VirtualProtect** | Removes "VirtualProtect" from static IAT. Nt* variant is loaded dynamically, used by every process. |
| **UE_GRAPHICS_DEBUG over DCOMP_BOOTSTRAP_ENABLE** | Looks like a UE engine debug flag. Blends into development environment. |
| **dgcore over dcomp** | `dcomp.dll` is Windows DirectComposition — caused system-wide DLL loading crash when accidentally in System32. |
| **Keep RENDERDOC_API_1_6_0 struct names** | Renaming breaks Python bindings, UI tools, proxy CoreHandshake. 25K string occurrences in binary, but ACE doesn't do full string scanning. |

---

## 6. Known Gotchas

- **Release build LTCG lock**: `WholeProgramOptimization=true` in vcxproj causes incremental LTCG to produce a 2MB stub DLL that locks the output file. Fixed by `Directory.Build.targets` defaulting WPO to false. Use `build_windows_release.ps1` for Release builds.

- **dcomp.dll System32 contamination**: A build step copied `dcomp.dll` to `C:\Windows\System32\`. Since `dcomp.dll` IS a real Windows DLL (DirectComposition), this caused explorer.exe, QQ, Edge, and dozens of other processes to load our 73MB DLL. System became unusable. Root cause: unknown build/post-build step. **MUST ensure output DLLs NEVER go into System32.**

- **Proxy DLL recursion**: Loading order matters. d3d11_proxy must call ResolveExports(false) BEFORE loading dgcore.dll, otherwise IAT hooks redirect the proxy's own GetProcAddress back to wrapped functions → stack overflow.

- **Vulkan layer JSON**: Renamed from `dcomp.json` → `dgcore.json`. Contract checker script (`check_windows_build_contracts.ps1`) has hardcoded reference to old name and will fail.

- **Canonical System32 resolver**: `win32_hook.cpp` now recognizes both `dxgi.dll` AND `d3d11.dll` as canonical system modules (`GetCanonicalSystemModulePath`). This ensures onward calls use the real System32 DLL, not the proxy.

- **ACE-ATS64.dll FileMemIATChecker & MemoryChecker**: The ACE user-mode module scans for IAT hooks and performs memory integrity checks on loaded modules. **Keep ProxyOnly mode active** (`DCOMP_SetHookMode(0)`) to avoid triggering these scanners. IAT patching is the highest-risk operation.

- **SSC (System Service Call) isolation test**: Planned for next test window. SSC hooking is a known ACE detection vector — need to verify our proxy-only approach doesn't trigger SSC integrity checks.

- **D3D11 mode on 卡拉比丘 not yet tested**: All 卡拉比丘 testing so far has been D3D12 mode. D3D11 path may behave differently with ACE detection, particularly for `d3d11.dll` proxy which has different detection signatures than `dxgi.dll`.

---

## 7. Remaining Tasks (To-Do)

### 🔴 Priority (In Progress — Phase 0-2)
- [ ] **PEB masquerade restoration**: Re-add `MasqueradePEB` to all 3 proxy DLLs (dxgi, d3d11, d3d12). Based on renderdoc-ue5 validation and ACE-Base64 YARA PE scanning analysis.
- [ ] **Disk rename restoration**: Re-add `MoveFileW` self-rename to `.tmp` in proxy init. Validated by zhihu article and ACE-DFS analysis.
- [ ] **Monolithic d3d11.dll**: Merge dgcore into d3d11_proxy. Single DLL, zero external LoadLibrary. Drops 4 files → 1. Eliminates PsSetLoadImageNotifyRoutine trigger. Aligns with 3DMigoto/GIMI architecture.
  - [x] Create `bootstrap/d3d11_mono/` project (in progress)
  - [ ] Link driver_d3d11.lib + core serialization libs statically
  - [ ] Remove LibraryHooks/IAT patch init — proxy init has direct access to wrapper functions
  - [ ] Verify: D3D11 UE5 test program capture + replay
  - [ ] Verify: Wuthering Waves D3D11 mode
- [ ] **卡拉比丘 D3D11 mode test**: Test d3d11 proxy against ACE-ATS64 FileMemIATChecker/MemoryChecker

### 🟡 Medium
- [x] ~~PEB masquerade decision reversed~~ — restoring (see Section 3.2)
- [x] ~~Disk rename decision reversed~~ — restoring (see Section 3.2)
- [ ] **3DMigoto Shader Hunting integration**: Port numpad-based shader cycling + overlay to DComp. Use case: identify which shader renders which visual element without full capture.
- [ ] **FrameAnalysis dump mode**: Lightweight frame dump (shaders + textures as loose files) as alternative to full RDC serialization.
- [ ] **Release LTCG validation**: Once WPO lock issue resolved, test full LTCG Release for maximum binary optimization.
- [ ] **DCOMP_BOOTSTRAP_ENABLE → UE_GRAPHICS_DEBUG audit**: Ensure all 3 proxies + docs use consistent env var name.

### 🟢 Low
- [ ] Contract checker script fix: Update `dgcore.json` reference in `check_windows_build_contracts.ps1`
- [ ] D3D12 mono proxy branch (parallel to D3D11 mono, for non-ACE games)
- [ ] System32 cleanup: Remove any accidentally copied DLLs

---

## 8. File Map — Where Is Everything

### Active development
| Path | Purpose |
|------|---------|
| `wt-followup/` | **Main workspace** — all source code |
| `wt-followup/bootstrap/dxgi_proxy/` | DXGI proxy DLL |
| `wt-followup/bootstrap/d3d12_proxy/` | D3D12 proxy DLL |
| `wt-followup/bootstrap/d3d11_proxy/` | D3D11 proxy DLL |
| `wt-followup/bootstrap/d3d11_mono/` | **Monolithic D3D11 project** (Phase 0-2, in progress) |
| `wt-followup/renderdoc/` | Core engine + drivers |
| `wt-followup/renderdoc/os/win32/win32_hook.cpp` | IAT hook engine + ProxyOnly + NtProtectVirtualMemory |
| `wt-followup/build/product_identity.*` | Brand configuration (dgcore naming) |
| `wt-followup/Directory.Build.targets` | WPO/LTCG control (GPT added) |
| `wt-followup/util/buildscripts/build_windows_release.ps1` | Release build script (GPT added) |
| `wt-followup/util/buildscripts/check_windows_build_contracts.ps1` | Pre-build contract check (GPT added) |

### Build outputs
| Path | Purpose |
|------|---------|
| `wt-followup/x64/Development/` | Dev build artifacts (73MB dgcore.dll) |
| `wt-followup/x64/Release/` | Release artifacts (26MB dgcore.dll, proxy DLLs at `bootstrap/*_proxy/`) |

### Isolated / Research
| Path | Purpose |
|------|---------|
| `D:\dcomp-isolated\` | Sensitive docs, bypass analysis, build scripts, MinHook source |
| `D:\dcomp-isolated\技术博客-DComp图形调试工具的用户态隐蔽设计.md` | Technical blog post (Chinese) |
| `D:\dcomp-isolated\内核截帧研究方向.md` | Kernel capture research notes |
| `D:\rdoc-port\3dmigoto-ref\` | 3DMigoto source clone (1543 files, MIT) |
| `D:\rdoc-port\3dmigoto-ref\prototype\` | Shader Hunting prototype + mono DLL plan |
| `D:\rdoc-port\legacy\` | Archived worktrees (wt-base, wt-fork, wt-port) |
| `D:\rdoc-port\reports\ACE分析-卡拉比丘.md` | 15-chapter ACE reverse engineering report (卡拉比丘) |
| `D:\rdoc-port\reports\下一步计划.md` | Next-phase implementation plan |

---

## 9. Build Commands

```powershell
# Development (fast, 3 min)
& "C:\Program Files\Microsoft Visual Studio\18\Enterprise\MSBuild\Current\Bin\MSBuild.exe" `
  D:\rdoc-port\wt-followup\renderdoc.sln `
  /t:Build /m /nr:false `
  /p:Configuration=Development /p:Platform=x64 `
  /p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0.26100.0 `
  /p:VcpkgEnabled=false

# Release fast (no WPO, ~6 min)
& "C:\Program Files\Microsoft Visual Studio\18\Enterprise\MSBuild\Current\Bin\MSBuild.exe" `
  D:\rdoc-port\wt-followup\renderdoc.sln `
  /t:Rebuild /m /nr:false `
  /p:Configuration=Release /p:Platform=x64 `
  /p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0.26100.0 `
  /p:VcpkgEnabled=false /p:WholeProgramOptimization=false

# Proxy DLLs only (Release)
MSBuild bootstrap\dxgi_proxy\dxgi_proxy.vcxproj -t:Build -p:SolutionDir=D:\rdoc-port\wt-followup\ -p:Configuration=Release -p:Platform=x64 -p:PlatformToolset=v143 -p:WindowsTargetPlatformVersion=10.0.26100.0
MSBuild bootstrap\d3d12_proxy\d3d12_proxy.vcxproj -t:Build -p:SolutionDir=D:\rdoc-port\wt-followup\ -p:Configuration=Release -p:Platform=x64 -p:PlatformToolset=v143 -p:WindowsTargetPlatformVersion=10.0.26100.0
MSBuild bootstrap\d3d11_proxy\d3d11_proxy.vcxproj -t:Build -p:SolutionDir=D:\rdoc-port\wt-followup\ -p:Configuration=Release -p:Platform=x64 -p:PlatformToolset=v143 -p:WindowsTargetPlatformVersion=10.0.26100.0
```

---

## 10. Deployment (Wuthering Waves)

```bat
set SRC=D:\rdoc-port\wt-followup\x64\Release
set DST=E:\SteamLibrary\steamapps\common\Wuthering Waves\Client\Binaries\Win64

copy /Y "%SRC%\bootstrap\dxgi_proxy\dxgi.dll"    "%DST%\dxgi.dll"
copy /Y "%SRC%\bootstrap\d3d12_proxy\d3d12.dll"  "%DST%\d3d12.dll"
copy /Y "%SRC%\bootstrap\d3d11_proxy\d3d11.dll"  "%DST%\d3d11.dll"
copy /Y "%SRC%\dgcore.dll"                         "%DST%\dgcore.dll"

# Permanent env var:
[Environment]::SetEnvironmentVariable("UE_GRAPHICS_DEBUG", "1", "User")
```

---

> Last updated: 2026-07-27 by CAT Shadow / Butter collaboration
