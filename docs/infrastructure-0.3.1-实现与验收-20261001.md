# 工程工具 0.3.1 历史实现与后续状态

原始记录日期：2026-10-01。状态核对日期：2026-10-22。
当前实现见 [实现状态](current-status.md)。

## 历史交付

0.3.1 增加一条命令生成、编译和验证代理的 Builder CLI、性能报告累计测量视图，
以及按文件哈希核验的 Capture Doctor 创建顺序证据。历史测试记录为 26 项 Python
测试、两种编译器合计 512,000 次转发及冻结 Builder 的 64,000 次 raw EAT 调用。
历史 RDC 回放和报告测试使用已有捕获。

## 当前结论

| 项 | 当前结果 | 说明 |
| --- | --- | --- |
| 数据/未知导出全部拒绝 | 限定为旧模板入口；统一运行时接受显式 DATA 契约 | 参见 Proxy Builder ROUTES.md |
| Aftermath 生成器 | 已迭代至 0.4.1 | auto 识别 aftermath；SDK 加载槽默认 worker；原件与 Core 启动分别初始化 |
| Capture Doctor 创建顺序 | 已完成历史样例运行并提供 schemaVersion 2 | EXE、Core、JSONL、RDC 均核验；结果独立于所选应用 |
| 原生 Core 保持原版不变 | 后续已集成 v1.46 和 DX12 closure 修复 | 当前设备/factory 包装行为按当前源码读取 |
| 嵌套捕获附件 | 0.3.2 已修复导出收集 | 当前便携构建和回归测试已包含 |
| 独立工程工具包 | 当前集成在完整 Windows Release | MSVC、ClangCL 均带 MCP、Builder 和顺序样例 |

## 性能报告语义

指标排行和事件顺序累计测量视图消费已有 counter 与事件树，支持名称、marker、EID
范围过滤、分页和详情。累计值随过滤重算，仅累加有效非负叶事件值。父 marker 保留
结构信息；未知值、非有限值和超出 JavaScript 精度的整数保留其明确表示。

累计轴表示按 EID 汇总的回放测量值。GPU 的并行执行、间隙和真实起止时间需要对应
的时序采样。counter 的来源和单位保存在报告中。

## 创建顺序的历史测量

2026-10-01 当时 Core 的 early 样例捕获并回放成功；after-factory 返回
`0x80004002`；after-swapchain Present 成功、捕获数为 0。
当前 Core 已有后续修改，新的顺序结论须由与其哈希匹配的矩阵提供。
详见 [Capture Doctor](../tools/capture-doctor/README.md)。
