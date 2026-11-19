# PersonLens Persons Workbench - v0.6.1 stable quality-indicator baseline

The v0.6.1 baseline combines persistent preferred portraits, a visual KB gallery,
and read-only face-crop and quality previews. The Git tag is `v0.6.1`; package
metadata is `0.6.1`.

## Workbench

- Browse and search the person roster, with asynchronous cached portraits.
- Select a person to view KB image thumbnails and metadata in the scrollable details panel.
- Select a gallery image to view its original, a 224 x 224 face crop, and quality metrics.
- Analyzed images show a face-quality score or face count; details show sharpness,
  face width, and face quality. Analysis runs on demand in the same isolated process.
- Click **Set Selected as Preferred** and confirm, or **Reset to Automatic**.

Preferences are separate `.preferred.json` files in the per-user portrait cache.
The preferred image must be returned by `PersonService.get_person_image_paths(name)`.
It is included first in the bounded scan of up to 24 KB images. Unusable, missing,
or multi-face preferred images fall back to qualifying automatic candidates.

## Isolation and caching

Portrait and face-crop detection run in disposable child processes. The GUI does
not call dlib. The preview uses the portrait service's single-face rules and crop
geometry, without writing KB images, preferences, or portrait cache files.

Portrait requests capture their preference, sources, and signature once before
crossing the process boundary. Positive files are named
`<person-hash>.<signature>.png`; legacy `<person-hash>.png` files are ignored and
left untouched. Changing a preference invalidates only that person's cache key.

The gallery cancels obsolete queued previews, preserves thumbnail jobs, and runs
at most one native crop analysis at a time. Shutdown cancels queued work, terminates
active crop processes, and waits for active original-image decoders. Repeated
shutdown is safe. Launch failures and unexpected crop-job exceptions report a
completion/error signal so subsequent selections can proceed.

Failed analysis without metrics shows **Quality unavailable**, clears previous
scores and gallery badges, and permits a later request to recover. Zero-face and
multi-face results retain their available measurements and explain why no reliable
crop is shown. Quality scores reuse the gallery optimizer's sharpness, face-size,
and contrast heuristics; they are not identity checks or encoding recommendations.

## Validation

The portrait, preview, and quality regression suite passes 30 tests, covering preference
persistence, both cache races, fallback, legacy-cache preservation, child cleanup,
20 refresh/tab-switch cycles, forced failures, launch errors, worker recovery,
quality metadata, unavailable metrics, and stale-score clearing.

Run the focused suite with:

```powershell
py -3 -m pytest tests/test_person_portrait_service.py tests/test_preferred_portraits.py tests/test_portrait_process.py tests/test_workbench_portrait_lifecycle.py tests/test_kb_faces_thread_safety.py tests/test_face_crop_preview.py tests/test_face_crop_quality.py -q
```

`tests/portrait_preference_native_check.py` checks real face detection and offscreen
Qt integration using disposable KB copies, including a fresh application process.
Native gallery checks also verified matching portrait/crop output, zero/multiple-face
explanations, latest-only queued analysis, failure recovery, and shutdown cleanup.
Original KB images remained untouched.

The quality-indicator slice and its failure-state corrections have also passed
native validation. Collection-level KB assessment is a subsequent step; this
baseline does not assess duplicates, body embeddings, or collection diversity.

## Limits

Active original-image decodes finish before shutdown returns. A single-face KB image
is still a provisional identity assumption; there is no independent embedding-based
identity verification. Selecting a preferred image confirms the source, not a custom
editable crop.
