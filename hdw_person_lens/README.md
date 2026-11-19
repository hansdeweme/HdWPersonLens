# PersonLens Persons Workbench ? v0.5 stable baseline

The v0.5 baseline combines persistent preferred portraits, a visual KB gallery,
and a read-only face-crop preview. The Git tag is `v0.5`; package metadata is `0.5.0`.

## Workbench

- Browse and search the person roster, with asynchronous cached portraits.
- Select a person to view KB image thumbnails and metadata in the scrollable details panel.
- Select a gallery image to view its original and a 224 ? 224 face crop.
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

## Validation

The portrait and preview regression suite passes 27 tests, covering preference
persistence, both cache races, fallback, legacy-cache preservation, child cleanup,
20 refresh/tab-switch cycles, forced failures, launch errors, and worker recovery.

Run the focused suite with:

```powershell
py -3 -m pytest tests/test_person_portrait_service.py tests/test_preferred_portraits.py tests/test_portrait_process.py tests/test_workbench_portrait_lifecycle.py tests/test_kb_faces_thread_safety.py tests/test_face_crop_preview.py -q
```

`tests/portrait_preference_native_check.py` checks real face detection and offscreen
Qt integration using disposable KB copies, including a fresh application process.
Native gallery checks also verified matching portrait/crop output, zero/multiple-face
explanations, latest-only queued analysis, failure recovery, and shutdown cleanup.
Original KB images remained untouched.

## Limits

Active original-image decodes finish before shutdown returns. A single-face KB image
is still a provisional identity assumption; there is no independent embedding-based
identity verification. Selecting a preferred image confirms the source, not a custom
editable crop.
