[CmdletBinding()]
param(
  [ValidateSet('Build', 'Rebuild')]
  [string]$Target = 'Rebuild',

  [ValidateSet('OneGeneration', 'AllGenerations')]
  [string]$ChildPropagation = 'AllGenerations',

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

# Version-independent runtime.  Every entry here must exist in the package; the
# Python runtime and the Python Qt bindings are resolved per build below.
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
  'pymodules\d3dcompiler_47.dll',
  'pymodules\renderdoc.pyd',
  'pymodules\qrenderdoc.pyd'
)
$runtimeDirectories = @('qtplugins')

# PySide2/Shiboken2 is the binding the embedded Python shell uses for Qt.  The
# UI project links shiboken2.lib whenever the dependency set provides it, which
# makes shiboken2.dll a static import of the GUI executable: a package without
# it fails to start with "shiboken2.dll was not found" instead of degrading.
$pysideRuntimeFiles = @(
  'shiboken2.dll',
  'PySide2\pyside2.dll',
  'PySide2\QtCore.pyd',
  'PySide2\QtGui.pyd',
  'PySide2\QtWidgets.pyd',
  'PySide2\__init__.py',
  'PySide2\_utils.py'
)
# Older PySide2 packages also ship a shiboken2 module directory, newer ones
# only the flat DLL.  Copy it when the build produced it.
$pysideOptionalRuntimeFiles = @(
  'shiboken2\shiboken2.pyd',
  'shiboken2\__init__.py'
)
# Qt resolves its TLS backend at runtime, so the import closure cannot see it.
$qtTlsRuntimeFiles = @('libcrypto-1_1-x64.dll', 'libssl-1_1-x64.dll')
$pysideRoot = Join-Path $repositoryRoot 'qrenderdoc\3rdparty\pyside'
$pysideEnabled = (Test-Path -LiteralPath `
    (Join-Path $pysideRoot 'include\PySide2\pyside.h') -PathType Leaf) -and
  (Test-Path -LiteralPath (Join-Path $pysideRoot 'x64\shiboken2.dll') -PathType Leaf)
$qtTlsAvailable = @($qtTlsRuntimeFiles | Where-Object {
    Test-Path -LiteralPath `
      (Join-Path $repositoryRoot "qrenderdoc\3rdparty\qt\x64\bin\$_") -PathType Leaf
  }).Count -eq $qtTlsRuntimeFiles.Count
$closureCheck = Join-Path $PSScriptRoot 'check_windows_runtime_closure.py'
if(-not (Test-Path -LiteralPath $closureCheck -PathType Leaf))
{
  throw "Runtime closure checker is missing: $closureCheck"
}
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

  # Resolve the Python runtime from the build output instead of pinning a
  # version.  The interpreter DLL carries the ABI version (python36.dll today,
  # python38.dll once the dependency set moves on) and the stdlib archive plus
  # the extension modules that ship beside it belong to exactly that version.
  $pythonInterpreters = @(Get-ChildItem -LiteralPath $sourceRoot -File |
    Where-Object { $_.Name -match '^python3[0-9]+\.dll$' })
  if($pythonInterpreters.Count -ne 1)
  {
    throw ("$toolchain build output must contain exactly one Python interpreter " +
           "DLL, found $($pythonInterpreters.Count)")
  }
  $pythonAbiFilename = $pythonInterpreters[0].Name
  $pythonMajorMinor = $pythonAbiFilename -replace '^python(3[0-9]+)\.dll$', '$1'
  $pythonRuntimeFiles = @($pythonAbiFilename, "python$pythonMajorMinor.zip")
  foreach($pythonSupportName in @(
      'python3.dll',
      '_ctypes.pyd',
      '_hashlib.pyd',
      '_queue.pyd',
      '_socket.pyd',
      '_ssl.pyd',
      'pyexpat.pyd',
      'select.pyd',
      'unicodedata.pyd',
      'libffi-7.dll',
      'libffi-8.dll',
      'libcrypto-3.dll',
      'libcrypto-3-x64.dll',
      'libssl-3.dll',
      'libssl-3-x64.dll'))
  {
    if(Test-Path -LiteralPath (Join-Path $sourceRoot $pythonSupportName) -PathType Leaf)
    {
      $pythonRuntimeFiles += $pythonSupportName
    }
  }
  foreach($pythonRequiredFile in @("python$pythonMajorMinor.zip", '_ctypes.pyd'))
  {
    if($pythonRuntimeFiles -notcontains $pythonRequiredFile)
    {
      throw "$toolchain Python runtime is incomplete: $pythonRequiredFile is not in the build output"
    }
  }

  $requiredRuntimeFiles = @($runtimeFiles) + $pythonRuntimeFiles
  if($pysideEnabled)
  {
    $requiredRuntimeFiles += $pysideRuntimeFiles
  }
  if($qtTlsAvailable)
  {
    $requiredRuntimeFiles += $qtTlsRuntimeFiles
  }

  foreach($relativeFile in $requiredRuntimeFiles)
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
  foreach($relativeFile in $pysideOptionalRuntimeFiles)
  {
    $source = Join-Path $sourceRoot $relativeFile
    if(-not (Test-Path -LiteralPath $source -PathType Leaf))
    {
      continue
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

  # A package is only complete when every binary inside it can resolve its own
  # imports, and when the runtime the binaries load dynamically is present.  The
  # whitelist above drifts as soon as the UI links another library (shiboken2.dll
  # is the most recent example), so validate the assembled package instead of
  # trusting the copy list.
  $closureArguments = @($closureCheck, $packageRoot)
  foreach($expectedRuntimeFile in $requiredRuntimeFiles)
  {
    $closureArguments += @('--expect-runtime', $expectedRuntimeFile)
  }
  & python @closureArguments
  if($LASTEXITCODE -ne 0)
  {
    throw "$toolchain package failed the runtime dependency closure check"
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
    python_abi = $pythonAbiFilename
    python_major_minor = $pythonMajorMinor
    pyside2 = $pysideEnabled
    runtime_closure_verified = $true
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
modules, the versioned CPython runtime (interpreter DLL, stdlib archive and the
extension modules built beside it), the PySide2/Shiboken2 Qt bindings, the Qt
runtime with its TLS libraries and plugins, and the symbol helper runtime files.
The capture DLL uses a static MSVC runtime and the selected child propagation
policy. Qt and Python filenames remain upstream-compatible runtime contracts.

The Python runtime version follows the build: the interpreter that the GUI links
against is discovered from the build output together with the files that belong
to it, so a dependency update to another Python does not silently drop runtime
files. Each package is then verified for a complete DLL import closure before it
is published, and `manifest.json` records the interpreter and binding state.
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
