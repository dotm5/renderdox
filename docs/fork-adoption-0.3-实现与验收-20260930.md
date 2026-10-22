# MCP 0.3.0 历史实现与后续状态

原始记录日期：2026-09-30。状态核对日期：2026-10-22。
当前实现总表见 [实现状态](current-status.md)，操作入口见
[MCP 说明](../tools/renderdoc-mcp/README.md)。

## 历史交付

0.3.0 引入 Shader trace Diff、离线性能 HTML、Proxy Builder 和 Capture Doctor。
当时发布接口共 70 个；当前 0.3.2 增加两项分析文档入口，共 72 个。

历史验证包括 21 项 Python 测试、MSVC/ClangCL 代理编译、256,000 次 ABI 转发、
中文输出路径、旧 RDC 回放及 HTML 交互。以上数量保留 0.3.0 的测试范围。

## 后续结论

| 项 | 当前结果 | 说明 |
| --- | --- | --- |
| D3D12 数据导出被拒绝 | 统一运行时已支持显式 DATA 契约 | 0.4.0 引入 dataExports；旧 generate 模板仍保留拒绝行为 |
| 创建顺序 GPU 矩阵未运行 | 后续已运行并升级为 schemaVersion 2 | 历史 HRESULT 和捕获数量见 Capture Doctor 说明；新 Core 要绑定新矩阵 |
| Aftermath 激活依赖首次 SDK 调用 | 0.4.1 已改为独立 worker 默认启动 | 原件转发继续惰性解析 |
| 捕获附件导出遗漏 | 0.3.2 已修复并加入回归测试 | 当前便携构建收集嵌套 capture 附件 |
| 包含自有生成器和样例 | 当前 Windows Release 已随包发布 | developer-tools 内含 Builder、模板和 Capture Doctor 样例 |

## 保留的接口语义

`debug_shader` 默认预算为 16,384 步、32 MiB、30 秒；预算检查发生在原生批次之间。
`diff_shader_traces` 和 `debug_pixel_pair` 的首版比较要求 Pixel、相同字节码及无活动替换。
控制流分歧结束硬对齐；截断和 Unknown 值保留在结果中。

性能报告使用回放 counter；累计轴按事件顺序汇总有效叶事件值。
Capture Doctor 的样例观测放在 `orderMatrixEvidence`，目标进程的未观测字段保持 unknown。

## 按应用验证

新增或替换代理后，记录该应用的加载链、设备创建时序、捕获文件和回放结果。
此项验证按应用构建和 Core 哈希保存。生成器编译验收与该应用的运行结果分别记录。
