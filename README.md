<h1 align="center">RenderDox</h1>

<p align="center">A downstream RenderDoc branch for reproducible Windows capture builds.</p>

[![MIT licensed](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE.md)
[![Upstream](https://img.shields.io/badge/upstream-RenderDoc-blue.svg)](https://github.com/baldurk/renderdoc)
[![CI](https://github.com/dotm5/renderdox/actions/workflows/ci.yml/badge.svg?branch=dgcore-main&event=push)](https://github.com/dotm5/renderdox/actions)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-v2.0%20adopted-ff69b4.svg)](docs/CODE_OF_CONDUCT.md) 

RenderDox is a downstream branch of [RenderDoc](https://github.com/baldurk/renderdoc), the frame-capture based graphics debugger for Vulkan, D3D11, D3D12, OpenGL, and OpenGL ES. It preserves RenderDoc's capture and replay formats while maintaining an isolated Windows runtime identity, reproducible MSVC and ClangCL Release builds, and a focused set of capture and analysis extensions.

RenderDox follows RenderDoc's intended-use boundary and is intended for debugging programs you own or are authorised to analyse. Projects created with third-party engines such as Unreal Engine or Unity are supported. This fork is independently maintained and is not supported by the upstream RenderDoc maintainers.

For RenderDox-specific questions, suggestions, or problems, [create an issue](https://github.com/dotm5/renderdox/issues). For upstream RenderDoc documentation and community support, see the links below.

RenderDox currently ships as a portable x64 Windows build rather than an MSI. The full Release matrix includes the GUI, command-line tools, capture runtime, Qt and Python runtimes, and is produced from the repository build scripts. Official RenderDoc installers and packages remain available from the upstream [builds page](https://renderdoc.org/builds).

* **Upstream**: [RenderDoc repository](https://github.com/baldurk/renderdoc), [stable and nightly builds](https://renderdoc.org/builds)
* **Documentation**: [RenderDoc HTML documentation](https://renderdoc.org/docs), [Videos](https://www.youtube.com/user/baldurkarlsson)
* **RenderDox issues**: [Issue tracker](https://github.com/dotm5/renderdox/issues)
* **Code of Conduct**: [Contributor Covenant](docs/CODE_OF_CONDUCT.md)
* **Information for contributors**: [All contribution information](docs/CONTRIBUTING.md), [Compilation instructions](docs/CONTRIBUTING/Compiling.md)
* **Upstream extensions**: [RenderDoc extensions repository](https://github.com/baldurk/renderdoc-contrib)

Screenshots
--------------

| [ ![Texture view](https://renderdoc.org/fp/ts_screen1.jpg?2) ](https://renderdoc.org/fp/screen1.jpg) | [ ![Pixel history & shader debug](https://renderdoc.org/fp/ts_screen2.jpg?2) ](https://renderdoc.org/fp/screen2.png) |
| --- | --- |
| [ ![Mesh viewer](https://renderdoc.org/fp/ts_screen3.jpg?2) ](https://renderdoc.org/fp/screen3.png) | [ ![Pipeline viewer & constants](https://renderdoc.org/fp/ts_screen4.jpg?2) ](https://renderdoc.org/fp/screen4.png) |

API Support
--------------

|                          | Windows                  | Linux                    | Android                   |
| ------------------------ | ------------------------ | ------------------------ | ------------------------  |
| Vulkan                   | :heavy_check_mark:       | :heavy_check_mark:       | :heavy_check_mark:        |
| OpenGL ES 2.0 - 3.2      | :heavy_check_mark:       | :heavy_check_mark:       | :heavy_check_mark:        |
| OpenGL 3.2 - 4.6 Core    | :heavy_check_mark:       | :heavy_check_mark:       |  N/A                      |
| D3D11 & D3D12            | :heavy_check_mark:       |  N/A                     |  N/A                      |
| OpenGL 1.0 - 2.0 Compat  | :heavy_multiplication_x: | :heavy_multiplication_x: |  N/A                      |
| D3D9 & 10                | :heavy_multiplication_x: |  N/A                     |  N/A                      |
| Metal                    |  N/A                     |  N/A                     |  N/A                      |

* Nintendo Switch&trade; support is distributed separately for authorized developers as part of the NintendoSDK. For more information, consult the Nintendo Developer Portal.

Downloads
--------------

RenderDox portable builds are produced from the `dgcore-main` branch. Until signed binary releases are published, build from source and use the generated package directory under the configured artifacts root.

If you need the standard RenderDoc distribution, use an upstream [stable build](https://renderdoc.org/builds). RenderDox packages are intended for the additional runtime and build requirements documented in this repository.

Documentation
--------------

The text documentation is available [online for the latest stable version](https://renderdoc.org/docs/), as well as in [renderdoc.chm](https://renderdoc.org/docs/renderdoc.chm) in any build. It's built from [restructured text with sphinx](docs).

As mentioned above there are some [youtube videos](https://www.youtube.com/user/baldurkarlsson) showing the use of some basic features and an introduction/overview.

There is also a great presentation by [@Icetigris](https://twitter.com/Icetigris) which goes into some details of how RenderDoc can be used in real world situations: [slides are up here](https://docs.google.com/presentation/d/1LQUMIld4SGoQVthnhT1scoA3k4Sg0as14G4NeSiSgFU/edit#slide=id.p).

License
--------------

RenderDox is derived from RenderDoc and remains under the MIT license. See [LICENSE.md](LICENSE.md) for the full text and third-party library acknowledgements.

Compiling
---------

The upstream compilation instructions remain applicable. For the complete Windows x64 MSVC and ClangCL portable Release matrix, run:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\util\buildscripts\build_windows_release_matrix.ps1 `
  -Target Rebuild -ChildPropagation OneGeneration
```

See [Compiling.md](docs/CONTRIBUTING/Compiling.md) for the upstream platform requirements. The matrix command above defines the downstream Windows Release boundary.

Contributing & Development
--------------

I've added some notes on how to contribute, as well as where to get started looking through the code in [Developing-Change.md](docs/CONTRIBUTING/Developing-Change.md). All contribution information is available under [CONTRIBUTING.md](docs/CONTRIBUTING.md).

