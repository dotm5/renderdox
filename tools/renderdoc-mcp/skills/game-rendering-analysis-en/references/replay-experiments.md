# Controlled replay experiments

Only perform experiments that resolve a concrete question. Preserve the capture and record capture/session/event identity, original shader resource, replacement source/hash, compiler diagnostics and output conditions.

## Establish a baseline

Inspect input/output signatures, interpolation, resources and samplers, constant-buffer layouts, matrix conventions, numeric types, MRT writes, discard, depth and blending. Recovering readable code is not enough: reconstruct a baseline and compare its rendered and numerical outputs with the original under identical conditions.

Compilation success proves syntax and target compatibility, not equivalence. A baseline mismatch invalidates subsequent effect-removal conclusions. If reconstruction is incomplete, present code as explanatory pseudocode and keep replay claims pending.

## Vary one cause

After the baseline matches, expose or disable one intermediate at a time. Useful variants include coverage visualization, encoded normal output, isolated roughness/AO and individual lighting terms. Document altered output encoding and any behavior deliberately changed for visualization. Do not compare a linear intermediate preview directly with a display-mapped final image.

`replace_shader` replaces a shader resource, so all draws using that resource may change. Inspect sharing before interpreting a full-frame difference as an isolated material result. Read the result's installation status and diagnostics. Restore replacements in cleanup even on failure, or use separate sessions; close sessions when finished.

Use `view_texture` for previews and `read_texture`/`sample_pixels` for numerical evidence. There is no built-in baseline-plus-variants runner with equivalence thresholds: the host/LLM must organize artifacts and compute comparisons explicitly. Record pixel/region, subresource, format, normalization and tolerance. `diff_shader_traces` applies to matching bytecode without active replacements; it is not a generic comparison between original and reconstructed shader algorithms.

## Wet-effect checklist

Investigate branch activation, time dependence and UV generation; distinguish coverage from actual geometry; inspect how normal, AO/roughness and specular terms change; trace final composition. Choose representative wet/dry pixels and account for light/view direction. Confirm each inferred connection from code, values or a controlled variant. Do not assume every game uses the same wetness model.

Report failed baselines, unsupported debugging stages, incomplete typed traces and unavailable source separately. Do not fabricate successful ablations from static code inspection.
