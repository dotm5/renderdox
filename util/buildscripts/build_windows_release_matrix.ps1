[CmdletBinding()]
param(
  [ValidateSet('Build', 'Rebuild')]
  [string]$Target = 'Rebuild',

  [ValidateSet('OneGeneration', 'AllGenerations')]
  [string]$ChildPropagation = 'OneGeneration',

  [ValidateRange(1, 64)]
  [int]$MaxCpuCount = 8,

  [string]$WindowsSDKVersion = '10.0.26100.0',

  [string]$OutputDirectory,

  [switch]$IncludeBootstrap
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$singleBuild = Join-Path $PSScriptRoot 'build_windows_release.ps1'
$identityPath = Join-Path $repositoryRoot 'build\product_identity.json'
$identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
$coreFilename = "$($identity.coreBaseName).dll"
$uiFilename = "$($identity.uiBaseName).exe"
$commandFilename = "$($identity.commandBaseName).exe"
$uiStubFilename = "$($identity.uiStubBaseName).exe"
$shim64Filename = "$($identity.shimBaseName)64.dll"
$vulkanJsonFilename = "$($identity.coreBaseName).json"
$vswherePath = Join-Path ${env:ProgramFiles(x86)} `
  'Microsoft Visual Studio\Installer\vswhere.exe'
if(-not (Test-Path -LiteralPath $vswherePath -PathType Leaf))
{
  throw "vswhere.exe was not found: $vswherePath"
}
$visualStudioPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
  -property installationPath
if(-not $visualStudioPath)
{
  throw 'An MSBuild-capable Visual Studio installation was not found'
}
$v143VersionFile = Join-Path $visualStudioPath `
  'VC\Auxiliary\Build\Microsoft.VCToolsVersion.v143.default.txt'
if(-not (Test-Path -LiteralPath $v143VersionFile -PathType Leaf))
{
  throw "The v143 toolset version file was not found: $v143VersionFile"
}
$v143Version = (Get-Content -LiteralPath $v143VersionFile -Raw).Trim()
$v143VersionPrefix = ([version]$v143Version).ToString(2)
$redistRoot = Join-Path $visualStudioPath 'VC\Redist\MSVC'
$redistVersionDirectory = Get-ChildItem -LiteralPath $redistRoot -Directory |
  Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' -and $_.Name.StartsWith("$v143VersionPrefix.") } |
  Sort-Object { [version]$_.Name } -Descending |
  Select-Object -First 1
if(-not $redistVersionDirectory)
{
  throw "A matching v143 redistributable directory was not found below $redistRoot"
}
$crtDirectory = Get-ChildItem -LiteralPath (Join-Path $redistVersionDirectory.FullName 'x64') `
  -Directory -Filter 'Microsoft.VC*.CRT' | Select-Object -First 1
if(-not $crtDirectory)
{
  throw "The x64 v143 CRT directory was not found below $($redistVersionDirectory.FullName)"
}
$crtFileNames = @('msvcp140.dll', 'msvcp140_1.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
foreach($crtFileName in $crtFileNames)
{
  $crtFile = Join-Path $crtDirectory.FullName $crtFileName
  if(-not (Test-Path -LiteralPath $crtFile -PathType Leaf))
  {
    throw "The required v143 CRT file is missing: $crtFile"
  }
}
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
    "$($identity.coreBaseName)-full-release-matrix-$stamp-$shortCommit"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if(Test-Path -LiteralPath $OutputDirectory)
{
  throw "Output directory already exists: $OutputDirectory"
}
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null

$runtimeFiles = @(
  $coreFilename,
  $uiFilename,
  $commandFilename,
  $uiStubFilename,
  $shim64Filename,
  $vulkanJsonFilename,
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
  '_ctypes.pyd',
  'pymodules\d3dcompiler_47.dll',
  'pymodules\renderdoc.pyd',
  'pymodules\qrenderdoc.pyd'
)
$runtimeDirectories = @('qtplugins')
if($IncludeBootstrap)
{
  $runtimeFiles += @(
    'bootstrap\dxgi_proxy\dxgi.dll',
    'bootstrap\d3d11_proxy\d3d11.dll',
    'bootstrap\d3d12_proxy\d3d12.dll'
  )
}
$matrix = @()

foreach($toolchain in @('MSVC', 'ClangCL'))
{
  & $singleBuild -Target $Target -Toolchain $toolchain -Platform x64 `
    -ChildPropagation $ChildPropagation -MaxCpuCount $MaxCpuCount `
    -WindowsSDKVersion $WindowsSDKVersion `
    -IncludeBootstrap:$IncludeBootstrap.IsPresent
  if($LASTEXITCODE -ne 0)
  {
    throw "$toolchain full Release build failed with exit code $LASTEXITCODE"
  }

  $configurationDirectory = if($toolchain -eq 'ClangCL') { 'ClangRelease' } else { 'Release' }
  $sourceRoot = Join-Path $repositoryRoot "x64\$configurationDirectory"
  $packageName = if($toolchain -eq 'ClangCL') { 'clangcl-release' } else { 'msvc-release' }
  $packageRoot = Join-Path $OutputDirectory $packageName
  New-Item -ItemType Directory -Path $packageRoot | Out-Null
  if($IncludeBootstrap)
  {
    $bootstrapPackageRoot = Join-Path $packageRoot 'bootstrap'
    New-Item -ItemType Directory -Path $bootstrapPackageRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'bootstrap\README.md') `
      -Destination (Join-Path $bootstrapPackageRoot 'README.md')
  }

  foreach($relativeFile in $runtimeFiles)
  {
    $source = Join-Path $sourceRoot $relativeFile
    if(-not (Test-Path -LiteralPath $source -PathType Leaf))
    {
      throw "$toolchain runtime file is missing: $source"
    }
    $destination = Join-Path $packageRoot $relativeFile
    $destinationDirectory = Split-Path -Parent $destination
    if(-not (Test-Path -LiteralPath $destinationDirectory -PathType Container))
    {
      New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $destination
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
  foreach($crtFileName in $crtFileNames)
  {
    Copy-Item -LiteralPath (Join-Path $crtDirectory.FullName $crtFileName) `
      -Destination (Join-Path $packageRoot $crtFileName)
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
    vc_runtime = $crtDirectory.FullName
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
  bootstrap = $IncludeBootstrap.IsPresent
  toolchains = $matrix
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content `
  -LiteralPath (Join-Path $OutputDirectory 'manifest.json') -Encoding utf8

$readme = @'
# {PRODUCT_NAME} full Windows Release matrix

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
$readme = $readme.Replace('{PRODUCT_NAME}', $identity.productDisplayName)
$readme | Set-Content -LiteralPath (Join-Path $OutputDirectory 'README.md') -Encoding utf8
if($IncludeBootstrap)
{
  @'

The optional loader-safe DXGI, D3D11, and D3D12 bootstrap DLLs are included
below each package's `bootstrap` directory. They are not installed or enabled
automatically; see the included `bootstrap\README.md`.
'@ | Add-Content -LiteralPath (Join-Path $OutputDirectory 'README.md') -Encoding utf8
}

Write-Host "Full Release matrix complete: $OutputDirectory"
