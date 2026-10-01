# 工程工具 0.3.1 实现与验收（2026-10-01）

本轮优先完成 Proxy Builder 一条命令生成 DLL，补充累计性能测量视图及有文件证据的 Capture Doctor。源码与便携包编译、静态检查、自有原生转发、现有真实游戏 RDC 回放已通过。新生成的 Aftermath DLL 尚未替换到游戏并验证。

## Proxy Builder

交付 `proxy-builder.exe`，使用者无需 Python，编译仍需 Visual Studio C++/MASM。自动发现 MSBuild，支持 MSVC/ClangCL。`build` 一次完成读取 PE、生成现有模板、编译和导出契约验收，返回 DLL 路径并保存 `exports.json`、`build-result.json`、`build.log`。生成的工程自带头文件，可移出仓库再次编译。

```powershell
proxy-builder.exe build "D:\original\vendor.dll" --output "D:\proxy-output\vendor" --copy-original
proxy-builder.exe build "D:\original\GFSDK_Aftermath_Lib.x64.dll" --output "D:\proxy-output\aftermath" --route streamline-bootstrap --original GFSDK_Aftermath_Lib_orig.dll --copy-original --core "D:\DComp\dgcore.dll" --enable-core
```

原 DLL 保持只读，复制改名原件和 Core 为可选项，启用 marker 也必须显式请求。已经有内容的输出目录拒绝覆盖；输出文件名与 Core 冲突时在写入前拒绝。输入、生成源码/头文件、工具和产物均记录哈希。

路径分为 system-dll、app-local、streamline-bootstrap。后两者复用 Aftermath 的 sibling-original 转发及独立线程 Core 激活。PE 导出表本身不能证明应用使用了 Streamline，因此 auto 不作此推断。

[#3257](https://github.com/baldurk/renderdoc/issues/3257) 记录了 sl.interposer 读取 EAT 后直接调用、跳过 IAT/GetProcAddress hooks 的路径。本地 Core 的 `renderdoc/os/win32/win32_hook.cpp` 有 inline/topmost-provider 接入代码。自动代理的物理导出 stub、Core 激活和图形 API 接入是分别验收的步骤：本轮 raw-eat 自建测试不用 GetProcAddress 取得被调用导出，验证整数/浮点/ordinal/别名/forwarder 转发；不据此声称完整 Streamline 游戏接入通过。

原版 Aftermath 43-name union 部署不变。新生成器按指定原 DLL 的精确导出及 ordinal 制作。x64 函数导出受支持，数据/未知导出明确拒绝。当前 System32 D3D12 的数据导出仍属于这一限制。

## 性能报告

新增指标排行/事件顺序累计测量切换。消费已有完整 counters 和事件树，支持名称、marker 路径、EID 范围过滤、分页和事件详情。累计值随过滤重算，只累加有效非负叶事件值；父 marker 不重复计算。未知值、非有限值及超过 JavaScript 精度的整数不冒充数值累计。

这是一条按 EID 排列的测量累计轴，未测量 GPU 的真实起止时间、并行或间隙。它不能当作完整 GPU frame timeline。

真实 Strinova RDC 的 595 个事件已在新编译包里回放，生成新版 HTML；浏览器对照 counter 总和验证累计值，筛选后归零、详情、分页与 marker 聚合均通过，控制台无错误/警告。原 RDC SHA256 为 `3476077eb01c207744f468a13c080f86936e01cf826f39656f4b06dba15f21cb`，是上一轮绑定 PID 4092 的捕获，并非本轮新帧。

## Capture Doctor

创建顺序矩阵升级为 schemaVersion 2，绑定 EXE、Core、JSONL、各 RDC 的哈希与字节大小。`capture_doctor(orderMatrixPath=...)` 核对当前包 Core、原文件、事件/报告一致、阶段顺序、HRESULT 成功标记、终态及捕获文件数量，返回独立 `orderMatrixEvidence`。样例里的加载/创建/Present/捕获状态不填入所选游戏的对象包装字段。

当前 Core 自建样本：提前加载捕获成功；Factory 后加载创建交换链返回 `0x80004002`；交换链后加载 Present 成功但无捕获。它是已确认的边界，不是已修复的 late-loading 兼容性。

## 验收和产物

- 单元测试 26 项通过，包括变更/篡改、错误顺序、Core 不匹配与失败状态。
- 最终源码 MSVC、ClangCL 自动编译生成 fixture/DXGI/D3D11，导出契约通过；D3D12 数据导出明确拒绝。
- 两编译器普通/raw-EAT、Core disabled/enabled-missing 共 512,000 次调用，错误 0。
- 冻结 Builder EXE 从 C:\Windows 工作目录生成中文路径代理，额外 raw EAT 64,000 次调用，错误 0。
- 冻结 Builder 已制作真实 Aftermath DLL、改名原件、Core 与启用 marker；记录保存在产物中的 build-result.json。
- 冻结 MCP 0.3.1 的真实 RDC 回放、Pixel Diff 正例、报告、带矩阵的 Doctor、证据包导出通过。
- 当前 Core 原哈希保持 `3656F785307A3209ED13820C3024ED2B1CA16EAEE685035223E53C2E1397848F`，未改编其 native hook 路径。

产物根目录：`D:\rdoc-port\artifacts\infrastructure-031-20261001`。
独立 Builder：`Proxy-Builder-0.3.1-windows-x64.zip`；整套 MCP：`DComp-MCP-0.3.1-windows-x64.zip`。
机器验收：`ACCEPTANCE.json`；自动生成 Aftermath：`Aftermath-待运行时验证\bin\Release`。

当前未检测到 Strinova 进程；新代理的真实游戏/Streamline 验证待开启新实例后执行。本轮没有修改游戏部署，没有 commit/push。旧原件及旧交付包保留，临时浏览器/HTTP/MCP 验收进程已退出。
