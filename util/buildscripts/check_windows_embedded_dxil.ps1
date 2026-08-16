[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$DllPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if(-not (Test-Path -LiteralPath $DllPath -PathType Leaf))
{
  throw "Core DLL was not found: $DllPath"
}
$resolvedDllPath = (Resolve-Path -LiteralPath $DllPath).Path

if(-not ('DCompEmbeddedDxil.NativeMethods' -as [type]))
{
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace DCompEmbeddedDxil
{
  public static class NativeMethods
  {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr LoadLibraryExW(string fileName, IntPtr file, uint flags);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr FindResourceW(IntPtr module, IntPtr name, IntPtr type);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SizeofResource(IntPtr module, IntPtr resourceInfo);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr LoadResource(IntPtr module, IntPtr resourceInfo);

    [DllImport("kernel32.dll")]
    public static extern IntPtr LockResource(IntPtr resourceData);

    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool FreeLibrary(IntPtr module);
  }
}
'@
}

$embeddedResourceType = 256
$requiredResources = [ordered]@{
  RESOURCE_fixedcol_0_dxbc = 113
  RESOURCE_fixedcol_1_dxbc = 114
  RESOURCE_fixedcol_2_dxbc = 115
  RESOURCE_fixedcol_3_dxbc = 116
  RESOURCE_quadwrite_dxbc = 117
  RESOURCE_pixelhistory_primitiveid_dxbc = 122
  RESOURCE_pixelhistory_fixedcol_0_dxbc = 123
  RESOURCE_pixelhistory_fixedcol_1_dxbc = 124
  RESOURCE_pixelhistory_fixedcol_2_dxbc = 125
  RESOURCE_pixelhistory_fixedcol_3_dxbc = 126
  RESOURCE_pixelhistory_fixedcol_4_dxbc = 127
  RESOURCE_pixelhistory_fixedcol_5_dxbc = 128
  RESOURCE_pixelhistory_fixedcol_6_dxbc = 129
  RESOURCE_pixelhistory_fixedcol_7_dxbc = 130
}

$loadLibraryAsDataFile = 0x00000002
$module = [DCompEmbeddedDxil.NativeMethods]::LoadLibraryExW(
    $resolvedDllPath, [IntPtr]::Zero, $loadLibraryAsDataFile)
if($module -eq [IntPtr]::Zero)
{
  $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
  throw "LoadLibraryExW failed for $resolvedDllPath with Win32 error $errorCode"
}

$errors = [System.Collections.Generic.List[string]]::new()
try
{
  foreach($resource in $requiredResources.GetEnumerator())
  {
    $resourceInfo = [DCompEmbeddedDxil.NativeMethods]::FindResourceW(
        $module, [IntPtr]$resource.Value, [IntPtr]$embeddedResourceType)
    if($resourceInfo -eq [IntPtr]::Zero)
    {
      $errors.Add("$($resource.Key) (ID $($resource.Value)) is missing")
      continue
    }

    $resourceSize = [DCompEmbeddedDxil.NativeMethods]::SizeofResource($module, $resourceInfo)
    if($resourceSize -lt 4)
    {
      $errors.Add("$($resource.Key) (ID $($resource.Value)) has invalid size $resourceSize")
      continue
    }

    $resourceData = [DCompEmbeddedDxil.NativeMethods]::LoadResource($module, $resourceInfo)
    $resourcePointer = if($resourceData -eq [IntPtr]::Zero) {
      [IntPtr]::Zero
    } else {
      [DCompEmbeddedDxil.NativeMethods]::LockResource($resourceData)
    }
    if($resourcePointer -eq [IntPtr]::Zero)
    {
      $errors.Add("$($resource.Key) (ID $($resource.Value)) could not be loaded")
      continue
    }

    $magicBytes = [byte[]]::new(4)
    [Runtime.InteropServices.Marshal]::Copy($resourcePointer, $magicBytes, 0, 4)
    $magic = [Text.Encoding]::ASCII.GetString($magicBytes)
    if($magic -ne 'DXBC')
    {
      $errors.Add("$($resource.Key) (ID $($resource.Value)) has signature '$magic', expected 'DXBC'")
    }
  }
}
finally
{
  [void][DCompEmbeddedDxil.NativeMethods]::FreeLibrary($module)
}

if($errors.Count -gt 0)
{
  throw "Embedded DXIL validation failed for $resolvedDllPath`n$($errors -join [Environment]::NewLine)"
}

Write-Host ("Embedded DXIL resources passed: {0} resources in {1}" -f `
    $requiredResources.Count, $resolvedDllPath)
