[CmdletBinding()]
param(
  [string]$OutputDirectory,

  [string]$MSBuildPath,

  [string]$DumpbinPath,

  [ValidateRange(1, 64)]
  [int]$MaxCpuCount = 8,

  [string]$WindowsSDKVersion = '10.0.26100.0'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$projectPath = Join-Path $repositoryRoot 'renderdoc\renderdoc.vcxproj'
$identityPath = Join-Path $repositoryRoot 'build\product_identity.json'
$identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
$coreFilename = "$($identity.coreBaseName).dll"
$sourceDll = Join-Path $repositoryRoot "x64\Release\$coreFilename"
$contractCheck = Join-Path $PSScriptRoot 'check_windows_build_contracts.ps1'
$embeddedDxilCheck = Join-Path $PSScriptRoot 'check_windows_embedded_dxil.ps1'
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'

if(-not (Test-Path -LiteralPath $vswherePath -PathType Leaf))
{
  throw "vswhere.exe was not found: $vswherePath"
}

if(-not $MSBuildPath)
{
  $MSBuildPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
    -find 'MSBuild\**\Bin\amd64\MSBuild.exe' | Select-Object -First 1
  if(-not $MSBuildPath)
  {
    $MSBuildPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
      -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
  }
}

if(-not $DumpbinPath)
{
  $DumpbinPath = & $vswherePath -latest -products * `
    -find 'VC\Tools\MSVC\**\bin\Hostx64\x64\dumpbin.exe' | Select-Object -First 1
}

foreach($requiredTool in @($MSBuildPath, $DumpbinPath))
{
  if(-not $requiredTool -or -not (Test-Path -LiteralPath $requiredTool -PathType Leaf))
  {
    throw "Required build tool was not found: $requiredTool"
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
    "$($identity.coreBaseName)-recursive-routes-x64-Release-$stamp-$shortCommit"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

if(Test-Path -LiteralPath $OutputDirectory)
{
  throw "Output directory already exists: $OutputDirectory"
}
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null

& $contractCheck -Configuration Release -Platform x64
if($LASTEXITCODE -ne 0)
{
  throw 'Pre-build contract validation failed'
}

$commonProperties = [ordered]@{
  Configuration = 'Release'
  Platform = 'x64'
  PlatformToolset = 'v143'
  WindowsTargetPlatformVersion = $WindowsSDKVersion
  SolutionDir = "$repositoryRoot\"
  BuildInParallel = 'true'
  RDocEnableLTCG = 'false'
  DCompStaticRuntime = '1'
  DCompHookIntoChildrenDefault = '1'
  DCompInlineGraphicsHooks = '1'
  DCompDiagnosticVariantId = '0'
  DCompDiagnosticTargetInitStage = '0'
  DCompDisableAllHooks = '0'
  DCompDisableWin32SystemHooks = '0'
  DCompDisableTargetControl = '0'
  DCompDisableOverlay = '0'
  DCompPassthroughNonInjectedChildren = '0'
  DCompPassthroughAllNonInjectedChildren = '0'
  DCompDisableWSAHooks = '0'
}

$variants = @(
  [ordered]@{
    Name = 'recursive-one-generation'
    Description = 'Inject direct children, then disable propagation in the injected child.'
    DCompSingleGenerationChildHook = '1'
  },
  [ordered]@{
    Name = 'recursive-all-generations'
    Description = 'Keep child propagation enabled in every injected generation.'
    DCompSingleGenerationChildHook = '0'
  }
)

$results = @()

foreach($variant in $variants)
{
  $variantDirectory = Join-Path $OutputDirectory $variant.Name
  New-Item -ItemType Directory -Path $variantDirectory | Out-Null

  $properties = [ordered]@{}
  foreach($entry in $commonProperties.GetEnumerator())
  {
    $properties[$entry.Key] = $entry.Value
  }
  $properties['DCompSingleGenerationChildHook'] = $variant.DCompSingleGenerationChildHook

  $arguments = @(
    $projectPath
    '-nologo'
    '-t:Rebuild'
    "-m:$MaxCpuCount"
    '-nr:false'
    '-v:minimal'
  )
  foreach($entry in $properties.GetEnumerator())
  {
    $arguments += "-p:$($entry.Key)=$($entry.Value)"
  }

  Write-Host "Building $($variant.Name) from $shortCommit"
  & $MSBuildPath @arguments
  if($LASTEXITCODE -ne 0)
  {
    throw "MSBuild failed for $($variant.Name) with exit code $LASTEXITCODE"
  }
  if(-not (Test-Path -LiteralPath $sourceDll -PathType Leaf))
  {
    throw "Expected DLL was not produced: $sourceDll"
  }

  $destinationDll = Join-Path $variantDirectory $coreFilename
  Copy-Item -LiteralPath $sourceDll -Destination $destinationDll
  & $embeddedDxilCheck -DllPath $destinationDll

  $dependentsText = (& $DumpbinPath /dependents $destinationDll) -join [Environment]::NewLine
  if($LASTEXITCODE -ne 0)
  {
    throw "dumpbin /dependents failed for $destinationDll"
  }
  $exportsText = (& $DumpbinPath /exports $destinationDll) -join [Environment]::NewLine
  if($LASTEXITCODE -ne 0)
  {
    throw "dumpbin /exports failed for $destinationDll"
  }

  $dependencyNames = @([regex]::Matches(
    $dependentsText,
    '(?im)^\s+([A-Za-z0-9_.-]+\.dll)\s*$') | ForEach-Object { $_.Groups[1].Value })
  $forbiddenDependencies = @($dependencyNames | Where-Object {
    $_ -match '^(MSVCP\d+|VCRUNTIME\d*|ucrtbase)\.dll$'
  })
  if($forbiddenDependencies.Count -ne 0)
  {
    throw "Dynamic MSVC runtime dependency found: $($forbiddenDependencies -join ', ')"
  }
  if($exportsText -notmatch '(?m)\bDCOMP_GetAPI\b')
  {
    throw "DCOMP_GetAPI export was not found in $destinationDll"
  }

  $hash = (Get-FileHash -LiteralPath $destinationDll -Algorithm SHA256).Hash
  $file = Get-Item -LiteralPath $destinationDll
  $variantReport = [ordered]@{
    name = $variant.Name
    description = $variant.Description
    dll = $coreFilename
    bytes = $file.Length
    sha256 = $hash
    exports_dcomp_get_api = $true
    forbidden_dynamic_crt_imports = @()
    dependencies = $dependencyNames
    properties = $properties
  }

  $dependentsText | Set-Content -LiteralPath (Join-Path $variantDirectory 'dependents.txt') `
    -Encoding utf8
  $exportsText | Set-Content -LiteralPath (Join-Path $variantDirectory 'exports.txt') `
    -Encoding utf8
  $variantReport | ConvertTo-Json -Depth 6 | Set-Content `
    -LiteralPath (Join-Path $variantDirectory 'build-contract.json') -Encoding utf8
  $results += $variantReport
}

$manifest = [ordered]@{
  generated_at = (Get-Date).ToString('o')
  source_repository = $repositoryRoot
  source_commit = $commit
  configuration = 'Release'
  platform = 'x64'
  variants = $results
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content `
  -LiteralPath (Join-Path $OutputDirectory 'manifest.json') -Encoding utf8

$readme = @'
# {CORE_BASE_NAME} recursive injection builds

Source commit: {SOURCE_COMMIT}

- `recursive-one-generation`: preferred launcher -> Shipping route. It injects
  direct children and disables further propagation in the injected child.
- `recursive-all-generations`: keeps propagation enabled for all descendants.

Both DLLs are x64 Release `/MT` builds with native graphics entry hooks enabled.
Use the already validated injector. Do not combine these production builds with
the former x64dbg/CE suspended-process injection route.

`manifest.json` and each `build-contract.json` contain hashes and build flags.
'@
$readme = $readme.Replace('{SOURCE_COMMIT}', $commit)
$readme = $readme.Replace('{CORE_BASE_NAME}', $identity.coreBaseName)
$readme | Set-Content -LiteralPath (Join-Path $OutputDirectory 'README.md') -Encoding utf8

Write-Host "Completed: $OutputDirectory"
$results | ForEach-Object {
  Write-Host "$($_.name): SHA256=$($_.sha256) bytes=$($_.bytes)"
}
