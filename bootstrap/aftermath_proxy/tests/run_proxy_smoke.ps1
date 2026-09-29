[CmdletBinding()]
param(
  [ValidateSet('MSVC', 'ClangCL')]
  [string]$Toolchain = 'MSVC',

  [switch]$KeepOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$vswhere = Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath | Select-Object -First 1
if(-not $vs) { throw 'MSBuild was not found' }
$msbuild = Join-Path $vs 'MSBuild\Current\Bin\MSBuild.exe'
$dumpbin = & $vswhere -latest -products * -find 'VC\Tools\MSVC\**\bin\Hostx64\x64\dumpbin.exe' | Select-Object -First 1
if(-not $dumpbin) { throw 'dumpbin was not found' }

$platformToolset = if($Toolchain -eq 'ClangCL') { 'ClangCL' } else { 'v143' }
$configuration = if($Toolchain -eq 'ClangCL') { 'ClangRelease' } else { 'Release' }
$projects = @(
  'bootstrap\aftermath_proxy\aftermath_proxy.vcxproj',
  'bootstrap\aftermath_proxy\tests\original_fixture.vcxproj',
  'bootstrap\aftermath_proxy\tests\core_fixture.vcxproj',
  'bootstrap\aftermath_proxy\tests\proxy_smoke.vcxproj'
)
foreach($relativeProject in $projects)
{
  $arguments = @(
    (Join-Path $repo $relativeProject), '-nologo', '-t:Build', '-m:1', '-v:minimal',
    '-p:Configuration=Release', '-p:Platform=x64',
    "-p:PlatformToolset=$platformToolset",
    "-p:SolutionDir=$repo\"
  )
  & $msbuild @arguments
  if($LASTEXITCODE -ne 0) { throw "Build failed: $relativeProject" }
}

$output = Join-Path $repo "x64\$configuration\bootstrap\aftermath_proxy"
$proxy = Join-Path $output 'GFSDK_Aftermath_Lib.x64.dll'
$fixture = Join-Path $output 'tests\GFSDK_Aftermath_Lib_orig.dll'
$coreFixture = Join-Path $output 'tests\dgcore.dll'
$smoke = Join-Path $output 'tests\proxy_smoke.exe'
$definition = Join-Path $repo 'bootstrap\aftermath_proxy\aftermath_proxy.def'
$source = Join-Path $repo 'bootstrap\aftermath_proxy\aftermath_forward.cpp'
$assembly = Join-Path $repo 'bootstrap\aftermath_proxy\aftermath_forward.asm'

$expected = @(Get-Content -LiteralPath $definition | ForEach-Object {
  if($_ -match '^\s+([A-Za-z_][A-Za-z0-9_]*)\s*$') { $matches[1] }
})
$sourceText = Get-Content -LiteralPath $source -Raw
$sourceList = [regex]::Match(
  $sourceText, 'const char \*const ExportNames\[ExportCount\] = \{(.*?)\};',
  [Text.RegularExpressions.RegexOptions]::Singleline)
if(-not $sourceList.Success) { throw 'Could not locate the source export table' }
$sourceNames = @([regex]::Matches($sourceList.Groups[1].Value, '"([^"]+)"') |
  ForEach-Object { $_.Groups[1].Value })
$assemblyEntries = @(Get-Content -LiteralPath $assembly | ForEach-Object {
  if($_ -match '^AFTERMATH_FWD\s+(\w+)\s*,\s*(\d+),\s*(\d+)\s*$')
  {
    [pscustomobject]@{ Name = $matches[1]; Index = [int]$matches[2]; Offset = [int]$matches[3] }
  }
})
if($expected.Count -ne 43 -or $sourceNames.Count -ne 43 -or
   $assemblyEntries.Count -ne 43)
{
  throw 'Aftermath source export tables are not 43 entries each'
}
for($index = 0; $index -lt 43; ++$index)
{
  if($expected[$index] -cne $sourceNames[$index] -or
     $expected[$index] -cne $assemblyEntries[$index].Name -or
     $assemblyEntries[$index].Index -ne $index -or
     $assemblyEntries[$index].Offset -ne 8 * $index)
  {
    throw "Aftermath source export mapping differs at index $index"
  }
}

$exportOutput = & $dumpbin /nologo /exports $proxy
if($LASTEXITCODE -ne 0) { throw 'dumpbin /exports failed' }
$actual = @($exportOutput | ForEach-Object {
  if($_ -match '^\s+\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\S+)') { $matches[1] }
})
$mismatch = @(Compare-Object ($expected | Sort-Object) ($actual | Sort-Object))
if($expected.Count -ne 43 -or $actual.Count -ne 43 -or $mismatch.Count -ne 0)
{
  throw "Aftermath export mismatch: definition=$($expected.Count), binary=$($actual.Count)"
}

$names = @(
  'GFSDK_Aftermath_Lib_orig.dll',
  'GFSDK_Aftermath_Lib.x64.orig.dll',
  'GFSDK_Aftermath_Lib_orig.x64.dll'
)
$temporaryRoot = [IO.Path]::GetFullPath(
  (Join-Path $env:TEMP ("aftermath-proxy-smoke-" + [guid]::NewGuid().ToString('N'))))
$passed = $false
try
{
  New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
  for($index = 0; $index -lt $names.Count; ++$index)
  {
    $case = Join-Path $temporaryRoot ("case" + ($index + 1))
    New-Item -ItemType Directory -Path $case | Out-Null
    Copy-Item -LiteralPath $proxy -Destination (Join-Path $case 'GFSDK_Aftermath_Lib.x64.dll')
    Copy-Item -LiteralPath $fixture -Destination (Join-Path $case $names[$index])
    Copy-Item -LiteralPath $smoke -Destination (Join-Path $case 'proxy_smoke.exe')
    & (Join-Path $case 'proxy_smoke.exe')
    if($LASTEXITCODE -ne 0)
    {
      throw "Forwarding failed with $($names[$index]): exit $LASTEXITCODE"
    }
  }
  foreach($mode in @('marker', 'env', 'missing-core'))
  {
    $case = Join-Path $temporaryRoot $mode
    New-Item -ItemType Directory -Path $case | Out-Null
    Copy-Item -LiteralPath $proxy -Destination (Join-Path $case 'GFSDK_Aftermath_Lib.x64.dll')
    Copy-Item -LiteralPath $fixture -Destination (Join-Path $case 'GFSDK_Aftermath_Lib_orig.dll')
    Copy-Item -LiteralPath $smoke -Destination (Join-Path $case 'proxy_smoke.exe')
    if($mode -ne 'missing-core')
    {
      Copy-Item -LiteralPath $coreFixture -Destination (Join-Path $case 'dgcore.dll')
    }
    if($mode -eq 'marker')
    {
      New-Item -ItemType File -Path (Join-Path $case 'dgcore.enable') | Out-Null
    }
    $argument = if($mode -eq 'missing-core') { '--missing-core' } else { "--$mode" }
    & (Join-Path $case 'proxy_smoke.exe') $argument
    if($LASTEXITCODE -ne 0)
    {
      throw "$mode bootstrap check failed: exit $LASTEXITCODE"
    }
  }
  $passed = $true
  Write-Host "$Toolchain Aftermath proxy: 43 exports, three rename variants, and bootstrap modes passed"
}
finally
{
  if($passed -and -not $KeepOutput)
  {
    $tempBase = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    if(-not $temporaryRoot.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or
       -not [IO.Path]::GetFileName($temporaryRoot).StartsWith('aftermath-proxy-smoke-'))
    {
      throw "Refusing to remove unexpected test directory: $temporaryRoot"
    }
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
  }
  else
  {
    Write-Host "Test files: $temporaryRoot"
  }
}
