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
$projectPath = Join-Path $repositoryRoot 'renderdoc\renderdoc.vcxproj'
$contractCheck = Join-Path $PSScriptRoot 'check_windows_build_contracts.ps1'
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$projectPlatform = $Platform

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
    $projectPath
    '-nologo'
    "-t:$Target"
    "-m:$MaxCpuCount"
    '-nr:false'
    '-v:minimal'
    '-p:Configuration=Release'
    "-p:Platform=$projectPlatform"
    "-p:SolutionDir=$repositoryRoot\"
    '-p:BuildInParallel=true'
    "-p:RDocEnableLTCG=$ltcgValue"
    "-bl:$logBase.binlog"
    '-fl'
    "-flp:logfile=$logBase.log;verbosity=normal;encoding=UTF-8"
  )

  Write-Host "Building Core DLL Release|$projectPlatform, target=$Target, profile=$profile"
  Write-Host "Log: $logBase.log"
  Write-Host "Binlog: $logBase.binlog"

  & $msbuildPath @arguments
  $buildExitCode = $LASTEXITCODE
  if($buildExitCode -ne 0)
  {
    Write-Error "MSBuild failed with exit code $buildExitCode"
    exit $buildExitCode
  }
}
finally
{
  if($ownsMutex)
  {
    $mutex.ReleaseMutex()
  }
  $mutex.Dispose()
}
