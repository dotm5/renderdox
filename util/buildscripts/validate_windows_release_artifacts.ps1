[CmdletBinding()]
param(
  [ValidateSet('Win32', 'x64')]
  [string]$Platform = 'x64',

  [string]$RepositoryRoot =
      (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path,

  [string]$VisualStudioPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if([string]::IsNullOrWhiteSpace($VisualStudioPath))
{
  $vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  if(-not (Test-Path -LiteralPath $vswherePath -PathType Leaf))
  {
    throw "Visual Studio locator not found: $vswherePath"
  }

  $VisualStudioPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
    -property installationPath
}

$dumpbinPath = Get-ChildItem -Path `
    (Join-Path $VisualStudioPath 'VC\Tools\MSVC\*\bin\Hostx64\x64\dumpbin.exe') -File |
  Sort-Object FullName -Descending |
  Select-Object -First 1 -ExpandProperty FullName
if(-not $dumpbinPath)
{
  throw "dumpbin.exe was not found below $VisualStudioPath"
}

function Get-ExportContract
{
  param([Parameter(Mandatory)][string]$Path)

  if(-not (Test-Path -LiteralPath $Path -PathType Leaf))
  {
    throw "Binary is missing: $Path"
  }

  $rows = [System.Collections.Generic.List[string]]::new()
  $inExportTable = $false
  foreach($line in (& $dumpbinPath /nologo /exports $Path))
  {
    if($line -match '^\s*ordinal\s+hint\s+RVA\s+name')
    {
      $inExportTable = $true
      continue
    }
    if($inExportTable -and $line -match '^\s*Summary')
    {
      break
    }
    if($inExportTable -and
       $line -match '^\s*(\d+)\s+(?:[0-9A-F]+\s+)?[0-9A-F]{8,16}\s+(.+?)\s*$')
    {
      $name = $matches[2]
      if($name.StartsWith('[NONAME]', [StringComparison]::Ordinal))
      {
        $name = '[NONAME]'
      }
      else
      {
        $name = $name -replace '\s+=.*$', ''
      }

      [void]$rows.Add(('{0}|{1}' -f [int]$matches[1], $name))
    }
  }

  if($rows.Count -eq 0)
  {
    throw "No exports could be parsed from $Path"
  }

  return @($rows | Sort-Object)
}

$outputRoot = Join-Path $RepositoryRoot "$Platform\Release"
$systemDirectory = if($Platform -eq 'x64')
{
  Join-Path $env:WINDIR 'System32'
}
else
{
  Join-Path $env:WINDIR 'SysWOW64'
}

foreach($proxy in @(
  @{ Name = 'DXGI'; File = 'dxgi.dll'; Output = 'bootstrap\dxgi_proxy\dxgi.dll' },
  @{ Name = 'D3D11'; File = 'd3d11.dll'; Output = 'bootstrap\d3d11_proxy\d3d11.dll' },
  @{ Name = 'D3D12'; File = 'd3d12.dll'; Output = 'bootstrap\d3d12_proxy\d3d12.dll' }
))
{
  $expected = Get-ExportContract (Join-Path $systemDirectory $proxy.File)
  $actual = Get-ExportContract (Join-Path $outputRoot $proxy.Output)
  $difference = @(Compare-Object $expected $actual)
  if($difference.Count -gt 0)
  {
    $details = ($difference | Format-Table -AutoSize | Out-String).Trim()
    throw "$($proxy.Name) proxy export contract differs from $systemDirectory\$($proxy.File):`n$details"
  }

  Write-Host "$($proxy.Name) export contract passed ($($expected.Count) exports)"
}

[xml]$identityProps =
    Get-Content -LiteralPath (Join-Path $RepositoryRoot 'build\product_identity.props') -Raw
$coreBaseName =
    $identityProps.SelectSingleNode('//*[local-name()="RDocCoreBaseName"]').InnerText
$corePath = Join-Path $outputRoot "$coreBaseName.dll"
$coreExports = Get-ExportContract $corePath
foreach($requiredExport in @('DCOMP_GetAPI', 'DCOMP_SetHookMode'))
{
  if(-not ($coreExports -match "\|$([regex]::Escape($requiredExport))$"))
  {
    throw "$corePath does not export $requiredExport"
  }
}
if($coreExports -match '\|RENDERDOC_GetAPI$')
{
  throw "$corePath still exports legacy RENDERDOC_GetAPI"
}

Write-Host "Core API export contract passed: $corePath"
