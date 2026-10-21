[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$OutputDirectory,
  [switch]$FingerprintOnly,
  [string]$FingerprintCachePath,
  [switch]$CacheKeyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'windows_toolchain.ps1')
$selected = Get-DCompWindowsToolchain
$msvcDirectory = Join-Path $selected.ToolsRoot 'bin\Hostx64\x64'
$llvmRoot = Join-Path $selected.VisualStudioPath 'VC\Tools\Llvm'
$llvmCandidates = @(
  (Join-Path $llvmRoot 'x64\bin'),
  (Join-Path $llvmRoot 'bin')
)
$llvmDirectory = $llvmCandidates | Where-Object {
  Test-Path -LiteralPath (Join-Path $_ 'clang-cl.exe') -PathType Leaf
} | Select-Object -First 1
if(-not $llvmDirectory)
{
  throw "The selected Visual Studio installation has no clang-cl.exe below $llvmRoot"
}

# This memo only applies to the unmodified toolchain supplied by an immutable
# GitHub-hosted runner image. Local and self-hosted builds always hash binaries.
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$compilerFiles = @(
  (Join-Path $msvcDirectory 'cl.exe'),
  (Join-Path $msvcDirectory 'c1.dll'),
  (Join-Path $msvcDirectory 'c1xx.dll'),
  (Join-Path $msvcDirectory 'c2.dll'),
  (Join-Path $llvmDirectory 'clang-cl.exe'),
  (Join-Path $llvmDirectory 'lld-link.exe'),
  $selected.MSBuildPath
)
$linkFiles = @('link.exe', 'lib.exe') | ForEach-Object { Join-Path $msvcDirectory $_ }
$memoKey = ''
if($env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_ENVIRONMENT -ceq 'github-hosted' -and
   -not [string]::IsNullOrWhiteSpace($env:ImageOS) -and
   -not [string]::IsNullOrWhiteSpace($env:ImageVersion))
{
  $memoIdentity = [ordered]@{
    schema = 1
    image_os = $env:ImageOS
    image_version = $env:ImageVersion
    workspace = $workspace
    dependency_sha256 = $env:QRENDERDOC_THIRDPARTY_SHA256
    toolchain = $selected
    compiler_paths = $compilerFiles
    native_link_paths = $linkFiles
    scripts = @($PSCommandPath, (Join-Path $PSScriptRoot 'windows_toolchain.ps1')) |
      ForEach-Object {
        [ordered]@{
          path = $_
          sha256 = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash
        }
      }
  }
  $memoIdentityJson = $memoIdentity | ConvertTo-Json -Depth 5 -Compress
  $memoDigest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
    [Text.Encoding]::UTF8.GetBytes($memoIdentityJson))).ToLowerInvariant()
  $memoKey = "windows-compiler-fingerprint-v1-$memoDigest"
}
if($CacheKeyOnly)
{
  # This phase runs before actions/cache/restore. It must not need sccache,
  # create proxies or output directories, alter the compiler environment, or
  # hash the large compiler/linker binaries.
  if($env:GITHUB_OUTPUT)
  {
    "fingerprint-cache-key=$memoKey" | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8
  }
  Write-Host "Compiler fingerprint memo key: $memoKey"
  return
}

$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$parallelJobs = [Environment]::ProcessorCount
if(-not $FingerprintOnly)
{
  $sccache = (Get-Command sccache.exe -CommandType Application -ErrorAction Stop).Source
  foreach($name in @('cl.exe', 'clang-cl.exe'))
  {
    Copy-Item -LiteralPath $sccache -Destination (Join-Path $OutputDirectory $name) -Force
  }
  # The proxy directory stays off PATH. A renamed sccache executable searches
  # PATH for the real compiler with its own name, including fallback cl.exe.
  $env:PATH = "$msvcDirectory;$llvmDirectory;$env:PATH"
  $env:RDocUseCompilerCache = 'true'
  $env:RDocSccacheCompilerDir = $OutputDirectory
  $env:CL_MPCOUNT = $parallelJobs.ToString()
}

foreach($file in @($compilerFiles) + @($linkFiles))
{
  if(-not (Test-Path -LiteralPath $file -PathType Leaf))
  {
    throw "Compiler cache identity input is missing: $file"
  }
}

function Get-CachedBinaryFingerprints
{
  param([object[]]$Entries, [string[]]$ExpectedFiles)
  if($Entries.Count -ne $ExpectedFiles.Count) { throw 'Unexpected binary inventory' }
  for($i = 0; $i -lt $ExpectedFiles.Count; $i++)
  {
    $entry = $Entries[$i]
    if($entry -isnot [System.Collections.IDictionary] -or $entry.Count -ne 2 -or
       $entry['path'] -isnot [string] -or $entry['path'] -cne $ExpectedFiles[$i] -or
       $entry['sha256'] -isnot [string] -or $entry['sha256'] -cnotmatch '^[0-9A-F]{64}$')
    {
      throw 'Unexpected binary path or SHA256'
    }
    [ordered]@{ path = $ExpectedFiles[$i]; sha256 = $entry['sha256'] }
  }
}

function New-CompilerFingerprintJson
{
  param([object[]]$CompilerFingerprints, [object[]]$LinkFingerprints)
  # Keep the original property order, JSON depth and values: these strings
  # define the existing compiler-key and toolchain-key cache namespaces.
  $compilerIdentity = [ordered]@{
    schema = 1
    platform = 'x64'
    toolchain = $selected
    compilers = @($CompilerFingerprints)
    dependency_sha256 = $env:QRENDERDOC_THIRDPARTY_SHA256
    workspace = $workspace
  }
  $identity = [ordered]@{
    compiler = $compilerIdentity
    image_os = $env:ImageOS
    image_version = $env:ImageVersion
    native_link_tools = $LinkFingerprints
  }
  [pscustomobject]@{
    CompilerJson = ($compilerIdentity | ConvertTo-Json -Depth 5 -Compress)
    IdentityJson = ($identity | ConvertTo-Json -Depth 7 -Compress)
  }
}

$memoHit = $false
$fingerprintJson = $null
if($memoKey -and -not [string]::IsNullOrWhiteSpace($FingerprintCachePath) -and
   (Test-Path -LiteralPath $FingerprintCachePath -PathType Leaf))
{
  try
  {
    $memo = Get-Content -LiteralPath $FingerprintCachePath -Raw |
      ConvertFrom-Json -AsHashtable
    if($memo -isnot [System.Collections.IDictionary] -or $memo.Count -ne 4 -or
       $memo['schema'] -ne 1 -or $memo['fingerprint_cache_key'] -isnot [string] -or
       $memo['fingerprint_cache_key'] -cne $memoKey -or
       $memo['compiler_json'] -isnot [string] -or $memo['identity_json'] -isnot [string])
    {
      throw 'Unexpected memo schema or environment key'
    }
    $cachedCompiler = $memo['compiler_json'] | ConvertFrom-Json -AsHashtable
    $cachedIdentity = $memo['identity_json'] | ConvertFrom-Json -AsHashtable
    if($cachedCompiler -isnot [System.Collections.IDictionary] -or
       $cachedIdentity -isnot [System.Collections.IDictionary])
    {
      throw 'Unexpected compiler identity JSON'
    }
    $cachedCompilers = @(Get-CachedBinaryFingerprints `
      -Entries $cachedCompiler['compilers'] -ExpectedFiles $compilerFiles)
    $cachedLinks = @(Get-CachedBinaryFingerprints `
      -Entries $cachedIdentity['native_link_tools'] -ExpectedFiles $linkFiles)
    $fingerprintJson = New-CompilerFingerprintJson $cachedCompilers $cachedLinks
    # Reconstruct from the current image, selected toolchain, workspace and
    # dependencies. Exact strings also reject missing/extra/reordered fields
    # and a compiler identity that disagrees with the full toolchain identity.
    if($fingerprintJson.CompilerJson -cne $memo['compiler_json'] -or
       $fingerprintJson.IdentityJson -cne $memo['identity_json'])
    {
      throw 'Cached identity does not exactly match the current environment'
    }
    $memoHit = $true
  }
  catch
  {
    Write-Host "Compiler fingerprint memo rejected; hashing binaries: $($_.Exception.Message)"
  }
}
if(-not $memoHit)
{
  $fingerprints = foreach($file in $compilerFiles)
  {
    [ordered]@{ path = $file; sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash }
  }
  $linkFingerprints = foreach($file in $linkFiles)
  {
    [ordered]@{ path = $file; sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash }
  }
  $fingerprintJson = New-CompilerFingerprintJson $fingerprints $linkFingerprints
}

# Partition compiler results by binary identity; final packages additionally
# depend on the linker, SDK and installed runner-image runtime closure.
$compilerJson = $fingerprintJson.CompilerJson
$identityJson = $fingerprintJson.IdentityJson
$compilerKey = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
  [Text.Encoding]::UTF8.GetBytes($compilerJson))).ToLowerInvariant()
$key = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
  [Text.Encoding]::UTF8.GetBytes($identityJson))).ToLowerInvariant()

if($memoKey -and -not [string]::IsNullOrWhiteSpace($FingerprintCachePath))
{
  $temporaryMemo = $null
  try
  {
    $memoPath = [IO.Path]::GetFullPath($FingerprintCachePath)
    New-Item -ItemType Directory -Path (Split-Path -Parent $memoPath) -Force | Out-Null
    $temporaryMemo = "$memoPath.$([guid]::NewGuid().ToString('N')).tmp"
    $memoJson = [ordered]@{
      schema = 1
      fingerprint_cache_key = $memoKey
      compiler_json = $compilerJson
      identity_json = $identityJson
    } | ConvertTo-Json -Depth 3 -Compress
    [IO.File]::WriteAllText($temporaryMemo, $memoJson, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryMemo -Destination $memoPath -Force
  }
  catch
  {
    # The memo is optional; a save failure must not prevent a valid build.
    Write-Host "Compiler fingerprint memo could not be saved: $($_.Exception.Message)"
  }
  finally
  {
    if($temporaryMemo -and (Test-Path -LiteralPath $temporaryMemo))
    {
      Remove-Item -LiteralPath $temporaryMemo -Force -ErrorAction SilentlyContinue
    }
  }
}

if($env:GITHUB_PATH -and -not $FingerprintOnly)
{
  $llvmDirectory | Add-Content -LiteralPath $env:GITHUB_PATH -Encoding utf8
  $msvcDirectory | Add-Content -LiteralPath $env:GITHUB_PATH -Encoding utf8
}
if($env:GITHUB_ENV -and -not $FingerprintOnly)
{
  @(
    'RDocUseCompilerCache=true',
    "RDocSccacheCompilerDir=$OutputDirectory",
    "CL_MPCOUNT=$env:CL_MPCOUNT"
  ) | Add-Content -LiteralPath $env:GITHUB_ENV -Encoding utf8
}
if($env:GITHUB_OUTPUT)
{
  @(
    "toolchain-key=$key",
    "compiler-key=$compilerKey",
    "parallel-jobs=$parallelJobs",
    "fingerprint-cache-key=$memoKey",
    "fingerprint-cache-hit=$($memoHit.ToString().ToLowerInvariant())"
  ) | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8
}
$identityJson | Set-Content -LiteralPath (Join-Path $OutputDirectory 'toolchain.json') -Encoding utf8
Write-Host "Compiler environment: $parallelJobs available CPUs, MSVC $($selected.VCToolsVersion), SDK $($selected.WindowsSDKVersion)"
Write-Host "Real compilers: $msvcDirectory; $llvmDirectory"
Write-Host "Compiler archive identity: $key"
Write-Host "Compiler fingerprint memo reused: $memoHit"
