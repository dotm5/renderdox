# RenderDox code layout

[Project showcase](../../README.md) · [Development notes](../CONTRIBUTING.md)

| Path | Role |
| --- | --- |
| `renderdoc/` | Capture runtime, replay controller, shader tooling and API-specific backends under `driver/` |
| `qrenderdoc/` | Qt desktop application, GUI extensions and Python integration |
| `renderdoccmd/` | Native command-line tools |
| `renderdocshim/` | Windows injection shim |
| `bootstrap/` | DXGI, D3D11, D3D12 and Aftermath proxies and loader integrations |
| `safetyhook/`, `zydis/` | Hook and instruction-decoding components |
| `tools/renderdoc-mcp/` | Portable MCP service, native worker adapters and analysis workflows |
| `build/product_identity.json` | DComp product and runtime identity contract |
| `util/buildscripts/` | Release builds, dependency packaging and artifact manifests |
| `.github/workflows/` | Current cloud build and release workflows |
| `docs/` | Guides and Sphinx reference sources |

The native Windows solution is `renderdoc.sln`. Its historical source directory names
remain useful when comparing with RenderDoc; packaged Windows products use the DComp identity.
