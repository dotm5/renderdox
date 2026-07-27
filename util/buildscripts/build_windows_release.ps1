[CmdletBinding()]
param(
  [ValidateSet('Build', 'Rebuild')]
  [string]$Target = 'Build',

  [ValidateSet('Win32', 'x64')]
  [string]$Platform = 'x64',

  [ValidateRange(1, 64)]
  [int]$MaxCpuCount = 8,

  [switch]$EnableLTCG
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$solutionPath = Join-Path $repositoryRoot 'renderdoc.sln'
$contractCheck = Join-Path $PSScriptRoot 'check_windows_build_contracts.ps1'
$artifactValidation = Join-Path $PSScriptRoot 'validate_windows_release_artifacts.ps1'
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$solutionPlatform = if($Platform -eq 'Win32') { 'x86' } else { $Platform }
$proxyProjects = @(
  'bootstrap\dxgi_proxy\dxgi_proxy.vcxproj',
  'bootstrap\d3d11_proxy\d3d11_proxy.vcxproj',
  'bootstrap\d3d12_proxy\d3d12_proxy.vcxproj'
)

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
    "Name='MSBuild.exe' OR Name='cl.exe' OR Name='link.exe'" |
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
  $logBase = Join-Path $logDirectory "release-$Platform-$profile-$stamp"
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
    '-p:BuildInParallel=true'
    "-p:RDocEnableLTCG=$ltcgValue"
    "-bl:$logBase.binlog"
    '-fl'
    "-flp:logfile=$logBase.log;verbosity=normal;encoding=UTF-8"
  )

  Write-Host "Building Release|$solutionPlatform, target=$Target, profile=$profile"
  Write-Host "Log: $logBase.log"
  Write-Host "Binlog: $logBase.binlog"

  & $msbuildPath @arguments
  $buildExitCode = $LASTEXITCODE
  if($buildExitCode -ne 0)
  {
    Write-Error "MSBuild failed with exit code $buildExitCode"
    exit $buildExitCode
  }

  foreach($relativeProxyProject in $proxyProjects)
  {
    $proxyProject = Join-Path $repositoryRoot $relativeProxyProject
    $proxyName = [IO.Path]::GetFileNameWithoutExtension($proxyProject)
    $proxyLogBase = "$logBase-$proxyName"
    $proxyArguments = @(
      $proxyProject
      '-nologo'
      "-t:$Target"
      "-m:$MaxCpuCount"
      '-nr:false'
      '-v:minimal'
      '-p:Configuration=Release'
      "-p:Platform=$Platform"
      "-p:SolutionDir=$repositoryRoot\"
      '-p:BuildInParallel=true'
      "-p:RDocEnableLTCG=$ltcgValue"
      "-bl:$proxyLogBase.binlog"
      '-fl'
      "-flp:logfile=$proxyLogBase.log;verbosity=normal;encoding=UTF-8"
    )

    Write-Host "Building proxy $relativeProxyProject"
    & $msbuildPath @proxyArguments
    $proxyExitCode = $LASTEXITCODE
    if($proxyExitCode -ne 0)
    {
      Write-Error "$relativeProxyProject failed with exit code $proxyExitCode"
      exit $proxyExitCode
    }
  }

  [xml]$identityProps =
      Get-Content -LiteralPath (Join-Path $repositoryRoot 'build\product_identity.props') -Raw
  $coreBaseName =
      $identityProps.SelectSingleNode('//*[local-name()="RDocCoreBaseName"]').InnerText
  $outputRoot = Join-Path $repositoryRoot "$Platform\Release"
  $requiredOutputs = @(
    (Join-Path $outputRoot "$coreBaseName.dll"),
    (Join-Path $outputRoot 'bootstrap\dxgi_proxy\dxgi.dll'),
    (Join-Path $outputRoot 'bootstrap\d3d11_proxy\d3d11.dll'),
    (Join-Path $outputRoot 'bootstrap\d3d12_proxy\d3d12.dll')
  )
  foreach($requiredOutput in $requiredOutputs)
  {
    if(-not (Test-Path -LiteralPath $requiredOutput -PathType Leaf))
    {
      throw "Required Release output is missing: $requiredOutput"
    }
  }

  & $artifactValidation -Platform $Platform -RepositoryRoot $repositoryRoot `
    -VisualStudioPath $visualStudioPath

  Write-Host "Release build complete: Core plus all three proxy DLLs are present in $outputRoot"
}
finally
{
  if($ownsMutex)
  {
    $mutex.ReleaseMutex()
  }
  $mutex.Dispose()
}
