[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$errors = [System.Collections.Generic.List[string]]::new()

function Read-RepositoryText
{
  param([Parameter(Mandatory)][string]$RelativePath)

  $path = Join-Path $repositoryRoot $RelativePath
  if(-not (Test-Path -LiteralPath $path -PathType Leaf))
  {
    $errors.Add("Required identity file is missing: $RelativePath")
    return ''
  }

  return Get-Content -LiteralPath $path -Raw
}

function Require-Text
{
  param(
    [Parameter(Mandatory)][string]$RelativePath,
    [Parameter(Mandatory)][string]$Text,
    [Parameter(Mandatory)][string]$Required
  )

  if(-not $Text.Contains($Required))
  {
    $errors.Add("$RelativePath is missing required identity contract: $Required")
  }
}

function Forbid-Text
{
  param(
    [Parameter(Mandatory)][string]$RelativePath,
    [Parameter(Mandatory)][string]$Text,
    [Parameter(Mandatory)][string]$Forbidden
  )

  if($Text.Contains($Forbidden))
  {
    $errors.Add("$RelativePath retains forbidden legacy identity: $Forbidden")
  }
}

$manifestPath = Join-Path $repositoryRoot 'build\product_identity.json'
try
{
  $identity = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
}
catch
{
  throw "Could not read build\product_identity.json: $($_.Exception.Message)"
}

$captureProgId = "$($identity.configNamespace).RDCCapture.1"
$settingsProgId = "$($identity.configNamespace).RDCSettings.1"
$hookData32 = "$($identity.configNamespace)GlobalHookData32"
$hookData64 = "$($identity.configNamespace)GlobalHookData64"
$crashReadyEvent = "$($identity.configNamespace)CrashHandlerReady"
$vulkanDisableVar = 'DISABLE_' + $identity.vulkanEnableVar.Substring('ENABLE_'.Length)
$replayMarker = "$($identity.coreBaseName)__replay__marker"

$wixIncludePath = 'build\product_identity.wxi'
$wixInclude = Read-RepositoryText $wixIncludePath
$wixDefinitions = [ordered]@{
  RDocProductDisplayName = $identity.productDisplayName
  RDocUIDisplayName = $identity.uiDisplayName
  RDocCoreFilename = "$($identity.coreBaseName).dll"
  RDocUIFilename = "$($identity.uiBaseName).exe"
  RDocCommandFilename = "$($identity.commandBaseName).exe"
  RDocUIStubFilename = "$($identity.uiStubBaseName).exe"
  RDocShim32Filename = "$($identity.shimBaseName)32.dll"
  RDocShim64Filename = "$($identity.shimBaseName)64.dll"
  RDocVulkanJsonFilename = "$($identity.coreBaseName).json"
  RDocCaptureProgId = $captureProgId
  RDocSettingsProgId = $settingsProgId
  RDocInstallerUpgradeCode = $identity.installerUpgradeCode
  RDocThumbnailHandlerClsid = $identity.thumbnailHandlerClsid
  RDocFileAssociationRdcComponentGuid = $identity.fileAssociationRdcComponentGuid
  RDocFileAssociationCapComponentGuid = $identity.fileAssociationCapComponentGuid
}
foreach($definition in $wixDefinitions.GetEnumerator())
{
  Require-Text $wixIncludePath $wixInclude `
    "<?define $($definition.Key) = `"$($definition.Value)`" ?>"
}

$runtimeContracts = @(
  @{
    Path = 'renderdoc\os\win32\win32_process.cpp'
    Required = @('RDOC_COMMAND_FILENAME', 'RDOC_SHIM32_FILENAME', 'RDOC_SHIM64_FILENAME',
                 'RDOC_CORE_FILENAME')
    Forbidden = @('renderdoccmd.exe', 'renderdocshim32.dll', 'renderdocshim64.dll')
  },
  @{
    Path = 'renderdoc\os\win32\sys_win32_hooks.cpp'
    Required = @('RDOC_UI_FILENAME', 'RDOC_COMMAND_FILENAME', 'RDOC_UI_STUB_FILENAME')
    Forbidden = @('qrenderdoc.exe"', 'renderdoccmd.exe"', 'renderdocui.exe"')
  },
  @{
    Path = 'renderdoccmd\renderdoccmd_win32.cpp'
    Required = @('RDOC_CORE_FILENAME', 'RDOC_UI_FILENAME_W',
                 'RDOC_CRASH_HANDLER_READY_EVENT_FALLBACK_W')
    Forbidden = @('RENDERDOC_CRASHHANDLE', 'GetModuleHandleA("renderdoc.dll")')
  },
  @{
    Path = 'renderdocshim\renderdocshim.h'
    Required = @('RDOC_GLOBAL_HOOK_DATA32_NAME', 'RDOC_GLOBAL_HOOK_DATA64_NAME',
                 'RDOC_SHIM32_FILENAME', 'RDOC_SHIM64_FILENAME')
    Forbidden = @('RenderDocGlobalHookData32', 'RenderDocGlobalHookData64')
  },
  @{
    Path = 'renderdoc\core\crash_handler.h'
    Required = @('RDOC_LOG_NAMESPACE "\\dumps\\a"',
                 'RDOC_LOG_NAMESPACE "BreakpadServer')
    Forbidden = @('RenderDoc\\dumps', 'RenderDocBreakpadServer')
  },
  @{
    Path = 'renderdoc\os\win32\win32_stringio.cpp'
    Required = @('RDOC_UI_FILENAME', 'RDOC_CAPTURE_PROGID_W')
    Forbidden = @('RenderDoc.RDCCapture.1', 'qrenderdoc.exe')
  },
  @{
    Path = 'renderdoc\driver\gl\wgl_platform.cpp'
    Required = @('RDOC_CORE_BASE_NAME_W L"GLclass"')
    Forbidden = @('renderdocGLclass', 'rendertestGLclass')
  },
  @{
    Path = 'renderdoc\os\win32\win32_shellext.cpp'
    Required = @('../../generated/product_identity.h',
                 'RDOC_THUMBNAIL_HANDLER_CLSID_INITIALIZER')
    Forbidden = @('5D6BF029-A6BA-417A-8523-120492B1DCE3', '0x5d6bf029')
  },
  @{
    Path = 'renderdocshim\renderdocshim.rc'
    Required = @('RDOC_SHIM_FILE_DESCRIPTION', 'RDOC_SHIM32_FILENAME',
                 'RDOC_SHIM64_FILENAME', 'RDOC_PRODUCT_DISPLAY_NAME')
    Forbidden = @()
  }
)

foreach($contract in $runtimeContracts)
{
  $text = Read-RepositoryText $contract.Path
  foreach($required in $contract.Required)
  {
    Require-Text $contract.Path $text $required
  }
  foreach($forbidden in $contract.Forbidden)
  {
    Forbid-Text $contract.Path $text $forbidden
  }
}

$generatedHeaderPath = 'renderdoc\generated\product_identity.h'
$generatedHeader = Read-RepositoryText $generatedHeaderPath
foreach($expected in @($captureProgId, $settingsProgId, $hookData32, $hookData64,
                       $crashReadyEvent, $identity.thumbnailHandlerClsid,
                       $identity.vulkanLayerName, $identity.vulkanEnableVar,
                       $vulkanDisableVar))
{
  Require-Text $generatedHeaderPath $generatedHeader $expected
}
Require-Text $generatedHeaderPath $generatedHeader `
  'RDOC_THUMBNAIL_HANDLER_CLSID_INITIALIZER'
Require-Text $generatedHeaderPath $generatedHeader `
  "#define RDOC_REPLAY_PROGRAM_MARKER $replayMarker"

$replayMarkerProducers = @(
  @{
    Path = 'qrenderdoc\Code\qrenderdoc.cpp'
    IdentityInclude = '../../renderdoc/generated/product_identity.h'
  },
  @{
    Path = 'renderdoccmd\renderdoccmd.cpp'
    IdentityInclude = '../renderdoc/generated/product_identity.h'
  },
  @{
    Path = 'qrenderdoc\Code\pyrenderdoc\pyrenderdoc_stub.cpp'
    IdentityInclude = '../../../renderdoc/generated/product_identity.h'
  }
)
foreach($producer in $replayMarkerProducers)
{
  $producerText = Read-RepositoryText $producer.Path
  Require-Text $producer.Path $producerText $producer.IdentityInclude
  Require-Text $producer.Path $producerText 'REPLAY_PROGRAM_MARKER()'

  $identityIndex = $producerText.IndexOf($producer.IdentityInclude,
                                         [StringComparison]::Ordinal)
  $markerIndex = $producerText.IndexOf('REPLAY_PROGRAM_MARKER()',
                                       [StringComparison]::Ordinal)
  if($identityIndex -lt 0 -or $markerIndex -lt 0 -or $identityIndex -gt $markerIndex)
  {
    $errors.Add("$($producer.Path) must include product identity before exporting the replay marker")
  }
}

foreach($consumerPath in @('renderdoc\os\win32\win32_libentry.cpp',
                           'renderdoc\os\posix\posix_libentry.cpp'))
{
  $consumerText = Read-RepositoryText $consumerPath
  Require-Text $consumerPath $consumerText `
    'STRINGIZE(RDOC_BASE_NAME) "__replay__marker"'
}

$identityPropsPath = 'build\product_identity.props'
$identityProps = Read-RepositoryText $identityPropsPath
Require-Text $identityPropsPath $identityProps `
  "<RDocReplayBaseName>$($identity.coreBaseName)</RDocReplayBaseName>"
$replayCoreProjectPath = 'renderdoc\renderdoc.vcxproj'
$replayCoreProject = Read-RepositoryText $replayCoreProjectPath
Require-Text $replayCoreProjectPath $replayCoreProject `
  'RDOC_BASE_NAME=$(RDocReplayBaseName)'

$vulkanTemplatePath = "renderdoc\driver\vulkan\$($identity.coreBaseName).json"
$vulkanTemplate = Read-RepositoryText $vulkanTemplatePath
foreach($placeholder in @('@VULKAN_LAYER_NAME@', '@VULKAN_ENABLE_VAR@',
                          '@VULKAN_DISABLE_VAR@', '@RENDERDOC_VERSION_MAJOR@',
                          '@RENDERDOC_VERSION_MINOR@'))
{
  Require-Text $vulkanTemplatePath $vulkanTemplate $placeholder
}
Forbid-Text $vulkanTemplatePath $vulkanTemplate 'DISABLE_VULKAN_DCOMP_CAPTURE_@'

$vulkanCMakePath = 'renderdoc\driver\vulkan\CMakeLists.txt'
$vulkanCMake = Read-RepositoryText $vulkanCMakePath
foreach($cmakeIdentityVariable in @('RDOC_PRODUCT_VULKAN_LAYER_NAME',
                                    'RDOC_PRODUCT_VULKAN_ENABLE_VAR',
                                    'RDOC_PRODUCT_VULKAN_DISABLE_VAR',
                                    'RDOC_PRODUCT_CORE_BASE_NAME'))
{
  Require-Text $vulkanCMakePath $vulkanCMake $cmakeIdentityVariable
}

$rootCMakePath = 'CMakeLists.txt'
$rootCMake = Read-RepositoryText $rootCMakePath
Require-Text $rootCMakePath $rootCMake 'build/product_identity.cmake'
Require-Text $rootCMakePath $rootCMake 'RDOC_PRODUCT_CORE_BASE_NAME'

$posixVulkanPath = 'renderdoc\driver\vulkan\vk_posix.cpp'
$posixVulkan = Read-RepositoryText $posixVulkanPath
foreach($runtimeIdentityMacro in @('RENDERDOC_VULKAN_LAYER_NAME',
                                   'RENDERDOC_VULKAN_LAYER_VAR',
                                   'RENDERDOC_VULKAN_LAYER_DISABLE_VAR'))
{
  Require-Text $posixVulkanPath $posixVulkan $runtimeIdentityMacro
}

$coreProjectPath = 'renderdoc\renderdoc.vcxproj'
$coreProject = Read-RepositoryText $coreProjectPath
Require-Text $coreProjectPath $coreProject '<VulkanDisableVar>$(RDocVulkanDisableVar)</VulkanDisableVar>'
Require-Text $coreProjectPath $coreProject ".Replace('@VULKAN_DISABLE_VAR@'"
Require-Text $coreProjectPath $coreProject ".Trim().Split(' ')[2]"

$globalConfigPath = 'renderdoc\common\globalconfig.h'
$globalConfig = Read-RepositoryText $globalConfigPath
foreach($generatedVulkanMapping in @(
    '#define RENDERDOC_VULKAN_LAYER_NAME RDOC_VULKAN_LAYER_NAME',
    '#define RENDERDOC_VULKAN_LAYER_VAR RDOC_VULKAN_ENABLE_VAR',
    '#define RENDERDOC_VULKAN_LAYER_DISABLE_VAR RDOC_VULKAN_DISABLE_VAR'))
{
  Require-Text $globalConfigPath $globalConfig $generatedVulkanMapping
}

$allowedComponentGuids = [System.Collections.Generic.HashSet[string]]::new(
  [StringComparer]::Ordinal)
[void]$allowedComponentGuids.Add('*')
[void]$allowedComponentGuids.Add('$(var.RDocFileAssociationRdcComponentGuid)')
[void]$allowedComponentGuids.Add('$(var.RDocFileAssociationCapComponentGuid)')

foreach($installerPath in @('util\installer\Installer32.wxs',
                            'util\installer\Installer64.wxs'))
{
  $installerText = Read-RepositoryText $installerPath
  foreach($required in @('<?include product_identity.wxi?>',
                         'Name=''$(var.RDocProductDisplayName)''',
                         'UpgradeCode=''$(var.RDocInstallerUpgradeCode)''',
                         'Id="$(var.RDocInstallerUpgradeCode)"',
                         '$(var.RDocCaptureProgId)', '$(var.RDocSettingsProgId)',
                         '$(var.RDocThumbnailHandlerClsid)',
                         '$(var.RDocFileAssociationRdcComponentGuid)',
                         '$(var.RDocFileAssociationCapComponentGuid)'))
  {
    Require-Text $installerPath $installerText $required
  }
  foreach($forbidden in @('RenderDoc.RDCCapture.1', 'RenderDoc.RDCSettings.1',
                          '5D6BF029-A6BA-417A-8523-120492B1DCE3',
                          'D3209233-27AA-45CD-9D80-41734946FB36'))
  {
    Forbid-Text $installerPath $installerText $forbidden
  }

  try
  {
    [xml]$installerXml = $installerText
    foreach($component in $installerXml.SelectNodes('//*[local-name()="Component"]'))
    {
      $guid = $component.GetAttribute('Guid')
      if(-not $allowedComponentGuids.Contains($guid))
      {
        $errors.Add("$installerPath component $($component.Id) has non-product GUID '$guid'")
      }
    }
  }
  catch
  {
    $errors.Add("Invalid installer XML in ${installerPath}: $($_.Exception.Message)")
  }
}

$packageScriptPath = 'util\buildscripts\scripts\make_package_win32.sh'
$packageScript = Read-RepositoryText $packageScriptPath
Require-Text $packageScriptPath $packageScript 'generate_product_identity.py --check'
Require-Text $packageScriptPath $packageScript 'candle.exe" -Ibuild'

foreach($deliveryScriptPath in @('util\buildscripts\build_windows_release_matrix.ps1',
                                 'util\buildscripts\build_dgcore_injection_variants.ps1',
                                 'util\buildscripts\scripts\compile_win32.sh'))
{
  $deliveryScript = Read-RepositoryText $deliveryScriptPath
  Require-Text $deliveryScriptPath $deliveryScript 'product_identity.json'
  foreach($hardcodedOutput in @("'$($identity.coreBaseName).dll'",
                                "'$($identity.uiBaseName).exe'",
                                "'$($identity.commandBaseName).exe'",
                                "'$($identity.uiStubBaseName).exe'",
                                "'$($identity.shimBaseName)64.dll'",
                                "'$($identity.coreBaseName).json'"))
  {
    Forbid-Text $deliveryScriptPath $deliveryScript $hardcodedOutput
  }
}

$shimProjectPath = 'renderdocshim\renderdocshim.vcxproj'
$shimProject = Read-RepositoryText $shimProjectPath
Require-Text $shimProjectPath $shimProject '<ResourceCompile Include="renderdocshim.rc" />'
Require-Text $shimProjectPath $shimProject 'RDOC_SHIM_RESOURCE_64=1'

$shimFiltersPath = 'renderdocshim\renderdocshim.vcxproj.filters'
$shimFilters = Read-RepositoryText $shimFiltersPath
Require-Text $shimFiltersPath $shimFilters '<ResourceCompile Include="renderdocshim.rc" />'

$qrenderdocPath = 'qrenderdoc\Code\qrenderdoc.cpp'
$qrenderdoc = Read-RepositoryText $qrenderdocPath
Require-Text $qrenderdocPath $qrenderdoc `
  'parser.setApplicationDescription(tr("Qt UI for %1").arg(lit(RDOC_PRODUCT_DISPLAY_NAME)))'
Forbid-Text $qrenderdocPath $qrenderdoc 'Qt UI for RenderDoc'

$aboutPath = 'qrenderdoc\Windows\Dialogs\AboutDialog.cpp'
$about = Read-RepositoryText $aboutPath
Require-Text $aboutPath $about 'RDOC_PRODUCT_DISPLAY_NAME'
Require-Text $aboutPath $about 'ui->rdocName->setText'

$mainWindowPath = 'qrenderdoc\Windows\MainWindow.cpp'
$mainWindow = Read-RepositoryText $mainWindowPath
Require-Text $mainWindowPath $mainWindow 'lit(RDOC_PRODUCT_DISPLAY_NAME " ")'

$legacyNames = @(& git -C $repositoryRoot grep --text -n -i -E `
  'rendertest|qrendertest' -- docs tools 2>$null)
$legacyNamesExitCode = $LASTEXITCODE
if($legacyNamesExitCode -eq 0)
{
  foreach($legacyName in $legacyNames)
  {
    $errors.Add("Legacy RenderTest documentation/tool identity remains: $legacyName")
  }
}
elseif($legacyNamesExitCode -ne 1)
{
  throw "git grep failed while checking legacy RenderTest names with exit code $legacyNamesExitCode"
}
else
{
  & git -C $repositoryRoot rev-parse --is-inside-work-tree | Out-Null
  if($LASTEXITCODE -ne 0)
  {
    throw 'Could not restore the successful Git identity-check state'
  }
}

if($errors.Count -gt 0)
{
  throw ("Windows identity contracts failed:`n - " + ($errors -join "`n - "))
}

Write-Host ((
  'Windows identity contracts passed: product={0}, core={1}.dll, UI={2}.exe, ' +
  'command={3}.exe, shim={4}32/64.dll') -f $identity.productDisplayName,
    $identity.coreBaseName, $identity.uiBaseName, $identity.commandBaseName,
    $identity.shimBaseName)
