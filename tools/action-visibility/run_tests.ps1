[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$CaptureManifest,

  [Parameter(Mandatory = $true)]
  [string]$OutputRoot,

  [string]$QRenderDoc = '',

  [string[]]$Cases = @(),

  [ValidateRange(10, 900)]
  [int]$TimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if (-not $QRenderDoc) {
  $QRenderDoc = Join-Path $repositoryRoot 'x64\Development\QRenderTest.exe'
}

$QRenderDoc = (Resolve-Path -LiteralPath $QRenderDoc).Path
$CaptureManifest = (Resolve-Path -LiteralPath $CaptureManifest).Path
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$manifest = Get-Content -LiteralPath $CaptureManifest -Raw -Encoding UTF8 |
  ConvertFrom-Json
$captureEntries = @(
  $manifest.results |
    Where-Object { $Cases.Count -eq 0 -or $Cases -contains [string]$_.case }
)
if ($captureEntries.Count -eq 0) {
  throw "No capture cases matched: $($Cases -join ', ')"
}

$entry = Join-Path $PSScriptRoot 'embedded_entry.py'
$results = [Collections.Generic.List[object]]::new()

foreach ($capture in $captureEntries) {
  $caseName = [string]$capture.case
  $caseDirectory = Join-Path $OutputRoot $caseName
  New-Item -ItemType Directory -Force -Path $caseDirectory | Out-Null

  $resultPath = Join-Path $caseDirectory 'result.json'
  $progressPath = Join-Path $caseDirectory 'progress.log'
  $stdoutPath = Join-Path $caseDirectory 'stdout.log'
  $stderrPath = Join-Path $caseDirectory 'stderr.log'

  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $QRenderDoc
  $startInfo.WorkingDirectory = $caseDirectory
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  [void]$startInfo.ArgumentList.Add('--python')
  [void]$startInfo.ArgumentList.Add($entry)
  $startInfo.Environment['RDX_ACTION_VIS_ROOT'] = $PSScriptRoot
  $startInfo.Environment['RDX_ACTION_VIS_CAPTURE'] = [string]$capture.capturePath
  $startInfo.Environment['RDX_ACTION_VIS_OUTPUT'] = $caseDirectory
  $startInfo.Environment['RDX_ACTION_VIS_RESULT'] = $resultPath
  $startInfo.Environment['RDX_ACTION_VIS_PROGRESS'] = $progressPath

  $process = [Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  $timer = [Diagnostics.Stopwatch]::StartNew()
  if (-not $process.Start()) {
    throw "Failed to start QRenderDoc for $caseName"
  }

  $stdoutTask = $process.StandardOutput.ReadToEndAsync()
  $stderrTask = $process.StandardError.ReadToEndAsync()
  if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    & taskkill.exe /PID $process.Id /T /F | Out-Null
    throw "$caseName exceeded the $TimeoutSeconds second timeout"
  }
  $timer.Stop()

  [IO.File]::WriteAllText(
    $stdoutPath,
    $stdoutTask.GetAwaiter().GetResult(),
    [Text.UTF8Encoding]::new($false)
  )
  [IO.File]::WriteAllText(
    $stderrPath,
    $stderrTask.GetAwaiter().GetResult(),
    [Text.UTF8Encoding]::new($false)
  )

  if (-not (Test-Path -LiteralPath $resultPath)) {
    throw "$caseName did not produce result.json (exit $($process.ExitCode))"
  }

  $result = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $results.Add([ordered]@{
    case = $caseName
    api = [string]$capture.api
    processExitCode = $process.ExitCode
    processSeconds = [math]::Round($timer.Elapsed.TotalSeconds, 3)
    status = [string]$result.status
    resultPath = $resultPath
  })
}

$passed = @($results | Where-Object { $_.status -eq 'passed' }).Count
$summary = [ordered]@{
  schemaVersion = 1
  kind = 'action-visibility-test-run'
  generatedAt = (Get-Date).ToUniversalTime().ToString('o')
  captureManifest = $CaptureManifest
  total = $results.Count
  passed = $passed
  failed = $results.Count - $passed
  results = $results
}

$summaryPath = Join-Path $OutputRoot 'summary.json'
$summary | ConvertTo-Json -Depth 8 |
  Set-Content -LiteralPath $summaryPath -Encoding utf8
$summary | ConvertTo-Json -Depth 8

if ($passed -ne $results.Count) {
  exit 1
}
