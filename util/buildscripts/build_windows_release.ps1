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

  [switch]$EnableLTCG
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$solutionPath = Join-Path $repositoryRoot 'renderdoc.sln'
$contractCheck = Join-Path $PSScriptRoot 'check_windows_build_contracts.ps1'
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

  [xml]$identityProps =
      Get-Content -LiteralPath (Join-Path $repositoryRoot 'build\product_identity.props') -Raw
  $readIdentity = {
    param([string]$Name)
    $identityProps.SelectSingleNode("//*[local-name()='$Name']").InnerText
  }
  $coreBaseName = & $readIdentity 'RDocCoreBaseName'
  $uiBaseName = & $readIdentity 'RDocUIBaseName'
  $commandBaseName = & $readIdentity 'RDocCommandBaseName'
  $stubBaseName = & $readIdentity 'RDocUIStubBaseName'
  $shimBaseName = & $readIdentity 'RDocShimBaseName'
  $outputRoot = Join-Path $repositoryRoot "$Platform\$configurationDirectory"
  $shimSuffix = if($Platform -eq 'x64') { '64' } else { '32' }
  $requiredOutputs = @(
    "$coreBaseName.dll",
    "$uiBaseName.exe",
    "$commandBaseName.exe",
    "$stubBaseName.exe",
    "$shimBaseName$shimSuffix.dll",
    'pymodules\renderdoc.pyd',
    'pymodules\qrenderdoc.pyd',
    'Qt5Core.dll',
    'Qt5Gui.dll',
    'Qt5Widgets.dll',
    'python36.dll',
    'python36.zip',
    'qtplugins\platforms\qwindows.dll'
  )
  foreach($relativeOutput in $requiredOutputs)
  {
    $requiredOutput = Join-Path $outputRoot $relativeOutput
    if(-not (Test-Path -LiteralPath $requiredOutput -PathType Leaf))
    {
      throw "Required full Release output is missing: $requiredOutput"
    }
  }

  $dumpbinPath = & $vswherePath -latest -products * `
    -find 'VC\Tools\MSVC\**\bin\Hostx64\x64\dumpbin.exe' | Select-Object -First 1
  if(-not $dumpbinPath)
  {
    throw 'dumpbin.exe was not found'
  }
  $coreDll = Join-Path $outputRoot "$coreBaseName.dll"
  $dependents = (& $dumpbinPath /dependents $coreDll) -join [Environment]::NewLine
  if($LASTEXITCODE -ne 0)
  {
    throw "dumpbin /dependents failed for $coreDll"
  }
  if($dependents -match '(?im)^\s+(MSVCP\d+|VCRUNTIME\d*|ucrtbase)\.dll\s*$')
  {
    throw "Core DLL contains a forbidden dynamic MSVC runtime import: $coreDll"
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
