[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$OutputDirectory,
  [switch]$FingerprintOnly
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

# Partition the archive by the actual compiler implementation and SDK. The
# inner sccache keys still validate source, headers, flags and compiler inputs.
$compilerFiles = @(
  (Join-Path $msvcDirectory 'cl.exe'),
  (Join-Path $msvcDirectory 'c1.dll'),
  (Join-Path $msvcDirectory 'c1xx.dll'),
  (Join-Path $msvcDirectory 'c2.dll'),
  (Join-Path $llvmDirectory 'clang-cl.exe'),
  (Join-Path $llvmDirectory 'lld-link.exe'),
  $selected.MSBuildPath
)
$fingerprints = foreach($file in $compilerFiles)
{
  if(-not (Test-Path -LiteralPath $file -PathType Leaf))
  {
    throw "Compiler cache identity input is missing: $file"
  }
  [ordered]@{
    path = $file
    sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
  }
}
$compilerIdentity = [ordered]@{
  schema = 1
  platform = 'x64'
  toolchain = $selected
  compilers = @($fingerprints)
  dependency_sha256 = $env:QRENDERDOC_THIRDPARTY_SHA256
  workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
}
$compilerJson = $compilerIdentity | ConvertTo-Json -Depth 5 -Compress
$compilerKey = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
  [Text.Encoding]::UTF8.GetBytes($compilerJson))).ToLowerInvariant()
# Final packages also depend on the linker, SDK and installed runtime closure.
# A runner-image update invalidates that level, while per-TU results remain
# available for sccache to validate against the current headers and flags.
$identity = [ordered]@{
  compiler = $compilerIdentity
  image_os = $env:ImageOS
  image_version = $env:ImageVersion
  native_link_tools = @('link.exe', 'lib.exe') | ForEach-Object {
    $file = Join-Path $msvcDirectory $_
    [ordered]@{
      path = $file
      sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    }
  }
}
$identityJson = $identity | ConvertTo-Json -Depth 7 -Compress
$key = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
  [Text.Encoding]::UTF8.GetBytes($identityJson))).ToLowerInvariant()

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
    "parallel-jobs=$parallelJobs"
  ) | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8
}
$identityJson | Set-Content -LiteralPath (Join-Path $OutputDirectory 'toolchain.json') -Encoding utf8
Write-Host "Compiler environment: $parallelJobs available CPUs, MSVC $($selected.VCToolsVersion), SDK $($selected.WindowsSDKVersion)"
Write-Host "Real compilers: $msvcDirectory; $llvmDirectory"
Write-Host "Compiler archive identity: $key"
