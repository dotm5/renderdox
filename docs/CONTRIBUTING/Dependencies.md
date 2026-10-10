# RenderDox build environment

[Project showcase](../../README.md) · [Compiling](Compiling.md)

## Windows portable packages

The current release scripts use PowerShell 7, the latest installed stable Visual Studio
C++ toolset, ClangCL for the second compiler variant, and the newest complete installed
Windows SDK. Toolset and SDK discovery is shared by the release and injection-variant
scripts. `-MSVCPlatformToolset v143` and `-WindowsSDKVersion 10.0.26100.0` remain available
for reproducing an older environment. Package manifests record the resolved toolset,
C++ tools version, SDK and Visual Studio path.

The desktop build uses the bundled Qt, Python and PySide2/Shiboken2 dependency set under
`qrenderdoc/3rdparty`. MSBuild CI downloads the pinned dependency archive before building.
SafetyHook and Zydis sources are part of the checkout.

MCP packaging uses the latest stable Python available in the Actions manifest
within the supported range `>=3.12 <3.16`, and the dependencies in
[packaging/requirements.txt](../../tools/renderdoc-mcp/packaging/requirements.txt).
It bundles a separate worker interpreter matching the native Python bindings.
End users of a complete portable package do not need a system Python installation.
The packaged Proxy Builder still requires Visual Studio C++/MASM to compile generated
DLLs; JVM host generation additionally requires a JDK. CI uses Temurin JDK 25 LTS for its
owned host fixture.

## POSIX core builds

The [CMake workflow](../../.github/workflows/cmake.yml) records the Linux/macOS environments
used for core builds. These jobs build without the desktop Qt/Python components.
They do not produce the Windows portable package.

See the [release scripts](../../util/buildscripts/README.md) for the current build entry points.

## Stable CI environment

The maintained workflows use GitHub's `ubuntu-latest`, `macos-latest` and
`windows-latest` aliases, which follow generally available runner images. The
workflow logs identify the actual image and tool versions used by each build.
Actions follow their current stable major tags to receive compatible patch
updates; MCP packaging selects the newest supported stable Python from the
Actions manifest, excluding prereleases. The upper bound follows PyInstaller
support. Python and JDK setup run before native compilation so unavailable
environments fail early. JVM fixtures use Temurin 25 LTS. Packaging dependencies
are pinned in the requirements file.

The bundled Qt/Python/PySide2 archive is a separate native ABI contract, verified
by SHA-256. Changing the CI packaging interpreter does not replace that archive
or its matching replay worker.

The inherited `build.sh` Docker recipes target old Linux ABI compatibility. They
are separate from these maintained CI environments and Windows releases.
