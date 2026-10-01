[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Python,
  [Parameter(Mandatory)][string]$OutputDirectory,
  [ValidateSet('MSVC','ClangCL','Both')][string]$Toolchain = 'Both'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$artifactRoot = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
$vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
$vsPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath | Select-Object -First 1
if(-not $vsPath) { throw 'MSBuild missing' }
$msbuild = Join-Path $vsPath 'MSBuild\Current\Bin\MSBuild.exe'
$generator = Join-Path $PSScriptRoot '..\proxy_builder.py'
$results = @()
function BuildFixture([string]$Project, [string]$Root, [string]$Name, [string]$Configuration, [string[]]$Extra = @()) {
  $buildOut = Join-Path $Root 'bin'
  $buildInt = Join-Path $Root 'obj'
  $log = Join-Path $Root 'build.log'
  New-Item -ItemType Directory -Path $Root -Force | Out-Null
  $buildArgs = @($Project, '/t:Build', '/m:4', '/v:minimal', '/nologo', "/p:Configuration=$Configuration", '/p:Platform=x64', '/p:ImportDirectoryBuildProps=false', '/p:ImportDirectoryBuildTargets=false', "/p:OutDir=$buildOut\", "/p:IntDir=$buildInt\", "/p:TargetName=$Name") + $Extra
  & $msbuild @buildArgs *> $log
  if($LASTEXITCODE -ne 0) { Get-Content -LiteralPath $log -Tail 35; throw "Native build failed: $Project" }
  return $buildOut
}
$toolchains = if($Toolchain -eq 'Both') { @('MSVC','ClangCL') } else { @($Toolchain) }
foreach($compiler in $toolchains) {
  $configuration = if($compiler -eq 'ClangCL') { 'ClangRelease' } else { 'Release' }
  $root = Join-Path $artifactRoot $compiler
  $fixtureBin = BuildFixture (Join-Path $PSScriptRoot 'fixture.vcxproj') (Join-Path $root 'fixture') 'fixture' $configuration
  $dataBin = BuildFixture (Join-Path $PSScriptRoot 'fixture.vcxproj') (Join-Path $root 'data') 'data' $configuration @("/p:FixtureDef=$(Join-Path $PSScriptRoot 'data.def')")
  $smokeBin = BuildFixture (Join-Path $PSScriptRoot 'smoke.vcxproj') (Join-Path $root 'smoke') 'proxy-smoke' $configuration
  $orderBin = BuildFixture (Join-Path $repo 'tools\capture-doctor\d3d12_order.vcxproj') (Join-Path $root 'order') 'd3d12-order' $configuration
  & $Python $generator generate (Join-Path $dataBin 'data.dll') --template app-local --output (Join-Path $root 'reject-data') *> (Join-Path $root 'reject-data.log')
  if($LASTEXITCODE -ne 2) { throw 'Data export must be rejected' }
  foreach($slot in @('fixture','dxgi','d3d11','d3d12')) {
    $sourceDll = if($slot -eq 'fixture') { Join-Path $fixtureBin 'fixture.dll' } else { Join-Path $env:SystemRoot "System32\$slot.dll" }
    $template = if($slot -eq 'fixture') { 'app-local' } else { 'system' }
    $generated = Join-Path $root "generated-$slot"
    if(Test-Path -LiteralPath $generated) { throw 'Choose a fresh output directory' }
      $extraBuild = if($slot -eq 'fixture') { @('--copy-original','--route','streamline-bootstrap') } else { @() }
      & $Python $generator build $sourceDll --template $template --output $generated --toolchain $compiler --msbuild $msbuild @extraBuild *> (Join-Path $root "generate-$slot.log")
      if($LASTEXITCODE -ne 0) {
        if($slot -eq 'd3d12' -and $LASTEXITCODE -eq 2 -and (Get-Content (Join-Path $root "generate-$slot.log") -Raw).Contains('Data/unknown export')) {
          $results += [pscustomobject]@{toolchain=$compiler; slot=$slot; contractVerified=$false; safelyRejected=$true; reason='Data/unknown export requires an explicit data-forwarding design'; sourceSHA256=(Get-FileHash -LiteralPath $sourceDll).Hash}
          continue
        }
        Get-Content (Join-Path $root "generate-$slot.log"); throw "Generation failed: $slot"
      }
    $receipt = Get-Content -LiteralPath (Join-Path $generated 'build-result.json') -Raw | ConvertFrom-Json
    if($receipt.status -ne 'verified') { throw 'One-command build was not verified' }
    $proxyBin = Split-Path -Parent $receipt.dll
    & $Python $generator verify $sourceDll (Join-Path $proxyBin "$slot.dll") *> (Join-Path $root "verify-$slot.json")
    if($LASTEXITCODE -ne 0) { throw "Export verification failed: $slot" }
    if($slot -eq 'fixture') {
      foreach($activation in @('disabled','enabled-missing-core')) {
        $priorEnable = $env:DCOMP_BOOTSTRAP_ENABLE
        try {
          $env:DCOMP_BOOTSTRAP_ENABLE = if($activation -eq 'disabled') { '0' } else { '1' }
          & (Join-Path $smokeBin 'proxy-smoke.exe') (Join-Path $proxyBin 'fixture.dll') *> (Join-Path $root "smoke-$activation.json")
          if($LASTEXITCODE -ne 0) { throw 'Generated proxy ABI/concurrency smoke failed' }
          & (Join-Path $smokeBin 'proxy-smoke.exe') (Join-Path $proxyBin 'fixture.dll') raw-eat *> (Join-Path $root "smoke-raw-eat-$activation.json")
          if($LASTEXITCODE -ne 0) { throw 'Raw EAT lookup proxy ABI/concurrency smoke failed' }
        } finally { $env:DCOMP_BOOTSTRAP_ENABLE = $priorEnable }
      }
    }
    $results += [pscustomobject]@{toolchain=$compiler; slot=$slot; contractVerified=$true; sourceSHA256=(Get-FileHash -LiteralPath $sourceDll).Hash; proxySHA256=(Get-FileHash -LiteralPath (Join-Path $proxyBin "$slot.dll")).Hash}
  }
  Write-Output "${compiler}: generated proxy contracts, ABI smoke and D3D12 fixture build passed"
}
$results | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $artifactRoot 'results.json') -Encoding utf8
# A safely rejected DATA export can leave the last native exit code at 2.
# Expected negative cases above are assertions, not a failed acceptance run.
exit 0
