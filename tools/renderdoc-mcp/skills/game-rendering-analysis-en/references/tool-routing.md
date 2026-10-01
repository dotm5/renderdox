# Tool routing

This is a decision guide, not a mandatory call sequence. Inspect `tools/list` schemas and `get_capabilities(sessionId=...)`; backend and stage support must be confirmed by actual results.

| Question | Tools | Evidence boundary |
|---|---|---|
| Which draws produce the subject? | find_actions, get_draw_evidence, locate_draws_at_pixel, visualize_draw_contribution | Keep depth/stencil failures; differences describe the selected output only. |
| Which draws reuse geometry? | group_related_draws, get_mesh, get_post_vs_data, get_constants | Candidates, not established object identities; transforms and instances matter. |
| Who writes/reads a resource? | get_resource_usage, trace_resource_flow, trace_output_dependencies | Recorded resource dependencies, not pixel-level or shader-internal causality. |
| What do texture channels mean? | preview_resources, view_texture, read_texture, sample_pixels | Propose hypotheses from previews; confirm with sampling code, values and experiments. |
| Which parameters and branches execute? | get_shader, get_constants, debug_shader, query_shader_trace | Reflection may lack semantics; stage support differs; inspect completion status. |
| Where do two pixels differ? | debug_pixel_pair, diff_shader_traces | Require identical bytecode and no active replacements. Unknown/truncated data cannot prove full equivalence. |
| What changes across frames? | create_capture_set, align_events, get_aligned_event, match_resources, diff_captures, track_constant_changes | EID/resource numbers are not identities; missing and many-to-one matches require review. |
| Can an internal effect be exposed/disabled? | replace_shader, restore_replacement, view_texture, read_texture, sample_pixels | The LLM must supply valid reconstructed/modified shader code; no built-in automatic DXBC-to-HLSL or arbitrary intermediate instrumentation. |
| What is expensive? | list_gpu_counters, profile_events, export_profile_report | Replay measurements; accumulated durations are not an execution timeline. Missing SDK placeholders are not valid measurements. |
| How is knowledge retained? | annotate_capture, list_annotations, get_artifact, export_analysis_bundle | The LLM authors annotations and explanations; exporting does not assign semantics. |

## Common mistakes

- Inspect `diff_event`'s `preStateMethod`: `same_event_with_action_omitted` omits the current action, while `previous_api_event` observes the preceding API event. These are different experiments; neither automatically isolates an internal shader branch.
- A shared shader hash does not prove a shared material; a shared geometry hash does not prove a shared instance.
- MRTs alone do not establish a wholly deferred lighting architecture. Inspect writes and consumers.
- A single pixel trace cannot explain the whole surface. Use representative pixels, images and, where needed, changed parameters or views.
- Untyped DXBC raw unions need instruction-specific interpretation; choosing an arbitrary numerical interpretation does not establish equivalence.

Get atomic evidence with `get_draw_evidence`, then use `batch_query` projections to limit large JSON. Wait for jobs to finish. Native timeouts/cancellation do not necessarily mean execution has stopped.

`replace_shader` requires sessionId, eventId, stage and encoding; provide source or sourceFile and the actual entry point. Do not replace a six-target shader with a generic one-target material template.

An exposed native method is a capability claim, while a successful replay experiment is validation evidence. Keep the two distinct.
