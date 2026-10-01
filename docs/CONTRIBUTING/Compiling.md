# Compiling RenderDox

[Project showcase](../../README.md) · [Build environment](Dependencies.md) · [Usage guide](../../USAGE.md#builds)

## Windows release matrix

From the repository root, build both Windows x64 variants and the optional bootstrap DLLs:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\util\buildscripts\build_windows_release_matrix.ps1 `
  -Target Rebuild -ChildPropagation AllGenerations -IncludeBootstrap
```

The output contains `msvc-release`, `clangcl-release` and a matrix manifest.
For one compiler, use `util/buildscripts/build_windows_release.ps1`.
The [release script reference](../../util/buildscripts/README.md) describes packaging.

## MCP packaging

MCP packaging adds the service runtime and compatible worker to existing native packages.
MSBuild CI performs this step before creating the release ZIPs.
For a local package, follow the [MCP packaging guide](../../tools/renderdoc-mcp/README.md#开发和云端打包).

## Cloud builds

Code pushes to `dgcore-main` and `feat/**` trigger the current CMake and MSBuild workflows.
Documentation and showcase changes are excluded by their path filters.
Manual workflow dispatch remains available. Windows archives are published from successful
`dgcore-main` push builds by the automatic release workflow.

## Other platforms

The [CMake workflow](../../.github/workflows/cmake.yml) describes the current Linux/macOS
core build commands. Additional platform experiments can use the existing source backends.
