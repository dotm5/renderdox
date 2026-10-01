# Proxy Builder 0.4.1 路径与使用

只读解析 PE，自动生成独立工程，调用 MSBuild，再检查导出契约。
便携 EXE 自带 Python；编译需要 Visual Studio C++/MASM。JVM 构建额外需要 JDK，
生成的 agent 支持 Java 17+。所有输出写入新目录，不部署游戏或覆盖已有产物。

```powershell
proxy-builder.exe profiles
proxy-builder.exe build D:\original\vendor.dll --output D:\build\vendor --copy-original
proxy-builder.exe build D:\original\GFSDK_Aftermath_Lib.x64.dll --output D:\build\aftermath --profile streamline --original GFSDK_Aftermath_Lib_orig.dll --copy-original --core D:\DComp\dgcore.dll --enable-core
proxy-builder.exe build C:\Windows\System32\dxgi.dll --output D:\build\dxgi --toolchain ClangCL
proxy-builder.exe build D:\original\nvapi64.dll --output D:\build\nvapi --profile nvapi --config nvapi.json --copy-original
```

`build` 默认统一运行时、`--profile auto`。识别导出接口不会自动证明捕获兼容。
原版 `generate --template` 未传 profile/config 时仍生成旧模板。新用法：

```powershell
proxy-builder.exe generate D:\original\vendor.dll --template app-local --profile generic --config route.json --output D:\build\sources
proxy-builder.exe verify D:\original\vendor.dll D:\build\vendor\bin\Release\vendor.dll --lock D:\build\vendor\exports.json
```

|Profile|行为|
|---|---|
|generic|任意合规 x64 函数导出、原件路径、初始化时机、插件及哈希|
|aftermath|SDK 加载槽，Core worker 与 SDK 惰性转发独立，默认识别三个原件改名|
|streamline|物理 EAT stub、Core 激活，沿用已有 inline/topmost-provider 接入|
|ngx|精确 NGX/SDK 导出及原件转发、支持晚加载模块触发|
|nvapi|数字 ID 查询，命中且原件返回地址匹配时返回本代理 stub|
|vulkan|instance/device proc-address 查询，保留 handle、未知函数与 NULL|
|agility|D3D12GetInterface/工厂入口转发、显式 DATA 契约|

同一 DLL 的 NVAPI、Vulkan 和普通导出可同时处理。匹配查询入口自动纳入分发，
`dispatch` 分别配置两个协议。不伪造 GPU、SDK 能力或未知接口返回值。
仅具有直接导出且原查询结果与该导出地址一致的函数返回代理 stub。
非导出函数、设备专属不同地址、未知 ID 和 NULL 原样传递，不缓存为全局单一地址。
完整 Vulkan Layer 路径由 host 适配器复用 Core 现有 dispatch。

## 原件链与时序

配置严格检查 JSON schema。例：

```json
{
  "schemaVersion":1,
  "provider":{"kind":"absolute","path":"D:\\wrappers\\next.dll"},
  "activation":"first-call",
  "enableDefault":true,
  "plugins":[{"path":"owned_plugin.asi"}]
}
```

provider 支持 `system`（System32 basename）、`sibling`（同目录改名原件）、`absolute`
（本地或 UNC 完整路径）。相对路径只接受 basename；子目录使用完整路径。
可固定小写 `sha256`，编译时检查绝对 provider 的接口及哈希，运行时检查文件哈希、
文件身份、解析后的函数地址。生成器之间按下一层路径元数据检查循环，深度最多 32。
第三方没有这份元数据时，无法承诺发现其内部隐藏的任意循环。

默认系统槽包括 DXGI/D3D、OpenGL、winmm、version、winhttp/wininet、dinput8、dsound。
其他槽默认同目录改名原件。`--original` 显式选择 sibling；`--copy-original` 只适用 sibling。
默认原件固定输入 SHA256；显式空哈希表示不固定，仍检查自加载。
插件为显式列表，按顺序加载，先 Core 再插件，不扫描未知 DLL。

Aftermath 的 basename 与 GFSDK 导出共同用于自动识别，默认原件名为
`GFSDK_Aftermath_Lib_orig.dll`，另尝试 `GFSDK_Aftermath_Lib.x64.orig.dll`、
`GFSDK_Aftermath_Lib_orig.x64.dll`。只在文件不存在时尝试下一项；已有文件的哈希、依赖、
循环或契约失败不会被另一个文件掩盖。显式 `--original`/provider 禁用默认备选，
也可显式提供 sibling 的 `alternates` basename 列表；每一项使用同一输入哈希。
DATA/linker forwarder 不能实现备选文件，需显式选择单一原件。

启动策略由加载槽决定，与查询分发协议分别处理。SDK/普通加载槽（generic、Aftermath、
NGX、NVAPI，以及 version/winmm/winhttp 等）默认 worker；图形 provider（DXGI/D3D/OpenGL、
Streamline、Vulkan、Agility）默认 first-call。Aftermath 即使显式使用旧 streamline profile，
仍按 SDK 加载槽选择 worker；`--route streamline-bootstrap` 也默认 worker。
显式 `activation` 覆盖默认值。receipt 记录 `activationSelection` 和实际选择。

|activation|时序与边界|
|---|---|
|first-call（图形 provider 默认）|首次代理函数调用前握手；该调用须在 loader lock 外并早于待捕获对象创建|
|export|仅 `activateExports` 命中时激活，其余导出此前正常转发|
|entry-point|可选 EXE 入口一次性 INT3/VEH gate；恢复原字节和页保护，拒绝已有 INT3，仅适用于启动期加载，须按目标验证|
|worker（SDK/普通加载槽默认）|DLL 加载后启动 Core，与 SDK 是否调用无关；原件仍惰性解析；不保证早于设备创建|
|module-load|`watchModules` 全部出现后激活；通知只 SetEvent，worker 完成加载，不保证赶在模块 DllMain/设备创建之前|
|manual|宿主调用 `DCompProxyInitialize`，适合已有插件/启动回调|

`DCOMP_BOOTSTRAP_ENABLE=0` 明确关闭；`1`、`enableDefault:true` 或同目录
`dgcore.enable` 启用。`--core` 验证并复制 x64 DCOMP Core，`--enable-core` 创建 marker。
Core 缺失/握手失败默认保留原件转发；`requireCore:true` 可要求失败即停止。
requireCore 在每次物理函数转发前保证 Core 初始化，优先于延迟/manual 模式；不拦截 DATA/linker forwarder。
GetAPI 握手使用进程 mutex 串行化，原件及插件使用 InitOnce。不得卸载正在使用的代理。
除 export 模式保留每次调用的触发检查外，完成原件解析和所需启动门槛后发布 ASM 快路径。
Core/插件初始化中的重入只转发原件，不提前发布快路径；requireCore 外部调用等待插件初始化完成。
启动 worker 失败会记录状态/错误，不把线程创建失败当作成功。

除原始名字、ordinal-only 和别名外，统一运行时增加五个控制导出：
`DCompProxyInitialize`、`DCompProxyGetState`、`DCompProxyGetLastError`、
`DCompProxyNextProvider`、`DCompProxyCheckProvider`。
State：0 未激活、1 初始化中、2 Core 就绪、3 关闭、4 加载失败、5 握手失败。
Initialize 在 Core 或插件失败时返回 0。CheckProvider 检查原件及解析目标，须在 loader lock 外调用。
状态 2 只代表 API 握手，不能当成捕获成功。

## DATA 与另一种转发架构

未知/非执行区导出默认拒绝，须逐个声明：

```json
{
  "provider":{"kind":"sibling","path":"d3d12_orig.dll"},
  "dataExports":{"D3D12DeviceRemovedExtendedData":{"type":"opaque-address"}},
  "activation":"first-call"
}
```

类型为 `uint32`、`uint64`、`pointer`、`opaque-address`。前三者检查可用字节数；
最后一个是调用方明确声明的原地址契约，不推断大小或语义。
DATA 通过 PE forwarder 指向原件存储，保留 GetProcAddress、静态导入和共享写入。
单独生成并验证 DATA 类型 `.lib`，不复制变量初值，也不制造函数 stub。
原件须为 sibling 并可由正常 loader 搜索路径找到，例如与程序 exe 同目录。
纯 DATA 导入可能在代理 DllMain 之前加载原件，不能保证 Core 更早启动。
raw EAT 调用方须识别 DATA forwarder，不能把 forwarder 字符串当地址。
DATA/linker forwarder 由 loader 直接解析，纯转发调用不会经过本运行时的 provider 哈希或时序 gate。
可在宿主启动回调中调用 CheckProvider 检查原件，编译交付时仍验证原件复制哈希。

`forwarding:"linker"` 将全部导出生成 PE forwarder，供标准 loader 场景使用。
需 sibling 和 worker/entry-point/manual 激活；不能用于忽略 forwarder 的 raw EAT 调用方。
默认 `physical` stub 保留 x64 整数、浮点、栈参数和调用方返回地址，不推断未知函数签名。

## 宿主适配器

```powershell
proxy-builder.exe host asi --core D:\DComp\dgcore.dll --output D:\build\asi
proxy-builder.exe host jvm --core D:\DComp\dgcore.dll --output D:\build\jvm --jdk "C:\Program Files\Java\jdk-25.0.2"
proxy-builder.exe host openxr --core D:\DComp\dgcore.dll --output D:\build\openxr
proxy-builder.exe host vulkan-layer --core D:\DComp\dgcore.dll --output D:\build\vulkan
```

- ASI：生成 DLL 及同字节 `.asi`，供现有 ASI Loader 加载，默认 worker。
- JVM：生成 native bridge 和 `dcomp-bootstrap.jar`。`-javaagent:完整jar路径` 在 premain
  加载同目录 bridge、同步握手并 pin DLL；agent 参数可指定其他完整 DLL 路径。
- OpenXR：生成 DLL/显式 Layer JSON。协商时激活 Core，维护每个 instance/session 的
  下层 dispatch，遍历完整 pNext 查找 D3D11/D3D12/Vulkan/Win32 OpenGL binding。
  xrBeginFrame/xrEndFrame 限定应用帧，仅结束本 layer 拥有的捕获，不替其他 session 结束。
  `captureFirstFrame` 默认 0，`captureFrameCount` 默认 1。目录加入 `XR_API_LAYER_PATH`，
  名字 `XR_APILAYER_DCOMP_capture` 加入 `XR_ENABLE_API_LAYERS`。
- Vulkan Layer：生成薄桥接和 Core manifest，转发协商/查询到 Core 已有 Vulkan Layer。
  目录加入 `VK_LAYER_PATH` 并启用 `VK_LAYER_DCOMP_Capture`，不要重复启用同名 Core layer。

命令不注册系统 layer、不改变全局环境、不运行游戏。OpenXR 协商早于 session，
不保证早于应用此前创建的图形设备。所有桥接使用 DCOMP API。
Khronos 头文件固定版本，附 LICENSE/PROVENANCE；其余实现为本项目代码。

## 验收

保存 exports.json、build-result.json、日志、源码、头文件。输入、生成文件、Core/provider 复制、
DLL 和 DATA 导入库绑定 SHA256；编译失败或生成文件变化不能返回 verified。
verified 代表编译与契约验收；真实设备包装、捕获、回放和包装层组合须另行验证。

```powershell
python -m unittest discover -s tools/proxy-builder/tests -p test*.py
python tools/proxy-builder/tests/run_route_acceptance.py --output D:\route-acceptance --toolchain Both
pwsh -NoProfile -File tools/proxy-builder/tests/run_static_acceptance.ps1 -Python C:\Python312\python.exe -OutputDirectory D:\legacy-acceptance
```

自有进程覆盖双编译器、ABI/raw EAT、查询 NULL/未知值/不同 handle、DATA 动态/静态导入及
共享写入、工厂、指定导出/晚加载触发、插件顺序、哈希失败、链及循环、EXE 入口早于 main、
Java premain、OpenXR 多 instance/session 和 Vulkan Layer 协商。
0.4.1 增加纯加载而无 SDK 调用的激活、阻塞 Core 握手时 SDK 仍可转发、真实 Core 握手、
三个 Aftermath 改名、禁止用备选掩盖坏原件、requireCore 重入以及 Core/插件失败门槛。
原版 Aftermath 43-name union proxy 保持独立，不自动替换部署版本。
