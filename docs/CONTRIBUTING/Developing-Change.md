# Developing a RenderDox change

[Development notes](../CONTRIBUTING.md) · [Usage guide](../../USAGE.md)

Work can start directly from an idea, a capture, a runtime observation or a target-specific
problem. Feature scope and implementation choices are decided by the project's maintainer.

Custom inline hooks, proxy forwarding, alternative injection paths, .NET/CLR adapters,
AI-assisted code and exploratory UI or analysis features are in scope. Drafts and incomplete
experiments can be shared at any stage.

Core capture and replay code is under `renderdoc/`; desktop changes are under `qrenderdoc/`.
Bootstrap integrations live in `bootstrap/`, and MCP adapters and workflows live in
`tools/renderdoc-mcp/`. These boundaries make later upstream comparisons easier.

C++ facilities, STL containers, `auto` and `nullptr` can be chosen as appropriate to the
implementation and selected toolchain. Existing ABI, string encodings and resource lifetimes
still describe how the surrounding code works.
