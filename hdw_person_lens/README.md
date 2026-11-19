# PersonLens Persons Workbench — KB Quality Indicators v0.6 preview

## Install

Back up the current `hdw_person_lens/persons_workbench.py`. Copy both files into the `hdw_person_lens` Python package:

- `person_kb_gallery.py` (new)
- `persons_workbench.py` (replacement, based on the uploaded 19 November source)
- `face_crop_preview.py` (new, isolated native preview process and its runner)

Keep `person_portrait_service.py`, `portrait_process.py`, `portrait_worker.py`, `person_service.py`, `kb_faces.py` and `recognition_gui.py` unchanged. The immutable portrait-request snapshot and process lifecycle remain authoritative.

## Included functionality

- Embedded, scrollable KB reference-image gallery in the workbench details panel.
- Asynchronously decoded thumbnails using a dedicated `QThreadPool` (two workers) and `QImageReader`.
- Larger original-image preview for the selected KB reference, also decoded off the GUI thread.
- A separate 224px face-crop preview based on the same single-face and bounding-box geometry as the portrait pipeline.
- The crop is calculated in a disposable Python subprocess, never in the GUI or Qt decoder threads. Failure is displayed inline.
- Crop requests have their own one-worker queue; obsolete queued requests are cancelled on image/person changes.
- Selecting an image also computes the optimizer's sharpness, face-size and face-quality metrics in that same isolated analysis.
- Analyzed gallery items display a face-quality number (0–1) or detected face count; the selected-image details show full metrics.
- Analysis is on demand, not a background scan of every image. A heuristic score is **not** an identity check or an encoding recommendation.
- Preferred image highlighted by preselection when a person opens.
- Explicit **Set Selected as Preferred** confirmation; no KB files or encoding banks are modified.
- **Reset to Automatic** uses the existing preference service.
- Missing/unreadable originals retain the details workflow and show a nonfatal preview message.
- Selection-generation checks ignore stale thumbnails after rapid person switching. Queued obsolete image jobs are removed safely.
- Selecting another image cancels queued larger-preview decodes without disturbing queued thumbnail work.
- Workbench shutdown explicitly cancels queued gallery work and waits for active image readers to finish.
- Workbench shutdown also cancels pending crop previews, terminates an active native child, and reaps its worker thread.

## Scope limitation

This is a read-only preview: no preference is set and no KB source or cache file is written until the user chooses the existing **Set Selected as Preferred** action. The face-quality score reuses `_quick_image_quality` and `_face_quality_score` from `kb_gallery_optimizer.py`; it is a heuristic measure of sharpness, face size and contrast. It does **not** verify that the face belongs to the selected person, identify duplicates, compare body embeddings, or evaluate collection diversity. Those are essential for actual curation proposals and remain out of scope for this slice. Multi-face/no-face images report an inline explanation; the established preference fallback remains authoritative after confirmation.

## Windows smoke-test checklist

1. Open Persons Workbench with 0, 1, 12 and 100+ KB images. The gallery should remain responsive.
2. Select a different person while thumbnails load; no previous person's images should appear.
3. Scroll the gallery and inspect thumbnails and the enlarged original.
4. Select an unreadable image; verify a nonfatal preview message.
5. Confirm a preferred image; verify the expected portrait eventually appears in roster and details.
6. Restart and confirm persistent preference, then reset to automatic.
7. Try multi-face and missing images; verify existing service fallback.
8. Repeat native portrait failure/restart and 20-cycle shutdown tests. The gallery must not spawn dlib processes itself.
9. Select 20 images rapidly while decoding is slow; the final preview should no longer wait behind obsolete queued previews.
10. Close with many thumbnails still pending; the gallery pool should have no active workers or queued jobs afterward.
11. Select single-face, no-face, and multi-face images. Only a single usable face should yield a crop preview.
12. Switch quickly between 20 images; only one running and the latest queued crop request should remain, with no stale crop shown.
13. Kill a crop child manually and verify the GUI stays operational; subsequent selections should still produce previews.
14. Shut down during a running crop; verify the child terminates and is reaped without hanging the GUI at exit.
15. Inspect the preference and portrait-cache directory before/after preview-only interactions; bytes and timestamps should be unchanged.
16. Select a single-face image and compare the displayed sharpness and face-quality values to the optimizer's per-image feature extraction.
17. Verify non-single-face images have no numeric face-quality score and are annotated with the detected face count.
18. Switch persons during quality computation and confirm no previous person's badge or metrics are applied.
19. Simulate `subprocess.Popen` failure and an unexpected Qt worker exception; each must produce an error completion and later requests must recover.

## Verification performed here

Python syntax compilation of both files passed. PyQt6 and the native recognition runtime are unavailable in this environment, so no GUI or native-process execution is claimed.
