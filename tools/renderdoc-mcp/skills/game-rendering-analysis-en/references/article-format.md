# Illustrated analysis format

The LLM writes the narrative. Start with the observed scene, survey scope and frame structure. Explain discovery signals and why selected mechanisms deserve deeper study, then organize chapters around discoveries rather than a fixed SSS/Bloom/LUT outline. Focused requests preserve necessary upstream/downstream context. Candidate notes may record signals, research value, pass/EID, resources/shaders and investigation status, including valuable deferred items. Do not require a census of common effects or equate unexamined with absent. Finish with evidence gaps and review links. Do not dump tool responses or follow EID order mechanically.

An effect chapter should connect:

- the visible phenomenon and the question;
- inputs, texture channels, constants and relevant draws;
- the algorithm, with HLSL marked as original, validated equivalent or explanatory pseudocode;
- intermediate images and controlled comparisons when actually available;
- the conclusion, supporting evidence and remaining uncertainty.

Every image needs a purpose, caption and capture/event/resource/subresource provenance. State whether it is a preview, numerical export, intermediate visualization or display-mapped final output. Record channel selection, remapping and encoding when they affect interpretation. Missing figures remain missing evidence; do not fabricate a fixed image quota.

Keep facts, inferences, approximations and unknowns visibly distinct. Code should explain the relevant data flow and use evidence-backed names; original variable names are unavailable unless source really exists. Cite disassembly ranges, bindings or constant offsets for inferred meanings.

The host writes prose, code and generated figures into a durable directory with relative links and a provenance manifest. `export_analysis_bundle` packages MCP-managed evidence and annotations; it does not automatically import arbitrary host-created article assets. Include those separately and validate that the final archive has no broken links or missing referenced files.

The requested style reference is the [user-provided rendering breakdown](https://zhuanlan.zhihu.com/p/2013370672647268314). Treat it as a presentation and reasoning reference, not evidence that the current game uses the same implementation.
