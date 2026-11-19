# PersonLens v0.8.2 — Visual and Interactive Shortlist Comparison (preview)

This is an additive UI patch based on the three current modules uploaded after the v0.8.1 validation (67 regression tests and 22 malformed-input subtests). **Only `person_kb_recommendations.py` is changed.** The supplied backend modules are included as unmodified reference copies.

## New UI

- Two side-by-side image-card lists: **Quality-only baseline** and **Diversity-aware shortlist**.
- Each card shows its selection rank and filename. Candidates newly introduced by diversity ranking are labeled `+ variation`.
- A slider adjusts the quality/diversity blend from 100/0 to 30/70, defaulting to the existing `kb_gallery_diversity_weight` setting (35% diversity).
- A 120 ms debounce recalculates both rankings from already validated, in-memory reports; **no dlib, embedding extraction, or disk report writes** occur while moving the slider.
- Existing detailed table, rank explanations, and source/KB-membership freshness checks remain intact.

## Lifecycle and integration

Thumbnail decoding uses a dedicated two-thread `QThreadPool` and `QImageReader`. Results are converted to `QPixmap` only on the GUI thread. Jobs retain Python references until completion; changing the person cancels queued thumbnail work and discards stale results. The panel connects its `shutdown()` method to `QApplication.aboutToQuit` as a fallback.

For reliable earlier tab destruction, **also add `self.recommendations.shutdown()` to `PersonsWorkbench.shutdown_portraits()`**, before shutting down the other workers. The method is idempotent, cancels queued thumbnails, and waits for up to two running image readers. No new native-process lifecycle is introduced.

This hook is integrated into the current workbench. Thumbnail generations are also invalidated when assessment reports are cleared or replaced, so rerunning an assessment after replacing a file cannot reuse stale thumbnail pixels. Shutdown prevents further builds and debounce timers from restarting.

## Windows validation

1. Preserve and run all existing 67+ regression tests and 22 malformed-input cases.
2. Analyze a supported-person KB and build the shortlist. Both cards and the detail table should appear; no dlib should run during slider movement.
3. Set diversity weight to 0: both lists should match. At 35–60%, verify that genuinely different supported images may replace technically stronger near copies.
4. Try rapid slider dragging; check smooth response, no obsolete card images and no uncontrolled job growth.
5. Switch persons and refresh while card decoding is active. No old image or shortlist should appear.
6. Change KB membership or replace an image after analysis: slider change must trigger the existing stale-report block rather than rebuild from old data.
7. Close while 20+ card thumbnails are queued; no active gallery/preview/shortlist workers or child processes should remain.
8. Confirm source files, caches, preferences and encoding banks remain unchanged.

## Local verification

The combined regression suite passes 68 tests and 22 malformed-input subtests. Offscreen Windows Qt tests verify both visual rankings, variation labels, 0% agreement, a single debounced rebuild after rapid slider changes, and no process launches during weighting changes. They also verify changed-file invalidation, fresh pixels after reassessment, stale-result rejection, cancellation of 38 queued thumbnails while waiting for two active decoders, idempotent shutdown, and the actual workbench shutdown hook. Source-file hashes and timestamps remain unchanged during comparison and slider operations.
