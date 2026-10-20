# Build scripts

[Project showcase](../../README.md) · [Usage guide](../../USAGE.md#builds)

## RenderDox Windows portable releases

The maintained Windows release path uses PowerShell 7 and builds matching x64
MSVC and ClangCL packages:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\util\buildscripts\build_windows_release_matrix.ps1 `
  -Target Rebuild -ChildPropagation AllGenerations -IncludeBootstrap
```

The scripts discover the latest installed stable C++ toolset and complete Windows
SDK. Use `-MSVCPlatformToolset` and `-WindowsSDKVersion` to reproduce a specific
environment; matrix manifests record the resolved versions.

`build_windows_release.ps1` builds one toolchain. The matrix command creates
`msvc-release`, `clangcl-release` and a matrix manifest under the output
directory. Native packages contain the GUI, capture runtime, injection shim,
Qt plugins, Python and PySide2/Shiboken2. `-IncludeBootstrap` adds the DXGI,
D3D11, D3D12 and x64 Aftermath proxies.

The MSBuild workflow adds the portable MCP service to both packages using
`tools/renderdoc-mcp/packaging/bundle.py`. This step freezes the service with
the latest stable packaging Python supported by its dependencies and available
in the Actions manifest (`>=3.12 <3.16`), then adds an embedded worker interpreter
matching `renderdoc.pyd`;
it packages existing native outputs without rebuilding RenderDoc. See the
[MCP packaging guide](../../tools/renderdoc-mcp/README.md#开发和云端打包) for local use.

The final CI archives include file hashes and component manifests, and are
expanded again to check their contents and DLL dependency closure before
upload. Continuous releases require successful CMake and MSBuild workflows
for the same source commit. See the [release workflow guide](../../USAGE.md#builds).

## CI parallelism and build caches

The [MSBuild workflow](../../.github/workflows/msbuild.yml) validates the build
contracts, then builds MSVC and ClangCL on separate Windows runners in parallel.
Each native job produces one complete package with
`build_windows_release_matrix.ps1 -Toolchains MSVC` or `-Toolchains ClangCL`.
A separate packaging job merges those artifacts, builds the current MCP service
and developer tools, and runs the package and archive checks.

Release ZIPs use `Fastest` compression and artifact upload level `0`; native
handoff artifacts use level `1`. This favors shorter packaging time and can
produce larger archives while retaining the package contents and checks;
`overwrite: true` supports replacing artifacts when rerunning the same workflow
run.

The [CMake workflow](../../.github/workflows/cmake.yml) uses Ninja for the Ubuntu
GCC and macOS AppleClang Release builds. Both compiler launchers use sccache.
Parallelism comes from `[Environment]::ProcessorCount` on Windows, `nproc` on
Linux and `sysctl -n hw.logicalcpu` on macOS. MSBuild also limits the total
parallel compiler processes through `CL_MPCOUNT` and `UseMultiToolTask`.
GitHub currently supplies 4 CPUs and 16 GB RAM for the standard public-repository
Windows and Linux runners; macOS has a different allocation, so the workflow
reads its available CPU count. See the
[GitHub-hosted runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories).

The caches serve different parts of the build:

| Cache | Reused results | Identity and invalidation | Work on a hit |
| --- | --- | --- | --- |
| Windows L1 | Complete native package for one toolchain | Native tracked-input digest, build profile, toolchain, SDK, runner image and pinned dependency archive | Upload the verified native package for assembly; skip native compilation and linking |
| Windows L2 | Local sccache compiler results, up to `2G` per toolchain | Compiler environment prefix; sccache checks each source, included headers, arguments and compiler | Reuse valid compilation results while the native build regenerates outputs and links |
| Native fixture L3 | Compiled static, route and mixed acceptance fixtures | Fixture sources, compiler environment, Python dependencies and JDK | Verify cached files, then execute the acceptance checks again |
| POSIX compiler cache | Local sccache results, up to `1G` per OS/compiler | OS, architecture and compiler prefix; per-compilation content checks | Run CMake/Ninja and reuse matching compiler outputs |

Both workflows install `Mozilla-Actions/sccache-action@v0.0.11` with sccache
`v0.18.0`. They archive `SCCACHE_DIR` with `actions/cache/restore@v6` and
`actions/cache/save@v6`; cache transport takes place around the build rather
than uploading each translation unit during compilation. Windows skips the L2
download when a complete L1 package is available. Successful compiler results
are flushed and saved even when another compilation in the same build fails.
Complete native packages are saved only after their native build and runtime
closure validation succeed, before the separate packaging job starts.

### Native package input identity

`native_build_inputs.py` fingerprints tracked paths, Git object IDs, file modes
and submodule revisions, together with the canonical JSON in
`NATIVE_BUILD_PROFILE`. It rejects uncommitted changes to tracked native inputs.
It deliberately excludes these packaging/documentation paths:

- `tools/renderdoc-mcp/**`
- `docs/**`
- `assets/readme/**`
- `.github/workflows/**`

All other tracked inputs participate in the digest. A commit that only changes
the MCP service can therefore reuse the complete native packages and still
package and test the new MCP code. Changes to native sources, headers, projects,
build scripts or other tracked native inputs invalidate L1 and fall back to L2.

Native compilation policy must be recorded in `NATIVE_BUILD_PROFILE`. This
includes configuration, platform, child propagation, bootstrap selection, LTCG
and the compiler-cache profile. The native build step reads its policy from that
JSON. When adding or changing a native build option in the workflow, update the
profile and pass that value to the build; workflow files themselves are excluded
from the source digest. Compiler implementation, SDK, the dependency ZIP digest
and other machine-specific inputs are recorded separately by
`initialize_windows_compiler_cache.ps1`. Its `toolchain-key` additionally covers
the runner image and native link tools for L1; its `compiler-key` lets L2 retain
compiler entries across image updates for sccache to check individually.

L1 and fixture restore prefixes contain their complete input identity. Only the
`run_id` and `run_attempt` suffix is omitted when restoring the latest matching
snapshot. Compiler archives also have unique run suffixes, with the source SHA
in the saved key, and restore from their compiler/environment prefix. This
allows each build to save a new snapshot despite Actions caches being immutable.
The workflows check `cache-matched-key` for L1/fixture reuse; `cache-hit` alone
would only report an exact match to the new run's full key. See the
[Actions cache matching rules](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#cache-key-matching).

### Windows compiler-cache profile

`sccache.targets` is enabled by the CI-only `RDocUseCompilerCache` switch.
It disables precompiled headers and per-invocation `/MP` batching so sccache can
cache individual translation units. Sources using shared compiler PDB debug
information switch from `/Zi` or `/ZI` to `/Z7`; sources explicitly configured
without debug information, including the large SWIG sources, retain that choice.
Forced includes and the original PCH header search directories are preserved.
MSBuild schedules the independent compiler invocations across the available
CPUs. Ordinary local builds keep their existing profile unless the switch is
explicitly enabled.

The compiler proxies select `clang-cl.exe` for ClangCL sources and `cl.exe` for
MSVC sources, including projects that require the existing targeted MSVC frontend
fallback. Native jobs still use `-Target Rebuild`; reusable compilation comes
from sccache, so generated files and link steps follow the normal build rules.
`check_windows_compiler_cache.ps1` exercises real compiler cache hits, header
invalidation, compiler routing and failure propagation before an MSVC build that misses L1. Cold compilation
with this profile can take longer because it does not use PCH files; judge the
tradeoff from the recorded cold and warm runs.

### Native provenance and current package validation

`merge_windows_release_matrix.py` checks both toolchain packages, their file
inventories and SHA256 hashes, matching SDK/configuration/runtime metadata and
the shared input digest/profile before assembly. Cross-commit reuse requires a
matching native input digest. The merged matrix and each package retain the
native producer separately from the current assembly:

- Top-level `source_commit` and `assembly_commit` identify the current release
  assembly commit.
- Each toolchain entry and package manifest records `native_source_commit` and
  `native_generated_at` from the native build that produced its binaries.
- Reused binaries retain the original embedded Git SHA. The current MCP component
  manifest identifies the commit used to build the MCP service in this run.

The packaging job operates on the downloaded package roots; it does not require
the native jobs' `x64/Release` or `x64/ClangRelease` work directories. It still
sets up MSBuild and the JDK for the owned native fixtures. The fixture cache
reuses compilation artifacts and verifies their receipts and hashes. Static,
route and mixed acceptance execute in every packaging run, including cache hits;
an invalid fixture cache is discarded and rebuilt. Source tests, frozen package
checks, command-line smoke checks, binding checks, archive extraction and DLL
runtime closure checks also run before the final archives are uploaded.

### Cold and warm runs

Both workflows expose the boolean `cold_build` input in **Actions > Run
workflow**. Set it to `true` to skip restoring build results. Windows rebuilds
L1/L2/fixture results and POSIX starts with an empty compiler cache; completed
results are saved under the new run's key to seed a subsequent warm run.
Dependency archives and pip downloads may still be restored. The default
`false` enables normal cache reuse.

For example, using GitHub CLI from PowerShell:

```powershell
$branch = 'dgcore-main' # Use the branch containing the cache workflow changes.
gh workflow run msbuild.yml --repo dotm5/renderdox --ref $branch -f cold_build=true
gh workflow run cmake.yml --repo dotm5/renderdox --ref $branch -f cold_build=true
```

Wait for both runs to finish, then dispatch them again with
`-f cold_build=false` on the same branch and commit. Dispatching a newer run of
the same workflow/branch while one is active cancels the older run. Compare:

- The Windows native-cache summary, including whether each complete package was
  reused and its input digest.
- sccache hit/miss counts, non-cacheable calls and cache size when compilation
  actually runs; the statistics are printed in the logs and job summary.
- Fixture compilation reuse and the fresh acceptance results.
- End-to-end workflow time, native compilation/link time, package assembly and
  cache transfer time separately.

A later MCP-only commit exercises L1 reuse across source commits. A native
source/header change exercises L1 invalidation and L2 reuse of unaffected
translation units. Runner availability, image updates, archive transfer time,
eviction and the changed compiler profile affect the result; no measured speedup
is implied by the cache configuration alone.

### Cache storage budget

The two Windows sccache directories have a `2G` limit each, and the Ubuntu and
macOS directories have a `1G` limit each. Each limit applies to one local cache;
repository storage also includes native packages, fixtures, dependencies and
older snapshots. GitHub's default Actions cache budget is 10 GB per repository.
Unused entries expire after seven days by default, and capacity eviction removes
the least recently accessed entries first. See the
[cache storage and eviction policy](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#usage-limits-and-eviction-policy).

Check **Actions > Caches** and the sccache size statistics if warm builds begin
missing repeatedly. Adjust the per-job limits or remove superseded snapshots
when necessary. Native packages and fixture caches are saved after new work,
so a hit does not create another identical archive. Cache persistence is best
effort; a miss rebuilds the required results, and a failed build remains failed
even when its successful translation units are retained for the next run.

## Upstream build.sh workflow

The build.sh in this folder is used for building packaged builds of renderdoc on both windows and linux.

For this upstream script, the supported Windows environment is an MSYS2 bash shell.

Running build.sh will print the usage instructions. It can be run from anywhere.

By default it will compile everything and package, which will work out of a fresh checkout. You can also pass --skipcompile to package already built binaries, but in this case ensure that everything is compiled as expected:

* On windows, Win32 and x64 Release targets must be built.
* On windows, the `htmlhelp` docs target must be built, and on Linux the `html` target.
* On all platforms, an arm32 android build must exist in the `build-android-arm32` subfolder under the root, and likewise for arm64.
* On linux, the cmake build must be `make installed` to a `dist` folder in the root.

As above, running build.sh by default will compile all this.

# Running

Running build.sh apart from the optional arguments must pass `--snapshot <name>`. The name is used in packaging, i.e. the resulting zips will be `RenderDoc_name.zip`.

The output files will be placed in a `package` subfolder under the root.

`gpg` is used to generate signatures for the file, so a public/private key should be configured.

# Extras

Some extra files can be used, see the `support` subfolder. Also https://renderdoc.org/plugins.zip contains the windows plugins, and https://renderdoc.org/plugins.tgz contains the linux plugins. Extracting these in the root of the repository will be included in the package builds.

On windows PySide2 can be included with the Qt build by extracting https://renderdoc.org/qrenderdoc_3rdparty.zip in the root.

For windows to build installers, all these extras must be present.

# Requirements

In addition to the usual build requirements for native and android builds, windows requires the WiX toolset to generate installer files.

Linux requires docker to build the tool in an isolated container for maximum compatibility, although using the above mentioned `--skipcompile` you could get around this by building locally.

Both platforms require s phinx to be available in python, and in addition windows requires the HTML help workshop.

