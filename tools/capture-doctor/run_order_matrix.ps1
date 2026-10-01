[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Executable,
  [Parameter(Mandatory)][string]$Core,
  [Parameter(Mandatory)][string]$OutputDirectory
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$fixtureExe = (Resolve-Path -LiteralPath $Executable).Path
$fixtureCore = (Resolve-Path -LiteralPath $Core).Path
$fixtureOutput = [IO.Path]::GetFullPath($OutputDirectory)
if((Test-Path -LiteralPath $fixtureOutput) -and @(Get-ChildItem -LiteralPath $fixtureOutput -Force).Count) { throw 'Use a fresh empty output directory' }
New-Item -ItemType Directory -Path $fixtureOutput -Force | Out-Null
$results = @()
$identity = [pscustomobject]@{fixtureSHA256=(Get-FileHash -LiteralPath $fixtureExe -Algorithm SHA256).Hash; fixturePath=$fixtureExe; coreSHA256=(Get-FileHash -LiteralPath $fixtureCore -Algorithm SHA256).Hash; corePath=$fixtureCore}
foreach($phase in @('baseline', 'early', 'after-factory', 'after-swapchain')) {
  $report = Join-Path $fixtureOutput "$phase.jsonl"
  if(Test-Path -LiteralPath $report) { throw "Use a fresh output directory: $report exists" }
  & $fixtureExe $phase $report $fixtureCore (Join-Path $fixtureOutput $phase)
  $fixtureExit = $LASTEXITCODE
  $events = @(Get-Content -LiteralPath $report -Encoding utf8 | ForEach-Object { $_ | ConvertFrom-Json })
  $captureFiles = @(Get-ChildItem -LiteralPath $fixtureOutput -Filter "$($phase)*.rdc" | ForEach-Object { [pscustomobject]@{path=$_.FullName; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash; byteLength=$_.Length} })
  $results += [pscustomobject]@{phase=$phase; exitCode=$fixtureExit; events=$events; captures=$captureFiles; report=[pscustomobject]@{path=$report; sha256=(Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash}}
}
if((Get-FileHash -LiteralPath $fixtureExe).Hash -ne $identity.fixtureSHA256 -or (Get-FileHash -LiteralPath $fixtureCore).Hash -ne $identity.coreSHA256) { throw 'Fixture or Core changed during execution' }
[pscustomobject]@{schemaVersion=2; kind='d3d12-order-matrix'; identity=$identity; phases=$results; scope='Owned fixture only; no external game observations'} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $fixtureOutput 'matrix.json') -Encoding utf8
$results | Select-Object phase,exitCode
# A late phase can fail by design; the recorded result is evidence, not a test
# assertion that all injection phases must yield a complete capture.
