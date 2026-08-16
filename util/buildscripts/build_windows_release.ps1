[CmdletBinding()]
param(
  [ValidateSet('Build', 'Rebuild')]
  [string]$Target = 'Build',

  [ValidateSet('MSVC', 'ClangCL')]
  [string]$Toolchain = 'MSVC',

  [ValidateSet('Win32', 'x64')]
  [string]$Platform = 'x64',

  [ValidateSet('OneGeneration', 'AllGenerations')]
  [string]$ChildPropagation = 'OneGeneration',

  [ValidateRange(1, 64)]
  [int]$MaxCpuCount = 8,

  [string]$WindowsSDKVersion = '10.0.26100.0',

  [switch]$EnableLTCG,

  [switch]$IncludeBootstrap
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$solutionPath = Join-Path $repositoryRoot 'renderdoc.sln'
$contractCheck = Join-Path $PSScriptRoot 'check_windows_build_contracts.ps1'
$embeddedDxilCheck = Join-Path $PSScriptRoot 'check_windows_embedded_dxil.ps1'
$bootstrapExportCheck = Join-Path $PSScriptRoot 'check_windows_bootstrap_exports.ps1'
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$solutionPlatform = if($Platform -eq 'Win32') { 'x86' } else { $Platform }
$platformToolset = if($Toolchain -eq 'ClangCL') { 'ClangCL' } else { 'v143' }
$configurationDirectory = if($Toolchain -eq 'ClangCL') { 'ClangRelease' } else { 'Release' }
$singleGeneration = if($ChildPropagation -eq 'OneGeneration') { '1' } else { '0' }
$toolchainTag = $Toolchain.ToLowerInvariant()

$requiredDependencies = @(
  'qrenderdoc\3rdparty\swig\swig.exe',
  "qrenderdoc\3rdparty\qt\$Platform\bin\moc.exe",
  "qrenderdoc\3rdparty\qt\$Platform\bin\rcc.exe",
  "qrenderdoc\3rdparty\qt\$Platform\bin\uic.exe",
  "qrenderdoc\3rdparty\python\$Platform\python36.lib",
  "qrenderdoc\3rdparty\python\$Platform\python36.dll",
  "renderdoc\3rdparty\dbghelp\$Platform\dbghelp.dll"
)
foreach($relativeDependency in $requiredDependencies)
{
  $dependency = Join-Path $repositoryRoot $relativeDependency
  if(-not (Test-Path -LiteralPath $dependency -PathType Leaf))
  {
    throw "Full-solution dependency is missing: $dependency"
  }
}

$pathBytes = [Text.Encoding]::UTF8.GetBytes($repositoryRoot.ToUpperInvariant())
$pathHash = [Convert]::ToHexString(
  [Security.Cryptography.SHA256]::HashData($pathBytes)).Substring(0, 16)
$mutex = [Threading.Mutex]::new($false, "Local\RenderDocBuild-$pathHash")
$ownsMutex = $false

try
{
  try
  {
    $ownsMutex = $mutex.WaitOne(0)
  }
  catch [Threading.AbandonedMutexException]
  {
    $ownsMutex = $true
  }

  if(-not $ownsMutex)
  {
    throw "Another build launched through this script is active for $repositoryRoot"
  }

  $activeBuildTools = Get-CimInstance Win32_Process -Filter `
    "Name='MSBuild.exe' OR Name='cl.exe' OR Name='clang-cl.exe' OR Name='link.exe' OR Name='lld-link.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($repositoryRoot) }
  if($activeBuildTools)
  {
    $details = ($activeBuildTools | ForEach-Object {
      "$($_.Name) pid=$($_.ProcessId)"
    }) -join ', '
    throw "Build tools are already using this worktree: $details"
  }

  & $contractCheck -Configuration Release -Platform $Platform `
    -EnableLTCG:$EnableLTCG.IsPresent
  if($LASTEXITCODE -ne 0)
  {
    throw 'Pre-build contract validation failed'
  }

  if(-not (Test-Path -LiteralPath $vswherePath -PathType Leaf))
  {
    throw "vswhere.exe was not found: $vswherePath"
  }
  $visualStudioPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
    -property installationPath
  $msbuildPath = Join-Path $visualStudioPath 'MSBuild\Current\Bin\amd64\MSBuild.exe'
  if(-not (Test-Path -LiteralPath $msbuildPath -PathType Leaf))
  {
    $msbuildPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
      -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
  }
  if(-not $msbuildPath)
  {
    throw 'MSBuild.exe was not found in an installed Visual Studio instance'
  }

  $logDirectory = Join-Path $repositoryRoot 'build\logs'
  New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $profile = if($EnableLTCG) { 'ltcg' } else { 'fast' }
  $logBase = Join-Path $logDirectory "release-$Platform-$toolchainTag-$profile-$stamp"
  $ltcgValue = $EnableLTCG.IsPresent.ToString().ToLowerInvariant()

  $arguments = @(
    $solutionPath
    '-nologo'
    "-t:$Target"
    "-m:$MaxCpuCount"
    '-nr:false'
    '-v:minimal'
    '-p:Configuration=Release'
    "-p:Platform=$solutionPlatform"
    "-p:PlatformToolset=$platformToolset"
    "-p:WindowsTargetPlatformVersion=$WindowsSDKVersion"
    "-p:SolutionDir=$repositoryRoot\"
    '-p:BuildInParallel=true'
    "-p:RDocEnableLTCG=$ltcgValue"
    '-p:DCompStaticRuntime=1'
    '-p:DCompHookIntoChildrenDefault=1'
    '-p:DCompInlineGraphicsHooks=1'
    "-p:DCompSingleGenerationChildHook=$singleGeneration"
    '-p:DCompDiagnosticVariantId=0'
    '-p:DCompDiagnosticTargetInitStage=0'
    '-p:DCompDisableAllHooks=0'
    '-p:DCompDisableWin32SystemHooks=0'
    '-p:DCompDisableTargetControl=0'
    '-p:DCompDisableOverlay=0'
    '-p:DCompPassthroughNonInjectedChildren=0'
    '-p:DCompPassthroughAllNonInjectedChildren=0'
    '-p:DCompDisableWSAHooks=0'
    "-bl:$logBase.binlog"
    '-fl'
    "-flp:logfile=$logBase.log;verbosity=normal;encoding=UTF-8"
  )

  Write-Host "Building full Release|$solutionPlatform with $Toolchain, target=$Target"
  Write-Host "Output: $Platform\$configurationDirectory"
  Write-Host "Log: $logBase.log"
  Write-Host "Binlog: $logBase.binlog"

  & $msbuildPath @arguments
  $buildExitCode = $LASTEXITCODE
  if($buildExitCode -ne 0)
  {
    throw "MSBuild failed with exit code $buildExitCode; inspect $logBase.log"
  }

  $bootstrapOutputs = @(
    'bootstrap\dxgi_proxy\dxgi.dll',
    'bootstrap\d3d11_proxy\d3d11.dll',
    'bootstrap\d3d12_proxy\d3d12.dll'
  )
  if($IncludeBootstrap)
  {
    $bootstrapProjects = @(
      'bootstrap\dxgi_proxy\dxgi_proxy.vcxproj',
      'bootstrap\d3d11_proxy\d3d11_proxy.vcxproj',
      'bootstrap\d3d12_proxy\d3d12_proxy.vcxproj'
    )

    foreach($relativeProject in $bootstrapProjects)
    {
      $projectPath = Join-Path $repositoryRoot $relativeProject
      $projectTag = [IO.Path]::GetFileNameWithoutExtension($projectPath)
      $bootstrapLogBase = Join-Path $logDirectory `
        "release-$Platform-$toolchainTag-$profile-$projectTag-$stamp"
      $bootstrapArguments = @(
        $projectPath
        '-nologo'
        "-t:$Target"
        '-m:1'
        '-nr:false'
        '-v:minimal'
        '-p:Configuration=Release'
        "-p:Platform=$Platform"
        "-p:PlatformToolset=$platformToolset"
        "-p:WindowsTargetPlatformVersion=$WindowsSDKVersion"
        "-p:SolutionDir=$repositoryRoot\"
        "-p:RDocEnableLTCG=$ltcgValue"
        "-bl:$bootstrapLogBase.binlog"
        '-fl'
        "-flp:logfile=$bootstrapLogBase.log;verbosity=normal;encoding=UTF-8"
      )

      Write-Host "Building optional bootstrap project $relativeProject"
      & $msbuildPath @bootstrapArguments
      if($LASTEXITCODE -ne 0)
      {
        throw "Bootstrap build failed for $relativeProject; inspect $bootstrapLogBase.log"
      }
    }

    & $bootstrapExportCheck -Toolchain $Toolchain -Platform $Platform
    if($LASTEXITCODE -ne 0)
    {
      throw 'Bootstrap export validation failed'
    }
  }

  [xml]$identityProps =
      Get-Content -LiteralPath (Join-Path $repositoryRoot 'build\product_identity.props') -Raw
  $readIdentity = {
    param([string]$Name)
    $identityProps.SelectSingleNode("//*[local-name()='$Name']").InnerText
  }
  $productDisplayName = & $readIdentity 'RDocProductDisplayName'
  $uiDisplayName = & $readIdentity 'RDocUIDisplayName'
  $coreBaseName = & $readIdentity 'RDocCoreBaseName'
  $uiBaseName = & $readIdentity 'RDocUIBaseName'
  $commandBaseName = & $readIdentity 'RDocCommandBaseName'
  $stubBaseName = & $readIdentity 'RDocUIStubBaseName'
  $shimBaseName = & $readIdentity 'RDocShimBaseName'
  $vulkanJsonBaseName = & $readIdentity 'RDocVulkanJsonBaseName'
  $vulkanLayerName = & $readIdentity 'RDocVulkanLayerName'
  $vulkanEnableVar = & $readIdentity 'RDocVulkanEnableVar'
  $vulkanDisableVar = & $readIdentity 'RDocVulkanDisableVar'
  $outputRoot = Join-Path $repositoryRoot "$Platform\$configurationDirectory"
  $shimSuffix = if($Platform -eq 'x64') { '64' } else { '32' }
  $requiredOutputs = @(
    "$coreBaseName.dll",
    "$uiBaseName.exe",
    "$commandBaseName.exe",
    "$stubBaseName.exe",
    "$shimBaseName$shimSuffix.dll",
    "$vulkanJsonBaseName.json",
    'pymodules\renderdoc.pyd',
    'pymodules\qrenderdoc.pyd',
    'Qt5Core.dll',
    'Qt5Gui.dll',
    'Qt5Widgets.dll',
    'python36.dll',
    'python36.zip',
    'qtplugins\platforms\qwindows.dll'
  )
  if($IncludeBootstrap)
  {
    $requiredOutputs += $bootstrapOutputs
  }
  foreach($relativeOutput in $requiredOutputs)
  {
    $requiredOutput = Join-Path $outputRoot $relativeOutput
    if(-not (Test-Path -LiteralPath $requiredOutput -PathType Leaf))
    {
      throw "Required full Release output is missing: $requiredOutput"
    }
  }

  $peIdentityContracts = @(
    @{
      RelativePath = "$coreBaseName.dll"
      InternalName = $coreBaseName
      Description = "Core DLL for $productDisplayName"
    },
    @{
      RelativePath = "$uiBaseName.exe"
      InternalName = $uiBaseName
      Description = $productDisplayName
    },
    @{
      RelativePath = "$commandBaseName.exe"
      InternalName = "$commandBaseName.exe"
      Description = "$commandBaseName - https://renderdoc.org/"
    },
    @{
      RelativePath = "$stubBaseName.exe"
      InternalName = "$stubBaseName.exe"
      Description = "$uiDisplayName launcher"
    },
    @{
      RelativePath = "$shimBaseName$shimSuffix.dll"
      InternalName = "$shimBaseName$shimSuffix.dll"
      Description = "$productDisplayName injection shim"
    }
  )
  foreach($contract in $peIdentityContracts)
  {
    $binaryPath = Join-Path $outputRoot $contract.RelativePath
    $versionInfo = [Diagnostics.FileVersionInfo]::GetVersionInfo($binaryPath)
    if($versionInfo.ProductName -ne $productDisplayName -or
       $versionInfo.InternalName -ne $contract.InternalName -or
       $versionInfo.OriginalFilename -ne $contract.RelativePath -or
       $versionInfo.FileDescription -ne $contract.Description)
    {
      throw "PE identity resource mismatch: $binaryPath"
    }
  }
  Write-Host "PE identity resource contract passed: $productDisplayName"

  $versionHeaderText = Get-Content -LiteralPath `
    (Join-Path $repositoryRoot 'renderdoc\api\replay\version.h') -Raw
  $majorVersion = [regex]::Match(
    $versionHeaderText, '(?m)^\s*#define\s+RENDERDOC_VERSION_MAJOR\s+([0-9]+)\s*$').Groups[1].Value
  $minorVersion = [regex]::Match(
    $versionHeaderText, '(?m)^\s*#define\s+RENDERDOC_VERSION_MINOR\s+([0-9]+)\s*$').Groups[1].Value
  if(-not $majorVersion -or -not $minorVersion)
  {
    throw 'Could not parse the RenderDoc major/minor version for Vulkan descriptor validation'
  }

  $vulkanDescriptorPath = Join-Path $outputRoot "$vulkanJsonBaseName.json"
  try
  {
    $vulkanDescriptor = Get-Content -LiteralPath $vulkanDescriptorPath -Raw |
      ConvertFrom-Json
  }
  catch
  {
    throw "Generated Vulkan descriptor is invalid JSON: $vulkanDescriptorPath - " +
          $_.Exception.Message
  }
  $expectedDisableVar = "${vulkanDisableVar}_${majorVersion}_${minorVersion}"
  $enableVariables = @($vulkanDescriptor.layer.enable_environment.PSObject.Properties.Name)
  $disableVariables = @($vulkanDescriptor.layer.disable_environment.PSObject.Properties.Name)
  if($vulkanDescriptor.layer.name -ne $vulkanLayerName -or
     $vulkanDescriptor.layer.library_path -ne ".\$coreBaseName.dll" -or
     [string]$vulkanDescriptor.layer.implementation_version -ne $minorVersion -or
     $enableVariables.Count -ne 1 -or $enableVariables[0] -ne $vulkanEnableVar -or
     $disableVariables.Count -ne 1 -or $disableVariables[0] -ne $expectedDisableVar)
  {
    throw "Generated Vulkan descriptor identity/version mismatch: $vulkanDescriptorPath"
  }
  Write-Host "Vulkan descriptor contract passed: $vulkanLayerName, $expectedDisableVar"

  $dumpbinPath = & $vswherePath -latest -products * `
    -find 'VC\Tools\MSVC\**\bin\Hostx64\x64\dumpbin.exe' | Select-Object -First 1
  if(-not $dumpbinPath)
  {
    throw 'dumpbin.exe was not found'
  }
  $coreDll = Join-Path $outputRoot "$coreBaseName.dll"
  & $embeddedDxilCheck -DllPath $coreDll

  $coreExports = (& $dumpbinPath /exports $coreDll) -join [Environment]::NewLine
  if($LASTEXITCODE -ne 0)
  {
    throw "dumpbin /exports failed for $coreDll"
  }
  foreach($requiredCoreExport in @('DCOMP_GetAPI', 'DllGetClassObject'))
  {
    if(-not $coreExports.Contains($requiredCoreExport))
    {
      throw "Core DLL is missing required export ${requiredCoreExport}: $coreDll"
    }
  }
  if($coreExports.Contains('RENDERDOC_GetAPI'))
  {
    throw "Core DLL still exports the upstream API entry point RENDERDOC_GetAPI: $coreDll"
  }
  Write-Host 'Core export identity contract passed: DCOMP_GetAPI, DllGetClassObject'

  $replayMarker = "${coreBaseName}__replay__marker"
  $escapedReplayMarker = [regex]::Escape($replayMarker)
  $legacyReplayMarker = 'renderdoc__replay__marker'
  $replayPrograms = @(
    (Join-Path $outputRoot "$uiBaseName.exe"),
    (Join-Path $outputRoot "$commandBaseName.exe"),
    (Join-Path $outputRoot 'pymodules\renderdoc.pyd')
  )
  foreach($replayProgram in $replayPrograms)
  {
    $exports = (& $dumpbinPath /exports $replayProgram) -join [Environment]::NewLine
    if($LASTEXITCODE -ne 0)
    {
      throw "dumpbin /exports failed for $replayProgram"
    }
    if($exports -notmatch "(?m)(?<![A-Za-z0-9])_?${escapedReplayMarker}(?:@0)?(?![A-Za-z0-9_])")
    {
      throw "Replay program does not export ${replayMarker}: $replayProgram"
    }
    if($replayMarker -ne $legacyReplayMarker -and $exports.Contains($legacyReplayMarker))
    {
      throw "Replay program still exports the legacy marker ${legacyReplayMarker}: $replayProgram"
    }
  }
  Write-Host "Replay marker contract passed: $replayMarker"

  $shimDll = Join-Path $outputRoot "$shimBaseName$shimSuffix.dll"
  foreach($injectedDll in @($coreDll, $shimDll))
  {
    $dependents = (& $dumpbinPath /dependents $injectedDll) -join [Environment]::NewLine
    if($LASTEXITCODE -ne 0)
    {
      throw "dumpbin /dependents failed for $injectedDll"
    }
    if($dependents -match '(?im)^\s+(MSVCP\d+|VCRUNTIME\d*|ucrtbase)\.dll\s*$')
    {
      throw "Injected DLL contains a forbidden dynamic MSVC runtime import: $injectedDll"
    }
  }
  Write-Host "Injected DLL static-CRT contract passed: $coreDll, $shimDll"

  if($IncludeBootstrap)
  {
    foreach($relativeBootstrap in $bootstrapOutputs)
    {
      $bootstrapDll = Join-Path $outputRoot $relativeBootstrap
      $bootstrapDependents = (& $dumpbinPath /dependents $bootstrapDll) -join `
        [Environment]::NewLine
      if($LASTEXITCODE -ne 0)
      {
        throw "dumpbin /dependents failed for $bootstrapDll"
      }
      if($bootstrapDependents -match `
          '(?im)^\s+(MSVCP\d+|VCRUNTIME\d*|ucrtbase)\.dll\s*$')
      {
        throw "Bootstrap DLL contains a forbidden dynamic MSVC runtime import: $bootstrapDll"
      }
    }
  }

  Write-Host "Full $Toolchain Release build complete: $outputRoot"
}
finally
{
  if($ownsMutex)
  {
    $mutex.ReleaseMutex()
  }
  $mutex.Dispose()
}
