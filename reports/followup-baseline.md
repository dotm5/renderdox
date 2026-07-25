# Follow-up frozen baseline

## Anchors

| Role | Commit |
|---|---|
| Official RenderDoc v1.45 | `2fc0bc04cb95499635f63986a55bc6f67849dd9f` |
| Stable Windows port used as feature base | `25df92efcf0f5e138f3bc663fe54dcf4c8f72149` |
| Product identity | RenderTest (`rendertest.dll`, `qrendertest.exe`, `rendertestcmd.exe`, `rendertestshim64.dll`) |
| Toolchain | Visual Studio 18 Enterprise MSBuild, MSVC v143, Windows SDK 10.0.26100.0 |

The stable Windows port was clean before follow-up implementation. Official
v1.45 remained the upstream source baseline; no donor branch or commit was
merged or cherry-picked.

## Build and startup baseline

| Gate | Result | Time |
|---|---|---:|
| Development x64 v143 Rebuild | PASS, 0 warnings/errors | 182.18 s |
| Release x64 v143 Rebuild | PASS, 0 warnings/errors | 661.37 s |
| Development qrenderdoc startup | PASS, ready/responding | 0.395 s |

Raw logs and binlogs are preserved under `audit/followup/baseline/`.

## Frozen capture matrix

| ID | API | SHA-256 | Actions | Draw | Dispatch | ExecuteIndirect | MultiAction | Shaders | Textures | Buffers | Replay |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| d3d11-empty | D3D11 | `3FCD95281535515971AD580D79319E0AF65049E61FFC70613BD55C18F0BF8FCF` | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | PASS |
| d3d12-empty | D3D12 | `FA4729D7859823FCD8EE193DE500DA488FE4F30109B7CEB2E5B01F14AA1CB713` | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | PASS |
| opengl-empty | OpenGL | `948ADBE9DEFFEE6C0E10358AD9377D216C93C2ADDADF0095C21426E27A032637` | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | PASS |
| vulkan-empty | Vulkan | `307461A720A3DD1166131DDCD0B7F0C95469AEBB25DB45D3E645EC94BC4D1BD9` | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | PASS |
| ue5-d3d12-owned | D3D12 | `0D7E5BA79EEEE1EAD9282BE448BA47BAFF44627EF4F5E814EF9336EA727CB8A3` | 927 | 43 | 48 | 12 | 6 | 89 | 114 | 207 | PASS |

The small API captures establish open/replay and API identity, not broad draw
coverage. The owned UE5 capture is the substantive D3D12 baseline. Capture
format version is `UNKNOWN` because v1.45's public CaptureFile API does not
expose it.

