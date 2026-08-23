[CmdletBinding()]
param(
  [ValidateSet('Development', 'Release')]
  [string]$Configuration = 'Release',

  [ValidateSet('Win32', 'x64')]
  [string]$Platform = 'x64',

  [switch]$EnableLTCG
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$solutionPath = Join-Path $repositoryRoot 'renderdoc.sln'
$identityGenerator = Join-Path $PSScriptRoot 'generate_product_identity.py'
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'

if(-not (Test-Path -LiteralPath $solutionPath -PathType Leaf))
{
  throw "Solution not found: $solutionPath"
}

if(-not (Test-Path -LiteralPath $vswherePath -PathType Leaf))
{
  throw "Visual Studio locator not found: $vswherePath"
}

$visualStudioPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
  -property installationPath
$msbuildPath = Join-Path $visualStudioPath 'MSBuild\Current\Bin\amd64\MSBuild.exe'
if(-not (Test-Path -LiteralPath $msbuildPath -PathType Leaf))
{
  $msbuildPath = & $vswherePath -latest -products * -requires Microsoft.Component.MSBuild `
    -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
}
if(-not $msbuildPath)
{
  throw 'MSBuild.exe was not found in an installed Visual Studio instance'
}

& python $identityGenerator --check
if($LASTEXITCODE -ne 0)
{
  throw 'Generated product identity files are stale'
}

$errors = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
$identityContractsPath = Join-Path $PSScriptRoot 'check_windows_identity_contracts.ps1'
if(-not (Test-Path -LiteralPath $identityContractsPath -PathType Leaf))
{
  $errors.Add('Windows identity validation script is missing: ' +
              'util\buildscripts\check_windows_identity_contracts.ps1')
}
else
{
  try
  {
    & $identityContractsPath
  }
  catch
  {
    $errors.Add($_.Exception.Message)
  }
}
$embeddedDxilCheckPath = Join-Path $PSScriptRoot 'check_windows_embedded_dxil.ps1'
if(-not (Test-Path -LiteralPath $embeddedDxilCheckPath -PathType Leaf))
{
  $errors.Add('Embedded DXIL validation script is missing: ' +
              'util\buildscripts\check_windows_embedded_dxil.ps1')
}
$standaloneMissingSources = @{}
$requiredBootstrapProjects = @(
  'bootstrap\dxgi_proxy\dxgi_proxy.vcxproj',
  'bootstrap\d3d11_proxy\d3d11_proxy.vcxproj',
  'bootstrap\d3d12_proxy\d3d12_proxy.vcxproj'
)
foreach($relativeBootstrapProject in $requiredBootstrapProjects)
{
  if(-not (Test-Path -LiteralPath `
      (Join-Path $repositoryRoot $relativeBootstrapProject) -PathType Leaf))
  {
    $errors.Add("Required bootstrap project is missing: $relativeBootstrapProject")
  }
}
$productIdentityPropsPath = Join-Path $repositoryRoot 'build\product_identity.props'
$coreBaseName = $null
$vulkanJsonBaseName = $null
try
{
  [xml]$productIdentityProps = Get-Content -LiteralPath $productIdentityPropsPath -Raw
  $coreBaseName =
      $productIdentityProps.SelectSingleNode(
        '//*[local-name()="RDocCoreBaseName"]').InnerText
  $vulkanJsonBaseName =
      $productIdentityProps.SelectSingleNode(
        '//*[local-name()="RDocVulkanJsonBaseName"]').InnerText
  if([string]::IsNullOrWhiteSpace($coreBaseName))
  {
    throw 'RDocCoreBaseName is empty'
  }
  if([string]::IsNullOrWhiteSpace($vulkanJsonBaseName))
  {
    throw 'RDocVulkanJsonBaseName is empty'
  }
}
catch
{
  $errors.Add("Could not read product identity from build\product_identity.props: " +
              $_.Exception.Message)
}
$solutionLines = Get-Content -LiteralPath $solutionPath
$solutionProjectPaths = @(
  foreach($line in $solutionLines)
  {
    if($line -match '^Project\("\{[^}]+\}"\) = "[^"]+", "([^"]+\.vcxproj)"')
    {
      $matches[1]
    }
  }
) | Where-Object {
  $_ -notmatch '^qrenderdoc\\' -and $_ -notmatch '^util\\test\\demos\\'
}

$projectPaths = @(& git -C $repositoryRoot ls-files --cached --others --exclude-standard `
  -- '*.vcxproj')
if($LASTEXITCODE -ne 0)
{
  throw 'Could not enumerate Visual C++ projects'
}

$projectPaths = @(
  $projectPaths |
    ForEach-Object { $_ -replace '/', '\' }
  $solutionProjectPaths
) | Sort-Object -Unique

$projectRecords = foreach($relativeProjectPath in $projectPaths)
{
  $isSolutionProject = $solutionProjectPaths -contains $relativeProjectPath
  $projectPath = Join-Path $repositoryRoot `
    ($relativeProjectPath -replace '\\', [IO.Path]::DirectorySeparatorChar)

  if(-not (Test-Path -LiteralPath $projectPath -PathType Leaf))
  {
    $errors.Add("Solution project is missing: $relativeProjectPath")
    continue
  }

  try
  {
    $projectText = Get-Content -LiteralPath $projectPath -Raw
    [xml]$projectXml = $projectText
  }
  catch
  {
    $errors.Add("Invalid project XML: $relativeProjectPath - $($_.Exception.Message)")
    continue
  }

  if($projectText -match '3rdparty[\\/]+minhook')
  {
    $errors.Add("$relativeProjectPath still references removed MinHook sources")
  }

  $isBootstrapProject =
      $relativeProjectPath -match '^bootstrap\\(?:d3d11_proxy|dxgi_proxy|d3d12_proxy)\\'
  if($isBootstrapProject -and $isSolutionProject)
  {
    $errors.Add("Bootstrap project must remain outside renderdoc.sln: $relativeProjectPath")
  }
  if($isBootstrapProject -and
     ($projectText -notmatch `
        '<RuntimeLibrary\s+Condition="''\$\(Configuration\)''==''Release''">MultiThreaded</RuntimeLibrary>' -or
      $projectText -notmatch `
        '<RuntimeLibrary\s+Condition="''\$\(Configuration\)''==''Development''">MultiThreadedDebug</RuntimeLibrary>'))
  {
    $errors.Add("Bootstrap project does not enforce the static MSVC runtime: $relativeProjectPath")
  }

  $namespace = [Xml.XmlNamespaceManager]::new($projectXml.NameTable)
  $namespace.AddNamespace('m', 'http://schemas.microsoft.com/developer/msbuild/2003')

  foreach($reference in $projectXml.SelectNodes('//m:ProjectReference[@Include]', $namespace))
  {
    if($reference.Include -notmatch '\$\(')
    {
      $resolved = [IO.Path]::GetFullPath(
        (Join-Path (Split-Path -Parent $projectPath) $reference.Include))
      if(-not (Test-Path -LiteralPath $resolved -PathType Leaf))
      {
        $message = "$relativeProjectPath references missing project $($reference.Include)"
        if($isSolutionProject) { $errors.Add($message) } else { $warnings.Add($message) }
      }
    }
  }

  foreach($source in $projectXml.SelectNodes('//m:ClCompile[@Include]', $namespace))
  {
    if($source.Include -notmatch '\$\(')
    {
      $resolved = [IO.Path]::GetFullPath(
        (Join-Path (Split-Path -Parent $projectPath) $source.Include))
      if(-not (Test-Path -LiteralPath $resolved -PathType Leaf))
      {
        $message = "$relativeProjectPath compiles missing source $($source.Include)"
        if($isSolutionProject -or $isBootstrapProject)
        {
          $errors.Add($message)
        }
        else
        {
          if(-not $standaloneMissingSources.ContainsKey($relativeProjectPath))
          {
            $standaloneMissingSources[$relativeProjectPath] = 0
          }
          $standaloneMissingSources[$relativeProjectPath]++
        }
      }
    }
  }

  if($relativeProjectPath -match '^bootstrap\\[^\\]+_proxy\\')
  {
    $proxySourceText = ($projectXml.SelectNodes('//m:ClCompile[@Include]', $namespace) |
      ForEach-Object {
        if($_.Include -notmatch '\$\(')
        {
          $resolved = [IO.Path]::GetFullPath(
            (Join-Path (Split-Path -Parent $projectPath) $_.Include))
          if(Test-Path -LiteralPath $resolved -PathType Leaf)
          {
            Get-Content -LiteralPath $resolved -Raw
          }
        }
      }) -join "`n"

    $requiredResolvers = [System.Collections.Generic.HashSet[string]]::new(
      [StringComparer]::Ordinal)
    foreach($assembler in $projectXml.SelectNodes('//m:MASM[@Include]', $namespace))
    {
      if($assembler.Include -match '\$\(')
      {
        continue
      }

      $assemblerPath = [IO.Path]::GetFullPath(
        (Join-Path (Split-Path -Parent $projectPath) $assembler.Include))
      if(-not (Test-Path -LiteralPath $assemblerPath -PathType Leaf))
      {
        $errors.Add("$relativeProjectPath assembles missing source $($assembler.Include)")
        continue
      }

      $assemblerText = Get-Content -LiteralPath $assemblerPath -Raw
      foreach($match in [regex]::Matches(
        $assemblerText, '(?im)^\s*extern\s+([A-Za-z_][A-Za-z0-9_]*)\s*:proc'))
      {
        [void]$requiredResolvers.Add($match.Groups[1].Value.TrimStart('_'))
      }
    }

    foreach($resolver in $requiredResolvers)
    {
      $resolverPattern =
        '(?s)extern\s+"C"[^;{}]*\b' + [regex]::Escape($resolver) +
        '\s*\([^;{}]*\)\s*\{'
      if($proxySourceText -notmatch $resolverPattern)
      {
        $message =
          "$relativeProjectPath assembler expects $resolver but its C/C++ source has no implementation"
        if($isSolutionProject -or $isBootstrapProject)
        {
          $errors.Add($message)
        }
        else
        {
          $warnings.Add($message)
        }
      }
    }
  }

  $ltcgValue = $EnableLTCG.IsPresent.ToString().ToLowerInvariant()
  $queryOutput = & $msbuildPath $projectPath -nologo `
    "-p:Configuration=$Configuration" `
    "-p:Platform=$Platform" `
    "-p:SolutionDir=$repositoryRoot\" `
    "-p:RDocEnableLTCG=$ltcgValue" `
    '-getProperty:ProjectGuid;PlatformToolset;WholeProgramOptimization;LinkTimeCodeGeneration;TargetFileName;OutDir;IntDir' `
    2>&1
  if($LASTEXITCODE -ne 0)
  {
    $errors.Add("MSBuild property evaluation failed: $relativeProjectPath")
    continue
  }

  try
  {
    $properties = (($queryOutput -join "`n") | ConvertFrom-Json).Properties
  }
  catch
  {
    $errors.Add("Could not parse MSBuild properties: $relativeProjectPath")
    continue
  }

  if($Configuration -eq 'Release' -and -not $EnableLTCG -and
     $properties.WholeProgramOptimization -eq 'true')
  {
    $errors.Add("Fast Release still enables WPO: $relativeProjectPath")
  }
  if($Configuration -eq 'Release' -and -not $EnableLTCG -and
     $properties.LinkTimeCodeGeneration -eq 'UseLinkTimeCodeGeneration')
  {
    $errors.Add("Fast Release still enables LTCG: $relativeProjectPath")
  }
  if($properties.PlatformToolset -match '^v14[0-2]$')
  {
    $errors.Add("Legacy Visual Studio toolset remains in ${relativeProjectPath}: " +
                $properties.PlatformToolset)
  }

  [pscustomobject]@{
    Project = $relativeProjectPath
    Guid = $properties.ProjectGuid
    WPO = $properties.WholeProgramOptimization
    LTCG = $properties.LinkTimeCodeGeneration
    Output = Join-Path $properties.OutDir $properties.TargetFileName
    IntDir = $properties.IntDir
  }
}

foreach($entry in $standaloneMissingSources.GetEnumerator() | Sort-Object Key)
{
  $warnings.Add(
    "$($entry.Key) has $($entry.Value) missing source files in an optional external dependency")
}

foreach($duplicate in $projectRecords | Group-Object Guid | Where-Object Count -gt 1)
{
  $errors.Add("Duplicate project GUID $($duplicate.Name): " +
    (($duplicate.Group.Project) -join ', '))
}

foreach($duplicate in $projectRecords | Group-Object Output | Where-Object Count -gt 1)
{
  $errors.Add("Duplicate output $($duplicate.Name): " +
    (($duplicate.Group.Project) -join ', '))
}

foreach($duplicate in $projectRecords | Group-Object IntDir | Where-Object Count -gt 1)
{
  $errors.Add("Shared intermediate directory $($duplicate.Name): " +
    (($duplicate.Group.Project) -join ', '))
}

$appHeader = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot 'renderdoc\api\app\renderdoc_app.h') -Raw
$appImplementation = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot 'renderdoc\replay\app_api.cpp') -Raw

foreach($contract in @('pRENDERDOC_GetAPI', 'pDCOMP_GetAPI'))
{
  if(-not $appHeader.Contains($contract))
  {
    $errors.Add("Application API header is missing $contract")
  }
}

if(-not $appImplementation.Contains('DCOMP_GetAPI'))
{
  $errors.Add('Application API implementation is missing DCOMP_GetAPI')
}
if($appImplementation -match '\bRENDERDOC_GetAPI\s*\(')
{
  $errors.Add('Application API implementation still contains the legacy RENDERDOC_GetAPI wrapper')
}

foreach($relativeVersionScript in @("renderdoc\$coreBaseName.version", 'renderdoc\rdocself.version'))
{
  $versionScriptPath = Join-Path $repositoryRoot $relativeVersionScript
  if(-not (Test-Path -LiteralPath $versionScriptPath -PathType Leaf))
  {
    $errors.Add("Version script is missing: $relativeVersionScript")
    continue
  }

  $versionScript = Get-Content -LiteralPath $versionScriptPath -Raw
  if($versionScript.Contains('RENDERDOC_GetAPI'))
  {
    $errors.Add("Version script still exports RENDERDOC_GetAPI: $relativeVersionScript")
  }
  if($versionScript -notmatch 'DCOMP_(?:GetAPI|\*)')
  {
    $errors.Add("Version script does not export DCOMP_GetAPI: $relativeVersionScript")
  }
}

$vulkanDirectory = Join-Path $repositoryRoot 'renderdoc\driver\vulkan'
$vulkanDescriptorFileName = "$vulkanJsonBaseName.json"
$vulkanDescriptorPath = Join-Path $vulkanDirectory $vulkanDescriptorFileName
$legacyVulkanDescriptorPath = Join-Path $vulkanDirectory 'renderdoc.json'
if(-not (Test-Path -LiteralPath $vulkanDescriptorPath -PathType Leaf))
{
  $errors.Add("Vulkan layer descriptor is missing: " +
              "renderdoc\driver\vulkan\$vulkanDescriptorFileName")
}
else
{
  try
  {
    $vulkanDescriptor = Get-Content -LiteralPath $vulkanDescriptorPath -Raw |
      ConvertFrom-Json
    if($vulkanDescriptor.layer.name -ne '@VULKAN_LAYER_NAME@')
    {
      $errors.Add("$vulkanDescriptorFileName has an unexpected layer name template")
    }
  }
  catch
  {
    $errors.Add("Invalid $vulkanDescriptorFileName JSON: $($_.Exception.Message)")
  }
}
if(Test-Path -LiteralPath $legacyVulkanDescriptorPath)
{
  $errors.Add('Legacy Vulkan layer descriptor still exists: renderdoc\driver\vulkan\renderdoc.json')
}

$mainProject = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot 'renderdoc\renderdoc.vcxproj') -Raw
if(-not $mainProject.Contains('$(RDocVulkanJsonBaseName).json'))
{
  $errors.Add('renderdoc.vcxproj does not use the central Vulkan JSON basename')
}
if(-not $mainProject.Contains('RENDERDOC_BAKED_DXC_SHADERS=1') -or
   $mainProject.Contains('DCOMP_BAKED_DXC_SHADERS'))
{
  $errors.Add('renderdoc.vcxproj does not use the upstream baked-DXIL build macro')
}

$resourceScript = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot 'renderdoc\data\renderdoc.rc') -Raw
if($resourceScript -notmatch `
    '(?m)^\s*#\s*(?:ifdef\s+|if\s+defined\s*\(?\s*)RENDERDOC_BAKED_DXC_SHADERS\b' -or
   $resourceScript.Contains('DCOMP_BAKED_DXC_SHADERS'))
{
  $errors.Add('renderdoc.rc and renderdoc.vcxproj do not share the upstream ' +
              'baked-DXIL build macro')
}

$coreCMake = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot 'renderdoc\CMakeLists.txt') -Raw
if(-not $coreCMake.Contains('-DDCOMP_EXPORTS'))
{
  $errors.Add('renderdoc/CMakeLists.txt does not define DCOMP_EXPORTS')
}

$directoryBuildTargets = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot 'Directory.Build.targets') -Raw
foreach($requiredStaticRuntimeContract in @('DCompStaticRuntime', 'DCompCoreRuntimeProject',
                                             '<RuntimeLibrary>MultiThreaded</RuntimeLibrary>'))
{
  if(-not $directoryBuildTargets.Contains($requiredStaticRuntimeContract))
  {
    $errors.Add("Directory.Build.targets is missing injected static-CRT contract: " +
                $requiredStaticRuntimeContract)
  }
}

[xml]$directoryBuildTargetsXml = $directoryBuildTargets
$releaseCondition = "'`$(Configuration)'=='Release'"
$releaseDefaultGroups = @($directoryBuildTargetsXml.Project.PropertyGroup |
  Where-Object { $_.GetAttribute('Condition') -eq $releaseCondition })
if($releaseDefaultGroups.Count -ne 1)
{
  $errors.Add('Directory.Build.targets must define exactly one Release default contract group')
}
else
{
  $expectedReleaseDefaults = [ordered]@{
    DCompHookIntoChildrenDefault = '1'
    DCompStaticRuntime = '1'
    DCompInlineGraphicsHooks = '1'
    DCompSingleGenerationChildHook = '0'
  }
  foreach($releaseDefaultEntry in $expectedReleaseDefaults.GetEnumerator())
  {
    $releaseDefaultName = $releaseDefaultEntry.Key
    $expectedValue = $releaseDefaultEntry.Value
    $releaseDefault = $releaseDefaultGroups[0].SelectSingleNode(
      "*[local-name()='$releaseDefaultName']")
    $propertyReference = '$(' + $releaseDefaultName + ')'
    if($null -eq $releaseDefault -or $releaseDefault.InnerText -ne $expectedValue -or
       -not $releaseDefault.GetAttribute('Condition').Contains($propertyReference))
    {
      $errors.Add("Release default contract is missing or not overrideable: " +
                  "$releaseDefaultName=$expectedValue")
    }
  }
}

$qtUiProject = 'qrenderdoc\qrenderdoc_local.vcxproj'
$qtUiProjectText = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot $qtUiProject) -Raw
if(-not $qtUiProjectText.Contains(
    '<RuntimeLibrary>MultiThreadedDLL</RuntimeLibrary>'))
{
  $errors.Add("$qtUiProject no longer preserves the Qt/Python-compatible /MD ABI")
}
foreach($requiredTranslationFallback in @(
    'if exist "$(QtBinDir)\lrelease.exe"',
    'if not exist "Translations\qrenderdoc_zh_CN.qm"',
    'Missing tracked translation catalog'))
{
  if(-not $qtUiProjectText.Contains($requiredTranslationFallback))
  {
    $errors.Add("$qtUiProject is missing clean-build translation fallback: " +
                $requiredTranslationFallback)
  }
}
if($qtUiProjectText.Contains(
    'Translations\qrenderdoc_zh_CN.qm;$(QtBinDir)\lrelease.exe;'))
{
  $errors.Add("$qtUiProject still requires lrelease.exe as a custom-build input")
}
$trackedTranslationCatalog = Join-Path $repositoryRoot `
  'qrenderdoc\Translations\qrenderdoc_zh_CN.qm'
if(-not (Test-Path -LiteralPath $trackedTranslationCatalog -PathType Leaf))
{
  $errors.Add('Tracked Chinese translation catalog is missing: ' +
              'qrenderdoc\Translations\qrenderdoc_zh_CN.qm')
}

$legacyMacroMatches = @(& git -C $repositoryRoot grep --text -n -E `
  'RENDERDOC_(EXPORTS|PLATFORM_WIN32)' -- renderdoc qrenderdoc `
  ':(exclude)renderdoc/3rdparty/**' ':(exclude)qrenderdoc/3rdparty/**' 2>$null)
$legacyMacroExitCode = $LASTEXITCODE
if($legacyMacroExitCode -eq 0)
{
  foreach($legacyMacroMatch in $legacyMacroMatches)
  {
    $errors.Add("Legacy runtime build macro remains: $legacyMacroMatch")
  }
}
elseif($legacyMacroExitCode -ne 1)
{
  throw "git grep failed while checking legacy build macros with exit code $legacyMacroExitCode"
}
else
{
  # A no-match result is success for this check. Reset the native exit code so callers that invoke
  # this script in-process do not mistake git grep's expected exit code 1 for a contract failure.
  & git -C $repositoryRoot rev-parse --is-inside-work-tree | Out-Null
  if($LASTEXITCODE -ne 0)
  {
    throw 'Could not restore the successful Git contract-check state'
  }
}

$vulkanProjectPath = 'renderdoc\driver\vulkan\renderdoc_vulkan.vcxproj'
$vulkanProjectText = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot $vulkanProjectPath) -Raw
if(-not $vulkanProjectText.Contains('$(RDocVulkanJsonBaseName).json') -or
   $vulkanProjectText.Contains('renderdoc.json'))
{
  $errors.Add("$vulkanProjectPath does not use the central Vulkan JSON basename")
}

$vulkanFiltersPath = 'renderdoc\driver\vulkan\renderdoc_vulkan.vcxproj.filters'
$vulkanFiltersText = Get-Content -LiteralPath `
  (Join-Path $repositoryRoot $vulkanFiltersPath) -Raw
if(-not $vulkanFiltersText.Contains($vulkanDescriptorFileName) -or
   $vulkanFiltersText.Contains('renderdoc.json') -or
   ($vulkanJsonBaseName -ne 'dgcore' -and $vulkanFiltersText.Contains('dgcore.json')))
{
  $errors.Add("$vulkanFiltersPath does not reference only $vulkanDescriptorFileName")
}

if($errors.Count -gt 0)
{
  $warnings | ForEach-Object { Write-Warning $_ }
  $errors | ForEach-Object { Write-Error $_ }
  exit 1
}

$warnings | ForEach-Object { Write-Warning $_ }
$wpoCount = @($projectRecords | Where-Object WPO -eq 'true').Count
$profile = if($EnableLTCG) { 'enabled' } else { 'fast' }
$summary = ("Build contracts passed: {0} solution projects, {1} projects inspected, " +
  "Configuration={2}, Platform={3}, WPO projects={4}, LTCG profile={5}") -f `
  $solutionProjectPaths.Count, $projectRecords.Count, $Configuration, $Platform, $wpoCount, $profile
Write-Host $summary
