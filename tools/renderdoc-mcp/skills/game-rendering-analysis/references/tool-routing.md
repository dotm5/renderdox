# 工具路由

这是决策路由，不是固定的工具调用流水线。先检查当前 `tools/list` 参数及 `get_capabilities(sessionId=...)`，原生 backend/stage 支持以调用结果为准。

| 问题 | 可用工具 | 结果边界 |
|---|---|---|
| 选定对象由哪些绘制产生？ | find_actions、get_draw_evidence、locate_draws_at_pixel、visualize_draw_contribution | 像素历史保留深度/模板失败；差分仅代表所选输出 |
| 哪些绘制复用几何？ | group_related_draws、get_mesh、get_post_vs_data、get_constants | 返回候选；实例和变换不同可能是不同对象 |
| 一张缓冲被谁写、被谁读？ | get_resource_usage、trace_resource_flow、trace_output_dependencies | API 记录的资源级依赖，不是像素/Shader 内部因果 |
| 纹理各通道有什么作用？ | preview_resources、view_texture、read_texture、sample_pixels | 看图提出假设，用采样代码/数值/实验确认；PNG 是预览 |
| 参数和实际执行分支？ | get_shader、get_constants、debug_shader、query_shader_trace | 反射缺少语义；Pixel/Vertex/Compute 能力不同；检查 completion |
| 两个像素在哪里不同？ | debug_pixel_pair、diff_shader_traces | 同字节码且无活动替换；Unknown 或截断不能证明完整等价 |
| 不同状态/帧是否一致？ | create_capture_set、align_events、get_aligned_event、match_resources、diff_captures、track_constant_changes | 不以 EID/ResourceId 数字等同身份，缺失/多对一需人工决策 |
| 如何输出/关闭 Shader 内部项？ | replace_shader、restore_replacement、view_texture、read_texture、sample_pixels | LLM 提供合法的重建/修改 Shader；没有内置自动 DXBC→HLSL/中间量插桩器 |
| 开销和报告？ | list_gpu_counters、profile_events、export_profile_report | GPU 回放计数，累计值不是执行时间轴；缺失 SDK 不当作有效计数 |
| 积累与复查？ | annotate_capture、list_annotations、get_artifact、export_analysis_bundle | 注释由 LLM 写；导出器不会自动撰写文章或赋予语义 |

## 常见误判

- 检查 `diff_event` 的 `preStateMethod`：`same_event_with_action_omitted` 是省略当前动作的结果，`previous_api_event` 是前一 API 事件的状态；前者可以检查该动作的贡献，后者只是局部变化。二者都不能自动隔离某个 Shader 内部分支。
- 同一 Shader 哈希不代表一个材质；同一几何哈希不代表一个实例。
- MRT 存在不意味着全部光照在延迟 Pass 完成；检查写入色值的指令和下游消费。
- 单像素轨迹不足以解释整个表面，需要代表性像素、截图及可能的参数/视角变化。
- 当前无完整类型信息的 DXBC raw union 需要结合具体指令解释位模式，不能任选一种解释进行“等价比较”。

## 调用模式

`get_draw_evidence` 获取原子证据，然后按问题用 `batch_query` 的投影减少大 JSON。作业等待终态后再读产物；本地原生调用超时/取消不等于操作已经停止。

`replace_shader` 必填 sessionId、eventId、stage、encoding，源内容通过 source 或 sourceFile，entryPoint 来自实际 Shader。不要复制通用材质模板后直接替换六路输出的原 Shader。

原生支持某方法只表示底层入口存在；资料中的验收状态和当前调用成功是两种不同证据。
