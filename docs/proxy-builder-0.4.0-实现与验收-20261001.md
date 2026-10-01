# Proxy Builder 0.4.0：实现与验收

2026-10-01。实现位于 `tools/proxy-builder`；交付与证据位于
`D:\rdoc-port\artifacts\proxy-builder-040-20261001`。

## 已落地的路径

|机制|生成器实现|验证范围|
|---|---|---|
|普通导入、GetProcAddress、直接 EAT|物理 x64 ASM stub，保留名称、ordinal、别名和调用约定|16 线程、整数/浮点/栈参数及 raw EAT|
|Streamline / sl.interposer|streamline profile、物理 stub、Core 首次调用激活；复用 Core inline/topmost-provider|代理契约、ABI、Core 握手；真实 interposer 捕获待验证|
|NGX/其他 SDK 加载槽|ngx/generic profile，精确导出及可配置首次调用、指定导出、模块出现触发|自有进程时序与转发|
|NVAPI 数字查询|保留未知 ID/NULL，只对明确映射且匹配原导出地址的结果返回代理 stub|已知/未知/NULL 与原地址匹配|
|Vulkan 函数查询|instance/device 查询分开，保留原 handle 与不同设备返回地址|查询行为；完整 Core Layer 另走宿主适配器|
|D3D12 Agility / 工厂入口|agility profile，D3D12GetInterface 精确转发，显式 DATA 类型声明|工厂转发及数据契约；未知工厂接口包装不在此轮扩展|
|包装 DLL 链|system/sibling/absolute provider、哈希与文件身份、下一层元数据、循环拒绝|自有链、循环、原件失败|
|系统 loader forwarder|可选 linker 转发；DATA 始终指向原件真实存储|动态/静态数据导入、写入共享、类型化导入库|
|早期启动 gate|可选 entry-point INT3/VEH，恢复入口字节和页保护|启动期导入 DLL，在 EXE main 前握手|
|插件与 ASI|显式插件列表、Core 后加载插件，独立 ASI/DLL 产物|加载顺序、宿主握手|
|JVM|native bridge、Java premain agent/JAR|Java 17+ premain 与同步握手|
|OpenXR|显式 Layer、实例/会话 dispatch、完整 pNext binding 查找、应用帧捕获范围|多实例/会话、帧边界和协商|
|Vulkan Layer|桥接 Core 已有的四个 Layer 入口及 manifest|Layer 协商/查询与真实 Core 构建契约|

支持 generic、streamline、ngx、nvapi、vulkan、agility 六种 profile；同一 DLL 可同时包含
NVAPI/Vulkan 查询及普通导出。支持 worker、first-call、export、entry-point、manual、
module-load 六种激活模式。详细 schema、命令和配置样例见
[ROUTES.md](../tools/proxy-builder/ROUTES.md)。

所有产物使用本项目的 DCOMP API。默认 `build` 使用统一运行时；旧 `generate --template`
入口兼容保留。未加入外置进程注入器。

## 实现边界

1. `status=verified` 代表编译、导出契约和产物哈希验证。Core 状态 2 代表 API 握手；均不能替代真实设备包装、捕获和回放证明。
2. NVAPI/Vulkan 映射限于已存在直接导出且原查询地址相同的函数；未知签名、非导出函数或设备专属不同地址保持原样。不会伪造 GPU/SDK 能力。
3. DATA/linker forwarder 由 Windows loader 直接解析，不能提供物理 stub 的调用 gate/运行时哈希拦截。原件必须满足正常 loader 搜索规则；pure DATA 导入也可能先于代理 DllMain 加载原件。
4. entry-point 仅用于启动期加载的代理；first-call 须发生在 loader lock 外且早于图形对象创建。worker、module-load 和 OpenXR 协商不保证早于应用已创建的设备。
5. `requireCore` 在物理函数转发前强制 Core 初始化，优先于 manual/延迟模式；DATA/linker 不经过此检查。
6. 已知生成代理的循环可以拒绝；无元数据的第三方包装器内部循环不作保证。正在使用的代理、Core 与插件不支持卸载。
7. 自动生成器匹配输入原件的精确导出契约。此轮 Aftermath 输入为 9 个原始导出，另加 5 个控制导出；不会自动替换已有 43-name union 代理。

## 验收结果

|验收|结果|证据|
|---|---|---|
|Python 单元验证|19/19 通过|`unit-final.log`|
|MSVC/ClangCL 路径验收|40/40 自有进程通过|`routes-final/results.json`|
|同 DLL 双查询协议|2/2 通过|`mixed-final/results.json`|
|ABI/raw EAT 回归|两个编译器，共 512,000 次调用通过|`abi-regression/*/smoke*.json`|
|原生 System32 契约|DXGI/D3D11 双编译器通过；未声明 DATA 的 D3D12 被明确拒绝|`abi-regression/results.json`|
|最终便携 EXE 原生构建|真实 Aftermath/MSVC 与显式 DATA 的 D3D12/ClangCL 通过|各输出的 `build-result.json`、`final-verify.json`|
|最终便携 EXE 宿主构建|真实 Core 的 OpenXR/Vulkan Layer/ClangCL 通过|`final-openxr.json`、`final-vulkan-layer.json`|

原生自测工程使用 `/W4 /WX`。套件包括 DATA 动态/静态导入、别名地址共享、插件顺序、
模块出现触发、坏原件/缺 Core、代理链及循环、入口 gate、Java premain、OpenXR 多会话
捕获所有权与 Vulkan 协商。未以测试 DLL 作为游戏代理发布。

交付为 `Proxy-Builder-0.4.0-windows-x64.zip`，自带 Python 运行时、原生/宿主模板、样例、
Khronos 固定版本头文件及许可证；编译仍需要 Visual Studio C++/MASM，JVM 额外需要 JDK。
Core 仍由 `--core` 指定，不随独立生成器包重复分发。

## 下一阶段

真实 Aftermath 产物位于 `Aftermath-待运行时验证/bin/Release`，包含代理、改名原件、
已验证 Core 与 enable marker；尚未部署到游戏。需在明确的游戏 PID/build 中验证加载链、
接入时序、设备包装、单帧捕获、RDC 回放和退出稳定性。其他 SDK/宿主路径按其真实应用
分别验证，不将一个游戏的成功推广到所有 profile。

Khronos 头文件来自官方 OpenXR-SDK，固定提交及 SHA256 见
`tools/proxy-builder/vendor/openxr/PROVENANCE.json`。Streamline 特殊路径的背景见
[RenderDoc issue #3257](https://github.com/baldurk/renderdoc/issues/3257)。
