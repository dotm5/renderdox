function Get-DCompWindowsToolchain
{
  [CmdletBinding()]
  param(
    [ValidatePattern('^(Auto|v[0-9]+)$')]
    [string]$PlatformToolset = 'Auto',
    [string]$WindowsSDKVersion
  )

  $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  if(-not (Test-Path -LiteralPath $vswhere -PathType Leaf))
  {
    throw "vswhere.exe was not found: $vswhere"
  }
  # Without -prerelease, vswhere selects the latest installed release channel.
  $visualStudio = & $vswhere -latest -products * -requires `
    Microsoft.Component.MSBuild Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
  if($LASTEXITCODE -ne 0 -or -not $visualStudio)
  {
    throw 'A stable Visual Studio installation with MSBuild and C++ tools was not found'
  }
  $auxiliary = Join-Path $visualStudio 'VC\Auxiliary\Build'
  if($PlatformToolset -eq 'Auto')
  {
    $defaultVersion = (Get-Content -LiteralPath `
      (Join-Path $auxiliary 'Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
    $candidates = @(Get-ChildItem -LiteralPath $auxiliary -File `
      -Filter 'Microsoft.VCToolsVersion.v*.default.txt' |
      Where-Object {
        $_.Name -match '\.v[0-9]+\.default\.txt$' -and
        (Get-Content -LiteralPath $_.FullName -Raw).Trim() -eq $defaultVersion
      } | Sort-Object { [int]([regex]::Match($_.Name, '\.v([0-9]+)\.').Groups[1].Value) } `
      -Descending)
    if($candidates.Count -eq 0)
    {
      throw "No platform toolset matches the default C++ tools $defaultVersion"
    }
    $PlatformToolset = [regex]::Match($candidates[0].Name, '\.(v[0-9]+)\.').Groups[1].Value
  }
  $versionFile = Join-Path $auxiliary "Microsoft.VCToolsVersion.$PlatformToolset.default.txt"
  $toolsVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
  $toolsRoot = Join-Path $visualStudio "VC\Tools\MSVC\$toolsVersion"
  if(-not (Test-Path -LiteralPath (Join-Path $toolsRoot 'bin\Hostx64\x64\cl.exe')))
  {
    throw "The $PlatformToolset compiler is missing below $toolsRoot"
  }
  $msbuild = Join-Path $visualStudio 'MSBuild\Current\Bin\amd64\MSBuild.exe'
  if(-not (Test-Path -LiteralPath $msbuild -PathType Leaf))
  {
    throw "MSBuild.exe was not found: $msbuild"
  }

  $kitsRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
  $sdkVersions = @(Get-ChildItem -LiteralPath (Join-Path $kitsRoot 'Include') -Directory |
    Where-Object { $_.Name -match '^10\.0\.[0-9]+\.0$' } |
    Sort-Object { [version]$_.Name } -Descending)
  if($WindowsSDKVersion)
  {
    $sdkVersions = @($sdkVersions | Where-Object { $_.Name -eq $WindowsSDKVersion })
  }
  $completeSDKs = @($sdkVersions | Where-Object {
    $version = $_.Name
    $required = @(
      "Include\$version\um\Windows.h",
      "Include\$version\shared\sdkddkver.h",
      "Include\$version\ucrt\corecrt.h",
      "Lib\$version\um\x64\kernel32.lib",
      "Lib\$version\ucrt\x64\ucrt.lib",
      "bin\$version\x64\rc.exe"
    )
    @($required | Where-Object {
      -not (Test-Path -LiteralPath (Join-Path $kitsRoot $_) -PathType Leaf)
    }).Count -eq 0
  })
  if($completeSDKs.Count -eq 0)
  {
    throw "A complete Windows SDK was not found (requested: $WindowsSDKVersion)"
  }
  [pscustomobject]@{
    VisualStudioPath = $visualStudio
    MSBuildPath = $msbuild
    PlatformToolset = $PlatformToolset
    VCToolsVersion = $toolsVersion
    ToolsRoot = $toolsRoot
    WindowsSDKVersion = $completeSDKs[0].Name
  }
}
