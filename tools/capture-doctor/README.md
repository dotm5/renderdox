# Capture Doctor 与 D3D12 创建顺序样例

MCP `capture_doctor` 接受 `connectionId`、`captureId` 或 `sessionId`，返回独立的
控制连接、图形 API、捕获收集和回放状态。公共控制 API 无法证明模块加载和对象包装
顺序，因此 factory/device/queue/swapchain/Present 观测保持 `unknown`。
诊断不会修改目标、触发捕获或自动重试。

已有 Capture Health Checker 的 JSON 可通过 `healthReportPath` 传入，或提供服务中
已注册的 `healthArtifactId`。必须按捕获 SHA256 匹配；回放打开不冒充完整健康检查。

自有样例 `d3d12-order.exe` 显式在指定阶段加载传入 Core，记录创建对象、Present、
捕获结果和终态。支持 baseline、early、after-factory、after-swapchain。
它不注入任何外部进程，窗口默认隐藏。晚接入失败是待测结果，脚本不预设所有阶段成功。

```powershell
MSBuild d3d12_order.vcxproj /p:Configuration=Release /p:Platform=x64
pwsh -NoProfile -File run_order_matrix.ps1 -Executable .\bin\Release\d3d12-order.exe -Core D:\DComp\dgcore.dll -OutputDirectory D:\order-results-new
```

结果绑定样例 EXE 和 Core 哈希，JSONL 记录 HRESULT，matrix.json 汇总四种顺序。
schemaVersion 2 的矩阵保存 EXE、Core、JSONL 和各 RDC 的 SHA256。
MCP `capture_doctor(orderMatrixPath="D:\\order-results-new\\matrix.json")` 可单独读取矩阵，
也可与捕获/连接一起传入。它核对原文件、Core 与当前包一致、阶段顺序、HRESULT、终态和 RDC 数量。
不一致或旧 schema 会拒绝。结果的 `orderMatrixEvidence` 独立呈现自有样例的加载、创建、Present、
开始/保存捕获状态，不填充当前游戏的对象包装状态，不把创建成功当成包装成功。

2026-10-01 的当前 Core 实测：early 捕获并回放成功；after-factory 创建交换链失败
`0x80004002`；after-swapchain Present 成功但捕获数为 0。两种编译器结果一致。
这是样例的创建顺序边界，不能代替包含 `sl.interposer` 的真实游戏验证。
