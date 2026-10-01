# Capability audit — 2026-10-01

This is a dated audit of the 0.3.1 analysis baseline, not a promise that every current session supports every operation. The character investigation exercised 44 distinct tools across two D3D11 captures. Check current schemas, capabilities and actual results before relying on a backend feature.

## Implemented and exercised in the character investigation

Draw evidence and related-draw candidates; selected-output contributions and pixel history; texture previews, channels and numerical sampling; shader reflection/disassembly and constant buffers; post-VS geometry; resource usage/dependency traversal; pixel debugging and trace queries; cross-frame alignment and constant changes; counters and offline reports; annotations and evidence export.

These support most of the evidence collection and explanation needed for an illustrated article. They do not automatically establish semantic names or isolate internal material terms.

## Exposed, but not fully validated by this investigation

Shader replacement/restoration exists. A reconstructed character-shader baseline and internal effect ablations were not validated in this case. Debugging support differs by stage/backend. Capture Doctor reported unknown for evidence it did not observe; that is not a confirmed compatibility pass.

## Limitations and missing built-in operations

- Original HLSL recovery and automatic semantic naming are not available. The LLM must reconstruct and label code fidelity honestly.
- There is no general arbitrary-DXBC, full-frame intermediate instrumentation, nor a one-call baseline/variants/equivalence workflow.
- There is no generic constant-buffer override interface or automatic import of host-generated article assets into the managed evidence bundle.
- The observed trace comparison included untyped raw union values. Unknown/truncated values prevent a claim of full typed equivalence.
- Dependency traversal is resource-level and bounded; truncated graphs are incomplete. The case had no useful engine pass-marker ancestry.
- Missing Nsight Perf SDK counters were placeholders and must be excluded from performance conclusions.
- The evidence exporter had omitted nested capture attachments; the source fix and regression test address packaging completeness. Verify the deployed server version and exported archive before relying on it.

Conclusion: current tools provide a substantial evidence foundation, but do not fully automate or validate all article-style experiments. LLM-led reasoning and writing are the intended workflow; shader baselines, internal-effect ablations and unsupported evidence remain explicit validation tasks.
