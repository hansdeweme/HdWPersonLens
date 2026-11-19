# PersonLens Persons Workbench — v0.7.1 Collection-Level KB Assessment (preview)

## Scope

This is an explicitly launched, read-only **Analyze KB Collection** panel. It summarizes a person's current KB image list, pixel-level sharpness, dimensions, unreadable images, and possible exact or near-duplicates. It does not detect faces, verify identity, modify KB files or preferences, alter encodings, or invoke dlib.

Duplicate grouping mirrors `kb_gallery_optimizer.py`:

- Exact SHA-256 digest; or
- Perceptual 64-bit dHash Hamming distance at most 4, with aspect-ratio difference at most 0.03.

Possible duplicate representatives are ranked by sharpness and resolution, **not** identity evidence. “No duplicate found” does not imply a good encoding reference. The assessment is capped at the first 250 supplied images and explicitly indicates truncation.

## Integration

Add `kb_collection_assessment.py` and `person_kb_collection.py` to the `hdw_person_lens` package. The supplied `persons_workbench.py` shows the integration, but the current committed v0.6.1 files have not been supplied in this session. **Merge the following four changes into your actual v0.6.1 source rather than overwriting unrelated local fixes:**

1. `from .person_kb_collection import PersonKBCollectionPanel`
2. After adding `self.gallery` to `detail_layout`: `self.collection = PersonKBCollectionPanel(self); detail_layout.addWidget(self.collection)`
3. In selected-person details, reuse the existing KB paths: `self.collection.set_person(name, kb_paths)`; when clearing: `self.collection.set_person("", [])`.
4. In `shutdown_portraits()`, call `self.collection.shutdown()` before the portrait/gallery shutdown logic.

The panel has a dedicated one-worker `QThreadPool`. Each collection scan occurs in a disposable Python process. A person change invalidates stale results and kills the old scan; shutdown cancels queued work, terminates active scans, waits for the worker, and reaps the child. Failures are reported in the panel.

## Windows checks

1. Analyze KBs with 0, 1, 20 and 250+ images. Check progress and truncation.
2. Use identical files with different filenames: verify one is identified as a possible duplicate.
3. Use visually similar resized images and unrelated images: check grouping against optimizer output.
4. Include corrupt and removed files. They should appear as unreadable, without aborting other results.
5. Switch people or start a new scan while another runs. Old results must not appear and no stale worker may delay the new scan indefinitely.
6. Force a subprocess launch failure, crash, and timeout; verify recovery on the next scan.
7. Quit while scanning. Confirm active children are terminated and reaped.
8. Confirm KB images, portrait cache, preference files and encoding banks remain byte-for-byte unchanged.

## Verification in development environment

Six focused standard-library tests passed (three collection tests and three face-preview protocol tests). Syntax compilation passed. Native Windows Qt integration and the full optimizer implementation have not been exercised here.
