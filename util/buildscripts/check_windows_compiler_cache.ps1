#requires -Version 7.2
<#
Exercises the opt-in compiler-cache profile with real Windows C++ tools. The
fixture has a PCH creator, a PCH consumer in another directory, and a source
which explicitly disables both the forced header and debug information.

Every compilation uses Rebuild: a warm result must come from sccache rather
than MSBuild deciding that an existing object is up to date. The fixture uses
its own cache directory and server port, leaving the native build's cache and
statistics untouched. Logs are retained under OutputDirectory on failure.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$CacheToolDirectory,
  [Parameter(Mandatory = $true)]
  [string]$OutputDirectory,
  [ValidateRange(1, 16)]
  [int]$MaxCpuCount = 4
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# A deliberately failing compile is one of the checks below.
$PSNativeCommandUseErrorActionPreference = $false
. (Join-Path $PSScriptRoot 'windows_toolchain.ps1')
$toolchain = Get-DCompWindowsToolchain
$cacheTargets = Join-Path $PSScriptRoot 'sccache.targets'
$CacheToolDirectory = (Resolve-Path -LiteralPath $CacheToolDirectory).Path
foreach($name in @('cl.exe', 'clang-cl.exe'))
{
  if(-not (Test-Path -LiteralPath (Join-Path $CacheToolDirectory $name) -PathType Leaf))
  {
    throw "Missing compiler-cache proxy: $name"
  }
}
$sccachePath = (Get-Command sccache.exe -CommandType Application -ErrorAction Stop).Source
$sessionRoot = Join-Path ([System.IO.Path]::GetFullPath($OutputDirectory)) `
  ('smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null

function Invoke-Sccache
{
  param([string[]]$Arguments)
  $result = & $sccachePath @Arguments 2>&1
  if($LASTEXITCODE -ne 0)
  {
    throw "sccache $($Arguments -join ' ') failed: $($result -join [Environment]::NewLine)"
  }
  return ($result -join [Environment]::NewLine)
}

function Get-CacheCounts
{
  $document = (Invoke-Sccache -Arguments @('--show-stats', '--stats-format=json')) |
    ConvertFrom-Json -AsHashtable
  $stats = $document['stats']
  if($null -eq $stats -or -not $stats.ContainsKey('cache_hits') -or
     -not $stats.ContainsKey('cache_misses'))
  {
    throw 'sccache returned an unexpected statistics schema'
  }
  $hits = [long]0
  $misses = [long]0
  foreach($value in $stats['cache_hits']['counts'].Values) { $hits += [long]$value }
  foreach($value in $stats['cache_misses']['counts'].Values) { $misses += [long]$value }
  return [pscustomobject]@{
    Hits = $hits
    Misses = $misses
    Uncacheable = [long]$stats['requests_not_cacheable'] +
                  [long]$stats['non_cacheable_compilations']
    Unsupported = [long]$stats['requests_unsupported_compiler']
    WriteErrors = [long]$stats['cache_write_errors']
    Raw = $document
  }
}

function Invoke-SmokeBuild
{
  param(
    [string]$Project,
    [hashtable]$Route,
    [string]$Phase,
    [string]$Target = 'Rebuild',
    [bool]$CacheEnabled = $true
  )
  $projectDirectory = Split-Path -Parent $Project
  $logPath = Join-Path $projectDirectory "$Phase.log"
  $arguments = @(
    $Project, "-t:$Target", '-nologo', '-v:minimal', '-nr:false',
    "-m:$MaxCpuCount", '-p:Configuration=Release', '-p:Platform=x64',
    '-p:PreferredToolArchitecture=x64', "-p:PlatformToolset=$($Route.Toolset)",
    "-p:VCToolsVersion=$($toolchain.VCToolsVersion)",
    "-p:WindowsTargetPlatformVersion=$($toolchain.WindowsSDKVersion)",
    "-p:SolutionDir=$projectDirectory\",
    "-p:RDocUseCompilerCache=$($CacheEnabled.ToString().ToLowerInvariant())",
    "-p:RDocUseMsvcFrontend=$($Route.Fallback)",
    "-p:RDocSccacheCompilerDir=$CacheToolDirectory",
    "-p:SmokeClangValue=$($Route.ClangValue)",
    "-p:SmokeRouteId=$($Route.Id)",
    "-bl:$(Join-Path $projectDirectory "$Phase.binlog")"
  )
  & $toolchain.MSBuildPath @arguments *> $logPath
  $code = $LASTEXITCODE
  return [pscustomobject]@{
    ExitCode = $code
    LogPath = $logPath
    Text = Get-Content -LiteralPath $logPath -Raw
  }
}

function Assert-SmokeSuccess
{
  param($Result, [string]$Description)
  if($Result.ExitCode -ne 0)
  {
    Write-Host $Result.Text
    throw "$Description failed; see $($Result.LogPath)"
  }
}

function Assert-CacheCounts
{
  param($Counts, [long]$Hits, [long]$Misses, [string]$Description)
  if($Counts.Hits -ne $Hits -or $Counts.Misses -ne $Misses -or
     $Counts.Uncacheable -ne 0 -or $Counts.Unsupported -ne 0 -or
     $Counts.WriteErrors -ne 0)
  {
    Write-Host ($Counts.Raw | ConvertTo-Json -Depth 20)
    throw "$Description expected $Hits hits and $Misses misses, with no bypasses or write errors"
  }
}

# These values are restored even if an assertion or a compiler invocation fails.
$environmentNames = @('SCCACHE_DIR', 'SCCACHE_SERVER_PORT', 'SCCACHE_CACHE_SIZE')
$previousEnvironment = @{}
foreach($name in $environmentNames)
{
  $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$serverStarted = $false
try
{
  # Reserve an available local port briefly to avoid sharing the native server.
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  $listener.Start()
  $port = $listener.LocalEndpoint.Port
  $listener.Stop()
  $env:SCCACHE_SERVER_PORT = [string]$port
  $env:SCCACHE_DIR = Join-Path $sessionRoot 'cache'
  $env:SCCACHE_CACHE_SIZE = '64M'
  Invoke-Sccache -Arguments @('--start-server') | Out-Null
  $serverStarted = $true

  $routes = @(
    @{ Name = 'msvc'; Id = 1; Toolset = $toolchain.PlatformToolset; Fallback = 'false';
       ToolExe = 'cl.exe'; ClangValue = 0 },
    @{ Name = 'clangcl'; Id = 2; Toolset = 'ClangCL'; Fallback = 'false';
       ToolExe = 'clang-cl.exe'; ClangValue = 1 },
    @{ Name = 'clangcl_msvc'; Id = 3; Toolset = 'ClangCL'; Fallback = 'true';
       ToolExe = 'cl.exe'; ClangValue = 0 }
  )

  foreach($route in $routes)
  {
    $routeRoot = Join-Path $sessionRoot $route.Name
    New-Item -ItemType Directory -Path (Join-Path $routeRoot 'pch'),
      (Join-Path $routeRoot 'src') -Force | Out-Null
    $headerPath = Join-Path $routeRoot 'pch\precompiled.h'
    Set-Content -LiteralPath $headerPath -Encoding utf8 -Value @'
#pragma once
#define RENDERDOX_SMOKE_VALUE 7
'@
    $consumerText = @'
#ifndef RENDERDOX_SMOKE_VALUE
#error RENDERDOX_CACHE_FORCED_INCLUDE_MISSING
#endif
#if RENDERDOX_SMOKE_EXPECT_CLANG
#ifndef __clang__
#error RENDERDOX_CACHE_WRONG_COMPILER
#endif
#else
#ifdef __clang__
#error RENDERDOX_CACHE_WRONG_COMPILER
#endif
#endif
int consumer_value() { return RENDERDOX_SMOKE_VALUE + RENDERDOX_SMOKE_ROUTE_ID; }
'@
    Set-Content -LiteralPath (Join-Path $routeRoot 'src\consumer.cpp') `
      -Encoding utf8 -Value $consumerText
    Set-Content -LiteralPath (Join-Path $routeRoot 'pch\precompiled.cpp') `
      -Encoding utf8 -Value 'int creator_value() { return RENDERDOX_SMOKE_VALUE + RENDERDOX_SMOKE_ROUTE_ID; }'
    Set-Content -LiteralPath (Join-Path $routeRoot 'src\plain.cpp') -Encoding utf8 -Value @'
#ifdef RENDERDOX_SMOKE_VALUE
#error RENDERDOX_CACHE_FORCED_INCLUDE_LEAKED
#endif
int plain_value() { return RENDERDOX_SMOKE_ROUTE_ID; }
'@

    $projectTemplate = @'
<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64"><Configuration>Release</Configuration><Platform>x64</Platform></ProjectConfiguration>
  </ItemGroup>
  <PropertyGroup Label="Globals">
    <ProjectGuid>{98AC2B18-C90C-4725-9B29-3B8B1974046A}</ProjectGuid>
    <Keyword>Win32Proj</Keyword>
    <ImportDirectoryBuildProps>false</ImportDirectoryBuildProps>
    <ImportDirectoryBuildTargets>false</ImportDirectoryBuildTargets>
  </PropertyGroup>
  <!-- Match the early opt-in properties in Directory.Build.props. -->
  <PropertyGroup Condition="'$(RDocUseCompilerCache)'=='true'">
    <UseMultiToolTask>true</UseMultiToolTask>
    <EnforceProcessCountAcrossBuilds>true</EnforceProcessCountAcrossBuilds>
    <TrackFileAccess>false</TrackFileAccess>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\Microsoft.Cpp.Default.props" />
  <PropertyGroup Label="Configuration"><ConfigurationType>StaticLibrary</ConfigurationType><UseDebugLibraries>false</UseDebugLibraries></PropertyGroup>
  <Import Project="$(VCTargetsPath)\Microsoft.Cpp.props" />
  <PropertyGroup>
    <OutDir>$(ProjectDir)out\</OutDir><IntDir>$(ProjectDir)obj\</IntDir>
    <TargetName>cache_smoke</TargetName>
    <LlvmArchitectureSwitch Condition="'$(RDocUseMsvcFrontend)'=='true'" />
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <PrecompiledHeader>Use</PrecompiledHeader>
      <PrecompiledHeaderFile>precompiled.h</PrecompiledHeaderFile>
      <ForcedIncludeFiles>precompiled.h</ForcedIncludeFiles>
      <DebugInformationFormat>ProgramDatabase</DebugInformationFormat>
      <MultiProcessorCompilation>true</MultiProcessorCompilation>
      <Optimization>Disabled</Optimization>
      <RuntimeLibrary>MultiThreaded</RuntimeLibrary>
      <PreprocessorDefinitions>RENDERDOX_SMOKE_EXPECT_CLANG=$(SmokeClangValue);RENDERDOX_SMOKE_ROUTE_ID=$(SmokeRouteId);%(PreprocessorDefinitions)</PreprocessorDefinitions>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="pch\precompiled.cpp"><PrecompiledHeader>Create</PrecompiledHeader></ClCompile>
    <ClCompile Include="src\consumer.cpp" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\Microsoft.Cpp.targets" />
  <Import Project="__CACHE_TARGETS__" />
  <!-- Deliberately added after the targets import, like version.cpp. -->
  <ItemGroup>
    <ClCompile Include="src\plain.cpp">
      <PrecompiledHeader>NotUsing</PrecompiledHeader><ForcedIncludeFiles />
      <DebugInformationFormat>None</DebugInformationFormat>
    </ClCompile>
  </ItemGroup>
  <Target Name="WriteSmokeMetadata" DependsOnTargets="RDocConfigureCompilerCache">
    <WriteLinesToFile File="$(ProjectDir)metadata.txt" Overwrite="true"
      Lines="TOOL|$(CLToolExe)|$(CLToolPath);MULTI|$(UseMultiToolTask);@(ClCompile->'%(Filename)|%(PrecompiledHeader)|%(DebugInformationFormat)|%(ForcedIncludeFiles)|%(MultiProcessorCompilation)')" />
  </Target>
</Project>
'@
    $projectPath = Join-Path $routeRoot 'cache_smoke.vcxproj'
    $projectTemplate.Replace('__CACHE_TARGETS__', [System.Security.SecurityElement]::Escape($cacheTargets)) |
      Set-Content -LiteralPath $projectPath -Encoding utf8

    $result = Invoke-SmokeBuild -Project $projectPath -Route $route -Phase 'metadata' `
      -Target WriteSmokeMetadata
    Assert-SmokeSuccess $result "$($route.Name) metadata evaluation"
    $metadata = @(Get-Content -LiteralPath (Join-Path $routeRoot 'metadata.txt'))
    $expectedTool = "TOOL|$($route.ToolExe)|$CacheToolDirectory"
    if($metadata -notcontains $expectedTool -or $metadata -notcontains 'MULTI|true')
    {
      throw "$($route.Name) selected an incorrect compiler proxy or task mode: $($metadata -join '; ')"
    }
    foreach($expected in @(
      'precompiled|NotUsing|OldStyle|precompiled.h|false',
      'consumer|NotUsing|OldStyle|precompiled.h|false',
      'plain|NotUsing|None||false'))
    {
      if($metadata -notcontains $expected) { throw "Missing cache metadata: $expected" }
    }

    # Prove opting out still leaves the original PCH and debug profile intact.
    $result = Invoke-SmokeBuild -Project $projectPath -Route $route -Phase 'disabled' `
      -Target WriteSmokeMetadata -CacheEnabled $false
    Assert-SmokeSuccess $result "$($route.Name) opt-out metadata evaluation"
    $metadata = @(Get-Content -LiteralPath (Join-Path $routeRoot 'metadata.txt'))
    foreach($expected in @(
      'precompiled|Create|ProgramDatabase|precompiled.h|true',
      'consumer|Use|ProgramDatabase|precompiled.h|true',
      'plain|NotUsing|None||true'))
    {
      if($metadata -notcontains $expected) { throw "Opt-out changed source metadata: $expected" }
    }

    Invoke-Sccache -Arguments @('--zero-stats') | Out-Null
    $result = Invoke-SmokeBuild -Project $projectPath -Route $route -Phase 'cold'
    Assert-SmokeSuccess $result "$($route.Name) cold rebuild"
    Assert-CacheCounts (Get-CacheCounts) 0 3 "$($route.Name) cold rebuild"
    # Waiting for server shutdown also flushes pending cache writes.
    Invoke-Sccache -Arguments @('--stop-server') | Out-Null
    $serverStarted = $false
    Invoke-Sccache -Arguments @('--start-server') | Out-Null
    $serverStarted = $true

    $result = Invoke-SmokeBuild -Project $projectPath -Route $route -Phase 'warm'
    Assert-SmokeSuccess $result "$($route.Name) warm rebuild"
    Assert-CacheCounts (Get-CacheCounts) 3 0 "$($route.Name) warm rebuild"

    # Both forced-header consumers must miss; the independent source must hit.
    Set-Content -LiteralPath $headerPath -Encoding utf8 -Value @'
#pragma once
#define RENDERDOX_SMOKE_VALUE 9
'@
    Invoke-Sccache -Arguments @('--zero-stats') | Out-Null
    $result = Invoke-SmokeBuild -Project $projectPath -Route $route -Phase 'header_changed'
    Assert-SmokeSuccess $result "$($route.Name) changed-header rebuild"
    Assert-CacheCounts (Get-CacheCounts) 1 2 "$($route.Name) changed-header rebuild"

    Set-Content -LiteralPath (Join-Path $routeRoot 'src\consumer.cpp') -Encoding utf8 `
      -Value '#error RENDERDOX_CACHE_EXPECTED_ERROR'
    $result = Invoke-SmokeBuild -Project $projectPath -Route $route -Phase 'expected_error'
    if($result.ExitCode -eq 0 -or $result.Text -notmatch 'RENDERDOX_CACHE_EXPECTED_ERROR')
    {
      Write-Host $result.Text
      throw "$($route.Name) did not propagate the intentional compiler error"
    }
    Write-Host "$($route.Name): cold 3 misses, warm 3 hits, changed header 2 misses, compiler error propagated"
  }
  Write-Host "Compiler-cache smoke checks passed. Logs: $sessionRoot"
}
finally
{
  if($serverStarted)
  {
    # Cleanup must not replace the original assertion or compilation failure.
    & $sccachePath --stop-server *> $null
  }
  foreach($name in $environmentNames)
  {
    [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
  }
}
