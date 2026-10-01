# Proxy Builder 0.4.1

`build` 默认使用统一路径运行时。七种原生 profile、六种激活时机、代理链、
DATA 转发及 ASI/JVM/OpenXR/Vulkan Layer 自动构建见 [ROUTES.md](ROUTES.md)。
可运行 `proxy-builder.exe profiles` 查看接口；需要逐个目标验证实际捕获。

0.4.1 恢复专用 Aftermath proxy 的独立 worker 启动与惰性原件转发。
Aftermath 自动识别为 `aftermath`，不需要额外 JSON 才能在 DLL 加载后激活 Core。
SDK/普通加载槽默认 worker；DXGI/D3D/OpenGL、Streamline 图形 provider、Vulkan/Agility
默认首次调用。显式 activation 始终优先。Core 是否能早于设备创建，仍按目标验证。

```powershell
proxy-builder.exe build D:\original\GFSDK_Aftermath_Lib.x64.dll --output D:\proxy-build\aftermath-041 --copy-original --core D:\DComp\dgcore.dll --enable-core
```

以下是保留的 0.3.1 模板说明，适用于未传 profile/config 的旧 `generate` 命令。
新版 `build` 的默认时序、控制导出、数据处理和验收边界以 ROUTES.md 为准。

只读解析 PE，不加载候选 DLL，也不执行第三方仓库代码。生成器复用本项目现有
bootstrap 运行时，输出锁定导出契约、DEF、C++、ASM 和独立 MSBuild 项目。
开发时需要现代 Python；交付的 `proxy-builder.exe` 自带运行时。编译需要 Visual Studio C++/MASM，工具会自动发现 MSBuild，支持 MSVC / ClangCL。

一条命令制作 DLL（只向新的输出目录写入，不部署到游戏）：

```powershell
proxy-builder.exe build D:\original\vendor.dll --output D:\proxy-build\vendor --copy-original
proxy-builder.exe build C:\Windows\System32\dxgi.dll --output D:\proxy-build\dxgi --toolchain ClangCL
proxy-builder.exe build D:\original\GFSDK_Aftermath_Lib.x64.dll --output D:\proxy-build\aftermath --route streamline-bootstrap --original GFSDK_Aftermath_Lib_orig.dll --copy-original --core D:\DComp\dgcore.dll --enable-core
```

`build` 完成解析、生成、编译、导出契约检查。成功返回 `status=verified` 与 DLL 路径，
保存 `build.log`、`build-result.json`、`exports.json` 和自带头文件的可再次编译工程。
源码、原 DLL、Core 复制和产物均绑定 SHA256；编译失败或输入/生成文件改变不会被接受。
`--copy-original` 把原 DLL 复制为输出中同目录的改名原件；`--core` 复制 Core，
`--enable-core` 在输出目录生成 `dgcore.enable`。省略启用参数时不生成 marker。
`--msbuild` 可指定编译器位置。已有输出目录不被覆盖。

`--route` 的三种路径：

|路径|转发和接入方式|验收边界|
|---|---|---|
|system-dll|System32 原件，复用 DXGI/D3D 模板首次调用握手|具体图形对象创建顺序|
|app-local|同目录改名原件，复用 Aftermath 的异步 Core 激活|每个应用的时序|
|streamline-bootstrap|同目录改名原件及 Aftermath 激活方式，显式标记 Streamline 场景|物理 EAT stub 转发已自测，完整 interposer/Core 路由需真实应用验证|

`auto` 根据导出模块名选择 system-dll 或 app-local；不会仅凭导出表宣称识别了 Streamline。
[#3257](https://github.com/baldurk/renderdoc/issues/3257) 描述了 `sl.interposer` 直接遍历 EAT，
绕过 IAT/GetProcAddress hook 的路径。本项目 Core 的 `win32_hook.cpp` 有 inline/topmost-provider
接入逻辑；Builder 复用已有 bootstrap，不把导出转发成功当成 Core hook 成功。
生成的是有物理地址的 x64 stub，支持导入、GetProcAddress 和直接 EAT 地址调用。
自有 raw-eat 测试验证了后者的 16 线程、整数/浮点/ordinal/别名转发。

```powershell
python proxy_builder.py inspect C:\Windows\System32\dxgi.dll
python proxy_builder.py generate C:\Windows\System32\dxgi.dll --template system --output D:\proxy-build\dxgi
python proxy_builder.py generate D:\original\vendor.dll --template app-local --original vendor_orig.dll --output D:\proxy-build\vendor
MSBuild D:\proxy-build\vendor\proxy.vcxproj /p:Configuration=Release /p:Platform=x64
python proxy_builder.py verify D:\original\vendor.dll D:\proxy-build\vendor\bin\Release\vendor.dll
```

便携包附带 `runtime-templates`，生成与编译不依赖开发机源码目录。
输出目录必须为空；生成是确定性的，锁文件包含输入哈希、生成器哈希和全部生成源码/头文件哈希。
数据/未知导出、非 x64、无效 ordinal 和无法安全表示的名字会明确拒绝，不丢弃导出。
名称、ordinal-only、forwarder 及同 RVA/forwarder 的别名关系均保留并在 verify 中检查。
输出调用约定由已有 x64 汇编转发保留，不能从 PE 推断具体函数签名。

`system` 只允许 DXGI/D3D11/D3D12，且当前 DLL 必须包含所选运行时的基线名称。
当前测试系统 D3D12 的 `D3D12DeviceRemovedExtendedData` 位于非执行区，完整生成会
被拒绝。该拒绝是检测结果，不代表已经解决数据导出，也不是自动改动已有代理。

`app-local` 使用同目录改名原 DLL；独立线程负责可选 Core 激活。
`DCOMP_BOOTSTRAP_ENABLE=1` 或同目录 `dgcore.enable` 开启激活。它不能保证接入早于
图形对象创建。`system` 继续使用现有首次导出调用初始化与握手失败回退策略。
代理仅供明确拥有或获授权的应用；部署前备份原 DLL，按应用单独验证。

静态与自有原生验证：

```powershell
pwsh -NoProfile -File tests\run_static_acceptance.ps1 -Python C:\Python312\python.exe -OutputDirectory D:\proxy-acceptance
```

套件编译 MSVC/ClangCL 生成代理和 D3D12 样例，检查导出契约，验证 16 线程首次调用、
8 参数整数/浮点转发、ordinal-only、别名地址一致、forwarder、关闭 Core 和 Core 缺失。
测试 DLL 与模拟程序不作为实际应用的生产代理发布。原版 Aftermath 的 43-name union proxy 保持独立；
自动生成器按指定原 DLL 的精确名称和 ordinal 契约生成，不擅自替换已有 union 部署。
