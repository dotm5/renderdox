[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$DemoBinary,

  [Parameter(Mandatory = $true)]
  [string]$OutputRoot,

  [string]$RenderDocCmd = '',

  [string]$VulkanSdk = '',

  [switch]$ReuseFunctionalOutput,

  [string[]]$Cases = @(
    'D3D11_Simple_Triangle',
    'D3D11_Draw_Zoo',
    'D3D11_Action_Visibility_Dispatch',
    'D3D11_Stream_Out',
    'D3D12_Simple_Triangle',
    'D3D12_Draw_Zoo',
    'D3D12_Compute_Only',
    'D3D12_Execute_Indirect',
    'D3D12_Vertex_UAV',
    'VK_Simple_Triangle',
    'VK_Draw_Zoo',
    'VK_Groupshared',
    'VK_Indirect'
  )
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$identity = Get-Content -LiteralPath (Join-Path $repositoryRoot 'build\product_identity.json') `
  -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $RenderDocCmd) {
  $RenderDocCmd = Join-Path $repositoryRoot `
    "x64\Development\$($identity.commandBaseName).exe"
}

$RenderDocCmd = (Resolve-Path -LiteralPath $RenderDocCmd).Path
$DemoBinary = (Resolve-Path -LiteralPath $DemoBinary).Path
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

function Invoke-LoggedProcess {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$StdoutPath,
    [Parameter(Mandatory = $true)][string]$StderrPath,
    [hashtable]$Environment = @{}
  )

  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $FilePath
  $startInfo.WorkingDirectory = $WorkingDirectory
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true

  foreach ($argument in $ArgumentList) {
    [void]$startInfo.ArgumentList.Add($argument)
  }
  foreach ($entry in $Environment.GetEnumerator()) {
    $startInfo.Environment[$entry.Key] = [string]$entry.Value
  }

  $process = [Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  $timer = [Diagnostics.Stopwatch]::StartNew()
  if (-not $process.Start()) {
    throw "Failed to start $FilePath"
  }

  $stdoutTask = $process.StandardOutput.ReadToEndAsync()
  $stderrTask = $process.StandardError.ReadToEndAsync()
  $process.WaitForExit()
  $timer.Stop()

  [IO.File]::WriteAllText(
    $StdoutPath,
    $stdoutTask.GetAwaiter().GetResult(),
    [Text.UTF8Encoding]::new($false)
  )
  [IO.File]::WriteAllText(
    $StderrPath,
    $stderrTask.GetAwaiter().GetResult(),
    [Text.UTF8Encoding]::new($false)
  )

  return [pscustomobject]@{
    ExitCode = $process.ExitCode
    ElapsedSeconds = [math]::Round($timer.Elapsed.TotalSeconds, 3)
  }
}

$results = [Collections.Generic.List[object]]::new()
$renderdocLayerPath = Split-Path -Parent $RenderDocCmd

$environment = @{
  VK_IMPLICIT_LAYER_PATH = $renderdocLayerPath
  VK_LAYER_PATH = $renderdocLayerPath
}
$environment[[string]$identity.vulkanEnableVar] = '1'
if ($Cases | Where-Object { $_.StartsWith('VK_') }) {
  if (-not $VulkanSdk) {
    throw 'VulkanSdk is required when Vulkan cases are selected'
  }
  $vulkanBin = Join-Path $VulkanSdk 'Bin'
  if (-not (Test-Path -LiteralPath (Join-Path $vulkanBin 'glslc.exe'))) {
    throw "glslc.exe is missing from VulkanSdk: $VulkanSdk"
  }
  $environment['VULKAN_SDK'] = $VulkanSdk
  $environment['PATH'] = "$vulkanBin;$env:PATH"
}

$escapedCases = @($Cases | ForEach-Object { [Regex]::Escape($_) })
$testPattern = '^(' + ($escapedCases -join '|') + ')$'
$functionalTemp = Join-Path $OutputRoot 'functional-temp'
$functionalArtifacts = Join-Path $OutputRoot 'functional-artifacts'
if ($ReuseFunctionalOutput) {
  if (-not (Test-Path -LiteralPath $functionalTemp)) {
    throw "Cannot reuse missing functional output: $functionalTemp"
  }
  $functionalResult = [pscustomobject]@{
    ExitCode = -1
    ElapsedSeconds = 0
  }
} else {
  $functionalResult = Invoke-LoggedProcess `
    -FilePath $RenderDocCmd `
    -ArgumentList @(
      'test',
      'functional',
      '-t',
      $testPattern,
      '--in-process',
      '--test-timeout',
      '180',
      '--demos-timeout',
      '120',
      '--demos-binary',
      $DemoBinary,
      '--artifacts',
      $functionalArtifacts,
      '--temp',
      $functionalTemp,
      '--data',
      (Join-Path $repositoryRoot 'util\test\data'),
      '--data-extra',
      (Join-Path $repositoryRoot 'util\test\data_extra')
    ) `
    -WorkingDirectory $repositoryRoot `
    -StdoutPath (Join-Path $OutputRoot 'functional.stdout.txt') `
    -StderrPath (Join-Path $OutputRoot 'functional.stderr.txt') `
    -Environment $environment
}

foreach ($caseName in $Cases) {
  $api = if ($caseName.StartsWith('D3D11_')) {
    'd3d11'
  } elseif ($caseName.StartsWith('D3D12_')) {
    'd3d12'
  } elseif ($caseName.StartsWith('VK_')) {
    'vulkan'
  } else {
    throw "Unsupported owned test case prefix: $caseName"
  }

  $sourceDirectory = Join-Path $functionalTemp $caseName
  $captures = @(
    Get-ChildItem -LiteralPath $sourceDirectory -Filter 'capture*.rdc' |
      Sort-Object LastWriteTimeUtc, Name
  )
  if ($captures.Count -eq 0) {
    throw "$caseName did not leave a functional-test capture in $sourceDirectory"
  }

  $caseDirectory = Join-Path $OutputRoot $caseName
  New-Item -ItemType Directory -Force -Path $caseDirectory | Out-Null
  $capturePath = Join-Path $caseDirectory "$caseName.rdc"
  Copy-Item -LiteralPath $captures[-1].FullName -Destination $capturePath -Force
  $capture = Get-Item -LiteralPath $capturePath
  $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $capture.FullName
  $results.Add([ordered]@{
    case = $caseName
    api = $api
    capturePath = $capture.FullName
    captureSHA256 = $hash.Hash
    captureBytes = $capture.Length
    captureCount = $captures.Count
    functionalExitCode = $functionalResult.ExitCode
    functionalStatus = if ($functionalResult.ExitCode -eq 0) {
      'passed'
    } elseif ($ReuseFunctionalOutput) {
      'reused-see-log'
    } else {
      'see-log'
    }
    functionalRunSeconds = $functionalResult.ElapsedSeconds
  })
}

$manifest = [ordered]@{
  schemaVersion = 1
  kind = 'action-visibility-owned-captures'
  generatedAt = (Get-Date).ToUniversalTime().ToString('o')
  renderDocCmd = $RenderDocCmd
  demoBinary = $DemoBinary
  results = $results
}

$manifestPath = Join-Path $OutputRoot 'capture-manifest.json'
$manifest | ConvertTo-Json -Depth 8 |
  Set-Content -LiteralPath $manifestPath -Encoding utf8
$manifest | ConvertTo-Json -Depth 8
