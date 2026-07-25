# Action Visibility validation

## Result

Status: **PASS**

- Development x64 v143 solution build: pass.
- C++ unit tests: 2 cases, 27 assertions, pass.
- Owned replay scenarios: 13/13 pass.
- Source RDC SHA-256 before/after each run: unchanged.
- Enabling after a disable: exact output hash restored in every mutating scenario.
- Unsupported indirect/multi-action IDs: rejected.
- Default disabled set: empty.

## Scenario matrix

| API | Scenario | Coverage | Result |
| --- | --- | --- | --- |
| D3D11 | Simple Triangle | direct draw, color output, restore | pass |
| D3D11 | Draw Zoo | indexed/non-indexed and varied draw forms | pass |
| D3D11 | Action Visibility Dispatch | direct dispatch and UAV/buffer observation | pass |
| D3D11 | Stream Out | stream-output side-effect observation | pass |
| D3D12 | Simple Triangle | direct draw, color output, restore | pass |
| D3D12 | Draw Zoo | indexed/non-indexed and varied draw forms | pass |
| D3D12 | Compute Only | direct dispatch and UAV output | pass |
| D3D12 | Execute Indirect | parent/child rejection | pass |
| D3D12 | Vertex UAV | five-draw batch, UAV-visible final change | pass |
| Vulkan | Simple Triangle | direct draw, color output, restore | pass |
| Vulkan | Draw Zoo | indexed/non-indexed and varied draw forms | pass |
| Vulkan | Indirect | indirect rejection plus safe direct draw | pass |
| Vulkan | Groupshared | direct dispatch and storage output | pass |

The D3D12 Vertex UAV case intentionally disables all five identical full-overwrite draws. Disabling
one earlier draw does not change the final image because a later draw overwrites it; the batch test
proves multi-selection without misclassifying that expected overwrite as a failure.

## Assertions made by the replay harness

For every capture, the harness:

1. hashes the source RDC;
2. opens it through the built Development replay module;
3. discovers eligible and protected actions from current action metadata;
4. submits duplicate, stale, indirect, and multi-action IDs where applicable;
5. checks the exact accepted set returned by `SetDisabledActions`;
6. hashes every observable bound color/depth/UAV texture or buffer;
7. forces replay with the disabled set and verifies the expected change;
8. clears the set, forces replay again, and verifies exact restoration;
9. re-hashes the source RDC;
10. records debug messages and per-step timings.

## Evidence

Generated evidence is intentionally external to Git:

- `audit/followup/action-visibility/captures-final/capture-manifest.json`
- `audit/followup/action-visibility/results-final/summary.json`
- `audit/followup/action-visibility/results-final/<case>/result.json`
- `audit/followup/action-visibility-development-ui-tests-build.log`
- `audit/followup/action-visibility-unit-tests.log`

The committed, rerunnable harness is in `tools/action-visibility/`.

## Known fixture issue

The upstream `VK_Compute_Only` functional fixture produced a capture that replayed as an empty D3D12
capture and then failed while looking up resource `tex`, including when run alone. It is not counted
as Vulkan dispatch evidence. The independent `VK_Groupshared` functional fixture passed and is the
Vulkan dispatch proof. This is classified as an upstream/harness fixture issue, not hidden as an
Action Visibility pass.

## Donor comparison

Primary donor intent: `Renderdoc-ue56` commit
`7ae99f5e53341a9a2b825f67b823a11c33ea4be1`, with batch UI context from
`140d1ba214be32b159317233d680561bd1bd6793`.

The donor skips using the EID returned by `HandlePreCallback()`. Ordinary replay has no action
callback, so this can resolve to EID zero. The new implementation uses the current D3D11 replay EID
or D3D12/Vulkan chunk-to-`ActionUse` mapping and never copies the donor's `skipState` model.

## Rollback

Runtime rollback is immediate: clear the disabled set or reopen the capture. Source rollback is
confined to the two Action Visibility commits and requires no capture conversion.
