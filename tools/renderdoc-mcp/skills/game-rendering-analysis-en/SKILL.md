---
name: game-rendering-analysis-en
description: Survey game captures with RenderDoc MCP and let the LLM proactively discover interesting, specialized or reusable rendering mechanisms, select candidates for investigation, and explain them with images and evidence-labelled HLSL. Support user-requested focused investigations. Use for rendering breakdowns and technical-art research.
---

# Evidence-backed game rendering analysis

The LLM owns grouping, interpretation, experimentation and writing. MCP supplies inspectable replay data and artifacts. Do not treat tool output as an automatically generated explanation.

## Default mode: heuristic discovery

**By default, proactively discover interesting, specialized or reusable rendering ideas in the capture and choose valuable candidates for deeper investigation.** Do not wait for users to name components. Do not restrict discovery to predefined effects or require detailed analysis of every ordinary pass. Prioritize explicitly requested components when provided. A character example may still lead into relevant scene lighting and post-processing.

Start with a coarse overview of events, outputs and resource relationships. The following are illustrative discovery directions, not required checks, classification boundaries or eligibility rules for deeper analysis:

- Lighting/surface: SSS/transmission, special shadows, AO, reflections, nonstandard BRDFs, toon shading, MatCap and outlines.
- Geometry/space: vertex displacement, tessellation, parallax/POM, unusual skinning/deformation; distinguish geometry changes from UV/normal effects.
- Material layers: wetness, droplets, snow, dissolve, decals, transparency/refraction, emission and other special layers.
- Post-processing: Bloom, depth of field, motion blur, antialiasing, exposure, tone mapping, grading LUTs, color encoding and final display conversion.
- Supporting mechanisms: depth/normal intermediates, light lists, shadow maps and cross-pass composition.

Look for distinctive signals: unusual resource formats/dimensions/arrays, nonstandard buffer reuse, recurring sampling/computation patterns, unexpected blend/depth states, geometry changes, localized visual features and cross-pass data transfers. A familiar pass name can hide an unusual implementation. Describe unnamed mechanisms from evidence rather than forcing them into a known effect category.

Keep iterative candidate notes with discovery signals, evidence anchors, possible mechanisms, research value and validation questions. Select depth by visual contribution, implementation distinctiveness, reuse value and available evidence. The LLM decides priorities without a fixed number or effect list; new discoveries can redirect investigation. Retain valuable deferred candidates and reasons, and do not claim an exhaustive census. Keep collection bounded, batched and deduplicated rather than debugging every draw and pixel.

## Start with a frame survey

Record capture/session identity, API, frame, scene and explicit scope restrictions. Check `get_capabilities` and current tool schemas. Trace backward from final output and combine event order, resource producers/consumers, shader families and image contributions to discover candidates. Turn discoveries into observable questions, such as how an unusual lookup, deformation or multipass composition produces a visual feature. Select representative draws and pixels. A focused request may begin at the named component. Wait for jobs to reach a terminal state before reading artifacts.

Load references progressively through relative files, MCP resources, or `get_analysis_skill(name="game-rendering-analysis-en", path=...)`:

- [Tool routing](references/tool-routing.md) when selecting evidence tools.
- [Replay experiments](references/replay-experiments.md) before shader reconstruction or ablation.
- [Article format](references/article-format.md) when preparing the illustrated explanation.
- [Capability audit](references/capability-audit.md) when assessing coverage and limitations. It is a dated snapshot, not a live capability guarantee.

## Build the explanation

1. Locate the subject using selected-output contribution, pixel history, geometry and resource evidence. Failed depth/stencil fragments are evidence too. A screenshot resemblance alone does not establish identity.
2. Group at two levels: related geometry draws (body, face, outline, accessories) and effects implemented inside a shader (base shading, wetness, droplets, highlights). Shader reuse is not material identity, and geometry reuse is not instance identity. Keep unrelated lights/background draws separate.
3. Trace inputs to outputs: textures and channels, samplers, constant-buffer offsets and values, spaces, branches, instruction ranges, render targets, blending and downstream consumers. Sample numerical values alongside previews. Determine what executes at representative pixels.
4. Form a hypothesis, state what would distinguish it from alternatives, and request the smallest useful experiment. Use another frame or view when a single pixel cannot resolve the question.
5. Write HLSL with explicit fidelity: original source when actually available; validated equivalent only after a matching baseline; explanatory pseudocode otherwise. DXBC disassembly is not original HLSL. Preserve actual signatures, matrix conventions, numeric types, samplers, MRTs, discard and depth behavior in any replay candidate.
6. Run necessary offline experiments with a verified baseline first. A shader resource replacement affects every draw using that resource. Restore replacements even after errors. Compilation success is not visual or numerical equivalence.
7. Accumulate bounded semantic notes using `annotate_capture`, including capture identity, EIDs, resource IDs, hypotheses, evidence and unresolved questions. Do not reuse old EID meanings across captures without alignment.
8. Produce the article in the host: frame overview, discovery and selection rationale, deeper explanations of selected mechanisms, figures, HLSL and provenance. Keep unresolved results and valuable deferred candidates explicit. Export original MCP evidence with `export_analysis_bundle`; it does not author the article or automatically import host-generated files.

## Layered-effect reasoning

For a wet-skin investigation, test a possible chain such as branch/time/UV → coverage → normal → AO/roughness → specular response → composition. This is a checklist of questions, not a claim about the game's implementation. Separate geometry overlays from material-internal overlays using bindings, instructions and controlled replay evidence.

Use labels consistently: **Observed**, **Validated equivalent**, **Inference**, **Unknown**, **Approximation**. A useful conclusion explains the observed image, identifies supporting code/data, and states the remaining uncertainty.

## Completion

Default investigations describe survey scope, discovery signals, chosen mechanisms and selection reasons, plus valuable deferred candidates and evidence gaps. Fixed-category coverage is not a completion criterion. Focused investigations answer the requested scope with necessary upstream/downstream context.

Each central claim must have a traceable capture/event/resource or experiment. Each image must explain its purpose and sampling/preview conditions. Do not invent unavailable figures, original variable names or parameter semantics. Explicitly list missing evidence and unsuccessful experiments rather than presenting them as complete coverage.

Examples:

- “Analyze this capture's rendering”: survey broadly, discover worthwhile mechanisms from actual evidence, choose deeper investigations autonomously and deliver illustrated explanations with fidelity-labelled HLSL.
- “Explain this character's skin”: locate body draws, separate base shading from internal layers, inspect channel usage and compare representative pixels before proposing HLSL.
- “Why do droplets brighten the skin?”: trace coverage and normal/roughness inputs, test competing explanations, and report unverified branches as hypotheses.
- “Write a illustrated breakdown”: organize the observed frame first, then effect chapters with evidence, code fidelity and controlled comparisons; use the article reference.
