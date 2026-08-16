[CmdletBinding()]
param(
  [ValidateSet('MSVC', 'ClangCL')]
  [string]$Toolchain = 'MSVC',

  [ValidateSet('Win32', 'x64')]
  [string]$Platform = 'x64'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$vswherePath = Join-Path ${env:ProgramFiles(x86)} `
  'Microsoft Visual Studio\Installer\vswhere.exe'
if(-not (Test-Path -LiteralPath $vswherePath -PathType Leaf))
{
  throw "vswhere.exe was not found: $vswherePath"
}

$dumpbinPath = & $vswherePath -latest -products * `
  -find 'VC\Tools\MSVC\**\bin\Hostx64\x64\dumpbin.exe' | Select-Object -First 1
if(-not $dumpbinPath)
{
  throw 'dumpbin.exe was not found'
}

function Get-ExportMap([string]$Path)
{
  $output = & $dumpbinPath /nologo /exports $Path 2>&1
  if($LASTEXITCODE -ne 0)
  {
    throw "dumpbin /exports failed for $Path"
  }

  $exports = [ordered]@{}
  foreach($line in $output)
  {
    if($line -match '^\s+(\d+)\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\S+)')
    {
      $name = $matches[2]
      if(-not $name.StartsWith('['))
      {
        $exports[$name] = [int]$matches[1]
      }
    }
  }

  return $exports
}

$configurationDirectory = if($Toolchain -eq 'ClangCL') { 'ClangRelease' } else { 'Release' }
$outputRoot = Join-Path $repositoryRoot "$Platform\$configurationDirectory"
$systemDirectoryName = if($Platform -eq 'Win32') { 'SysWOW64' } else { 'System32' }
$systemRoot = Join-Path $env:SystemRoot $systemDirectoryName
$proxies = [ordered]@{
  'dxgi.dll' = 'bootstrap\dxgi_proxy\dxgi.dll'
  'd3d11.dll' = 'bootstrap\d3d11_proxy\d3d11.dll'
  'd3d12.dll' = 'bootstrap\d3d12_proxy\d3d12.dll'
}

$errors = [System.Collections.Generic.List[string]]::new()
foreach($systemFileName in $proxies.Keys)
{
  $systemDll = Join-Path $systemRoot $systemFileName
  $proxyDll = Join-Path $outputRoot $proxies[$systemFileName]
  if(-not (Test-Path -LiteralPath $systemDll -PathType Leaf))
  {
    $errors.Add("System DLL is missing: $systemDll")
    continue
  }
  if(-not (Test-Path -LiteralPath $proxyDll -PathType Leaf))
  {
    $errors.Add("Bootstrap DLL is missing: $proxyDll")
    continue
  }

  $systemExports = Get-ExportMap $systemDll
  $proxyExports = Get-ExportMap $proxyDll
  foreach($name in $systemExports.Keys)
  {
    if(-not $proxyExports.Contains($name))
    {
      $errors.Add("$proxyDll is missing export $name")
    }
    elseif($proxyExports[$name] -ne $systemExports[$name])
    {
      $errors.Add(
        "$proxyDll export $name has ordinal $($proxyExports[$name]); " +
        "$systemDll uses $($systemExports[$name])")
    }
  }
  foreach($name in $proxyExports.Keys)
  {
    if(-not $systemExports.Contains($name))
    {
      $errors.Add("$proxyDll has extra export $name")
    }
  }
}

if($errors.Count -gt 0)
{
  $errors | ForEach-Object { Write-Error $_ }
  exit 1
}

Write-Host "Bootstrap exports match $systemDirectoryName for $Toolchain $Platform"
