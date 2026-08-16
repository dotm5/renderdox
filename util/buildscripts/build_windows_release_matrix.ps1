[CmdletBinding()]
param(
  [ValidateSet('Build', 'Rebuild')]
  [string]$Target = 'Rebuild',

  [ValidateSet('OneGeneration', 'AllGenerations')]
  [string]$ChildPropagation = 'OneGeneration',

  [ValidateRange(1, 64)]
  [int]$MaxCpuCount = 8,

  [string]$WindowsSDKVersion = '10.0.26100.0',

  [string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$singleBuild = Join-Path $PSScriptRoot 'build_windows_release.ps1'
$commit = (& git -C $repositoryRoot rev-parse HEAD).Trim()
if($LASTEXITCODE -ne 0 -or -not $commit)
{
  throw 'Unable to resolve the source Git commit'
}
$shortCommit = $commit.Substring(0, 10)

if(-not $OutputDirectory)
{
  $artifactRoot = Join-Path (Split-Path -Parent $repositoryRoot) 'artifacts'
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $OutputDirectory = Join-Path $artifactRoot `
    "dgcore-full-release-matrix-$stamp-$shortCommit"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if(Test-Path -LiteralPath $OutputDirectory)
{
  throw "Output directory already exists: $OutputDirectory"
}
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null

$runtimeFiles = @(
  'dgcore.dll',
  'dgcoreui.exe',
  'dgcorecmd.exe',
  'dgcorestub.exe',
  'dgcoreshim64.dll',
  'dgcore.json',
  'renderdoc_app.h',
  'd3dcompiler_47.dll',
  'dbghelp.dll',
  'symsrv.dll',
  'symsrv.yes',
  'Qt5Core.dll',
  'Qt5Gui.dll',
  'Qt5Network.dll',
  'Qt5Svg.dll',
  'Qt5Widgets.dll',
  'python36.dll',
  'python36.zip',
  '_ctypes.pyd'
)
$runtimeDirectories = @('pymodules', 'qtplugins')
$matrix = @()

foreach($toolchain in @('MSVC', 'ClangCL'))
{
  & $singleBuild -Target $Target -Toolchain $toolchain -Platform x64 `
    -ChildPropagation $ChildPropagation -MaxCpuCount $MaxCpuCount `
    -WindowsSDKVersion $WindowsSDKVersion
  if($LASTEXITCODE -ne 0)
  {
    throw "$toolchain full Release build failed with exit code $LASTEXITCODE"
  }

  $configurationDirectory = if($toolchain -eq 'ClangCL') { 'ClangRelease' } else { 'Release' }
  $sourceRoot = Join-Path $repositoryRoot "x64\$configurationDirectory"
  $packageName = if($toolchain -eq 'ClangCL') { 'clangcl-release' } else { 'msvc-release' }
  $packageRoot = Join-Path $OutputDirectory $packageName
  New-Item -ItemType Directory -Path $packageRoot | Out-Null

  foreach($relativeFile in $runtimeFiles)
  {
    $source = Join-Path $sourceRoot $relativeFile
    if(-not (Test-Path -LiteralPath $source -PathType Leaf))
    {
      throw "$toolchain runtime file is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $packageRoot $relativeFile)
  }
  foreach($relativeDirectory in $runtimeDirectories)
  {
    $source = Join-Path $sourceRoot $relativeDirectory
    if(-not (Test-Path -LiteralPath $source -PathType Container))
    {
      throw "$toolchain runtime directory is missing: $source"
    }
    Copy-Item -Recurse -LiteralPath $source -Destination $packageRoot
  }

  $files = @(Get-ChildItem -Recurse -File -LiteralPath $packageRoot | Sort-Object FullName |
    ForEach-Object {
      [ordered]@{
        path = $_.FullName.Substring($packageRoot.Length + 1)
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
      }
    })
  $toolchainManifest = [ordered]@{
    toolchain = $toolchain
    platform_toolset = if($toolchain -eq 'ClangCL') { 'ClangCL' } else { 'v143' }
    source_output = $sourceRoot
    package = $packageName
    files = $files
  }
  $toolchainManifest | ConvertTo-Json -Depth 6 | Set-Content `
    -LiteralPath (Join-Path $packageRoot 'manifest.json') -Encoding utf8
  $matrix += $toolchainManifest
}

$manifest = [ordered]@{
  generated_at = (Get-Date).ToString('o')
  source_repository = $repositoryRoot
  source_commit = $commit
  configuration = 'Release'
  platform = 'x64'
  child_propagation = $ChildPropagation
  windows_sdk = $WindowsSDKVersion
  toolchains = $matrix
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content `
  -LiteralPath (Join-Path $OutputDirectory 'manifest.json') -Encoding utf8

$readme = @'
# DComp full Windows Release matrix

This directory contains two complete, runnable x64 Release packages built from
the same source commit:

- `msvc-release`: Visual C++ v143 build.
- `clangcl-release`: ClangCL build with isolated output and targeted MSVC
  frontend fallback only for source files that require MSVC-compatible parsing.

Both packages contain the GUI, CLI, capture DLL, shim, UI stub, embedded Python
modules, Qt runtime/plugins, Python runtime, and symbol helper runtime files.
The capture DLL uses a static MSVC runtime and the selected child propagation
policy. Qt and Python filenames remain upstream-compatible runtime contracts.
'@
$readme | Set-Content -LiteralPath (Join-Path $OutputDirectory 'README.md') -Encoding utf8

Write-Host "Full Release matrix complete: $OutputDirectory"
