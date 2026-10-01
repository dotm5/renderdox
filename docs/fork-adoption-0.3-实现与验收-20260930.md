# 候选功能落地：MCP 0.3.0 实现与验收

2026-09-30。四个阶段的第一版已完成，编译与静态验收通过；新游戏实例运行时验证待执行。
本轮未 commit/push，保留工作区原有文档与 CI 修改。原生 Core 沿用已验证便携包，未修改或重新编译。

## 实现范围

| 阶段 | 交付内容 | 实际边界 |
| --- | --- | --- |
| Shader trace Diff | schemaVersion 2 轨迹、步数/大小/时间预算、保存轨迹比较、两事件顺序调试 | Pixel、相同字节码、无活动替换；控制流分叉后停止硬对齐；下一条指令不冒充写入指令 |
| HTML 报告 | GPU counter 完整结果、筛选/分页/Pass 层级/详情、证据包 HTML | 回放指标权重布局，非真实 GPU 时间轴；大整数精确保留，缺失指标不填零 |
| Proxy Builder | PE 只读解析、现有运行时模板生成、独立项目、导出契约检查、随包模板与头文件 | x64；数据/未知导出明确拒绝；生成契约不代表实际应用捕获成功 |
| Capture Doctor | 控制连接、收集、回放证据、SHA256 绑定 Health Checker、D3D12 创建顺序样例 | 公共 API 无法证明对象包装/Present 观测，保持 unknown；自有样例已编译，GPU 矩阵未运行 |

新增 MCP 工具为 `diff_shader_traces`、`debug_pixel_pair`、`export_profile_report`、`capture_doctor`，共 70 个。
`debug_shader` 默认 16,384 步、32 MiB、30 秒，预算在原生批次之间检查。
单次初始 Debug 和 ContinueDebug 调用不能强制中断，仍由 Worker 串行持有并最终释放原生 trace。
浮点阈值不用于整数；NaN 对 NaN 相等，Inf 须符号相同。失败与截断不报告完整一致。

## 验收结果

- 21 项 Python 测试通过：18 项 MCP 扩展、3 项生成器测试。
- MSVC / ClangCL 编译生成代理和 D3D12 样例通过。
- 两种工具链的 fixture、DXGI、D3D11 名称、ordinal、别名关系及架构契约通过。
- 每种工具链在 Core 关闭、Core 缺失两种条件下执行 16 线程、每组 64,000 次 ABI 转发；共 256,000 次，无错误。
- ordinal-only、forwarder、8 参数整数/浮点和别名地址一致性通过。
- 当前 System32 D3D12 的 `D3D12DeviceRemovedExtendedData` 位于非执行区，生成器明确拒绝，作为安全拒绝样例通过；没有对现有 D3D12 代理作数据导出修复。
- 便携包在其他工作目录及中文生成路径下完成 Proxy Builder 生成、编译与契约校验；包内 D3D12 样例源码可独立编译。
- 编译后的 MCP 0.3.0、70 工具发现、包内 Python 3.6 Worker、真实旧 RDC 离线回放通过；Vertex trace 18 步完整结束，性能报告和证据 HTML 成功导出。
- 浏览器验证分页、同名 Pass 区分、聚合不重复计数、文本/EID 筛选、详情与 64 位整数精确显示通过。最终性能报告浏览器控制台零错误/警告。
- Git diff 空白检查和 PowerShell 脚本语法检查通过。
- 221 个清单文件长度/哈希校验通过，ZIP 完整性检查通过。

旧 RDC 上选定的三个 Pixel 候选未返回调试器，保留 `unsupported` 结果。双轨迹比较器及工作流已通过有差异、无差异、分支和失败样例测试，但真实游戏 Pixel 调试与差异定位仍需新实例验证。

## 交付

便携包：`D:\rdoc-port\artifacts\fork-adoption-20260930\DComp-MCP-0.3.0-windows-x64.zip`

解压目录：`D:\rdoc-port\artifacts\fork-adoption-20260930\delivery\RenderDoc MCP`

原生 Core SHA256：`3656F785307A3209ED13820C3024ED2B1CA16EAEE685035223E53C2E1397848F`

ZIP SHA256：`B245AA4DEDF9D0F895E11496BE68B7D6C1C65D5950B2CEC2620A5CD378E6C565`

机器可读验收：`D:\rdoc-port\artifacts\fork-adoption-20260930\ACCEPTANCE.json`

编译证据：`native-release/results.json`、`packaging-release.log`、`portable-generator-verify.json`。
离线回归：`offline-release/results.json`。浏览器回归：`browser-acceptance.log`。

## 下一步运行时验证

先开启此前验证过的 Steam 版 Strinova，使用 DX11 和现有 Aftermath/Core 接入配置，进入稳定可操作场景。
MCP 使用上述 0.3.0 的 `renderdoc-mcp.exe serve --stdio`；重新发现目标，以本次 PID/连接和新 RDC 为准。

验证顺序：

1. Capture Doctor 检查控制连接、API、捕获收集及新 RDC 回放，保留对象包装未知项。
2. 在实际覆盖的像素和可调试 Pixel Shader 上采集两条轨迹，验证同事件自比较，再比较已知变化事件。
3. 验证截断状态、调试失败和比较后会话继续可用；原始 RDC 哈希保持一致。
4. 采集新 counter 报告，核对热点、Pass 和证据图像，不把 replay 数值当实时 FPS。
5. D3D12 创建顺序随后用包内自有样例单独运行四阶段矩阵，记录 HRESULT、捕获文件和回放结果。

没有执行新游戏注入、修改游戏 DLL、代理链部署或 D3D12 GPU 矩阵；这些运行时结果均为 Pending。
