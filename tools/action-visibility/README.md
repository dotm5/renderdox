# Action Visibility replay tests

These scripts capture and validate RenderDoc-owned D3D11, D3D12, and Vulkan test cases.
They never modify the source RDC. The replay worker verifies:

- only eligible leaf draw/dispatch EIDs are accepted;
- duplicate, invalid, indirect, and multi-action EIDs are rejected;
- disabling a direct action changes an observable texture or UAV buffer;
- clearing the disabled set restores the output exactly;
- the source capture SHA-256 is unchanged.

Capture the owned cases:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\capture_owned_cases.ps1 `
  -DemoBinary D:\path\to\demos_x64.exe `
  -OutputRoot D:\path\to\captures `
  -VulkanSdk C:\path\to\VulkanSDK
```

Run replay validation:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1 `
  -CaptureManifest D:\path\to\captures\capture-manifest.json `
  -OutputRoot D:\path\to\results
```

The capture manifest and every per-case `result.json` use schema version 1. Generated
RDCs, DDS files, buffers, and logs belong in an external audit directory, not in Git.
