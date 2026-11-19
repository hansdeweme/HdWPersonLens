# PersonLens v0.9.2 — Guided KB Assessment (preview)

Based on the four current modules uploaded after the verified v0.9.1 baseline (69 tests / 22 subtests). This change adds a **read-only guided workflow header** to the existing KB Assessment tab. It preserves all current worker, cancellation, freshness, native-process and shutdown implementations.

## New modules

- `kb_assessment_flow_state.py`: pure three-stage state machine with pending/running/complete/failed/stale transitions.
- `person_kb_assessment_workflow.py`: compact Qt workflow header with progress labels and a `Next Step` button.

## Existing modules updated

- `person_kb_collection.py`: new `assessment_started` and `assessment_failed` signals (ready and invalidated signals remain unchanged).
- `person_kb_identity.py`: matching lifecycle signals.
- `person_kb_recommendations.py`: new shortlist-ready, shortlist-invalidated and shortlist-failed signals; no ranking or thumbnail implementation changed.
- `persons_workbench.py`: instantiate the workflow above the existing assessment panels, and reset it on selected-person changes.

The workflow calls `collection.analyze()`, `identity.analyze()` and `recommendations.build()` in that order. It never starts work automatically when another step completes. All original buttons remain usable. Restarting an upstream step marks downstream workflow state stale. Reports still carry their own generation and freshness checks; this header is informational/navigation, **not** a replacement for source validation.

Active work is tracked separately from result validity. Invalidating a running downstream stage cannot enable Next Step early, and its obsolete completion remains stale. Running and all-complete states have distinct button/notice text. Terminal stale-source signals clear active tracking and return the guide to Collection. An explicit guided Collection restart reloads the current KB paths before launching work, including added or removed files. Shortlist computation errors are reported and can be retried without losing valid upstream reports.

No KB image, preference, portrait cache, encoding bank or schema file is modified.

## Install

The additions are merged into the current working sources, preserving the nested-tab lazy-loading fix, assessment cancellation tokens, source snapshots, process isolation, and thumbnail shutdown safeguards. Use these merged files rather than overwriting them with the original ZIP examples. Tests are under `tests/`, including the pure state policy and an offscreen Qt integration scenario.

## Windows validation

1. Open Assessment with no person and with a person having zero KB images; Next Step must be disabled.
2. Select a person with images: stages start pending, and Next Step launches only collection analysis.
3. While a stage runs, the guided button must be disabled. A completed collection enables Check Identity as the next action.
4. After identity completes, the next action builds the provisional/reference-review shortlist; ambiguous identity produces review-only output but still counts as an assessment result.
5. Run each panel's original manual button; the header must follow started/completed/failed/invalidation signals.
6. Rerun collection after finishing all steps; identity and shortlist should display stale until refreshed. Retry failed stages using Next Step.
7. Switch persons or refresh during native analysis. No stale completion should advance the new person's workflow.
8. Close with active analyses; confirm original shutdown order and child/process reaping remain correct.
9. Run all existing 69 regression tests and 22 malformed-input subtests, plus six new state-policy tests.

## Verification here

The combined regression suite passes 80 tests and 22 malformed-input subtests. Ten pure workflow tests plus one Windows offscreen Qt scenario cover guided order, no automatic advancement, concurrent manual reruns, accurate running/completed display, stale-source recovery, added-file discovery, failed-step retry, empty KBs, and person resets during active work.

A native step-by-step smoke test also passed using three disposable copies of one usable image: Collection completed without starting Identity; Identity completed without building a shortlist; a final explicit action completed the workflow. No source, preference, or portrait-cache files changed. The repeated-image fixture checks orchestration, not independent-image identity discrimination or recognition gains.
