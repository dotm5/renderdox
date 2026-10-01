# RenderDox build environment

[Project showcase](../../README.md) · [Compiling](Compiling.md)

## Windows portable packages

The current release scripts use PowerShell 7, Visual Studio with MSBuild and the v143
C++ toolset, ClangCL for the second compiler variant, and Windows SDK 10.0.26100.0 by default.
The scripts locate the installed toolchain and accept an explicit SDK selection.

The desktop build uses the bundled Qt, Python and PySide2/Shiboken2 dependency set under
`qrenderdoc/3rdparty`. MSBuild CI downloads the pinned dependency archive before building.
SafetyHook and Zydis sources are part of the checkout.

MCP packaging uses Python 3.12 and the dependencies in
[packaging/requirements.txt](../../tools/renderdoc-mcp/packaging/requirements.txt).
It bundles a separate worker interpreter matching the native Python bindings.
End users of a complete portable package do not need a system Python installation.
The packaged Proxy Builder still requires Visual Studio C++/MASM to compile generated
DLLs; JVM host generation additionally requires a JDK. CI uses Temurin JDK 21 for its
owned host fixture.

## POSIX core builds

The [CMake workflow](../../.github/workflows/cmake.yml) records the Linux/macOS environments
used for core builds. These jobs build without the desktop Qt/Python components.
They do not produce the Windows portable package.

See the [release scripts](../../util/buildscripts/README.md) for the current build entry points.
