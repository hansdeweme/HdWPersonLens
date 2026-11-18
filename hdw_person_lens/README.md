# PersonLens Preferred Portraits — v0.3 initial slice

This package builds on the **committed process-isolated** application snapshot supplied on 18 November 2026.

## Files to replace

- `hdw_person_lens/person_portrait_service.py`
- `hdw_person_lens/persons_workbench.py`
- `hdw_person_lens/portrait_process.py`
- `hdw_person_lens/portrait_worker.py`

Update these four files together: the service, process runner, and child worker share the same request snapshot. `kb_faces.py`, `person_service.py`, and `recognition_gui.py` retain the Phase 1 implementation.

## New behavior

1. Select someone in Persons Workbench.
2. Click **Choose KB portrait…** and select an existing KB image by filename.
3. The preference is saved under the per-user portrait cache as a separate `.preferred.json` file, not in the Persons DB or KB folder.
4. Refresh invalidates the displayed portrait; the existing process-isolated pipeline regenerates the crop from the preferred image if it has exactly one usable face.
5. Click **Reset to Automatic** to remove the preference and restore automatic selection.

The source-selection limit is still 24 images per person; the preferred image is moved to the front of that bounded scan, even when it originally appeared later in the KB directory. The original cache signature now includes the preferred image path, so changing/resetting a choice invalidates only the affected person's portrait.

Each request captures its preference, candidate files, and signature once and passes that snapshot to the child process. Positive cache files use `<person-hash>.<signature>.png`, so overlapping requests cannot mix another signature's image bytes with their metadata. Legacy `<person-hash>.png` entries are ignored and left untouched.

## Guardrails

- Manual preferences must refer to files returned by `PersonService.get_person_image_paths(name)`; no arbitrary file paths or KB mutations.
- The GUI never calls dlib; its existing `PortraitProcessRunner` still launches disposable native child processes.
- Multi-face/undetectable preferred images are **not forced**: they fall back to the best qualifying automatic candidate. The preference remains stored until reset.
- A deleted preferred source likewise falls back automatically. It does not delete or rewrite the preference.
- The UI currently uses a filename picker. A thumbnail gallery and crop-before-confirmation interaction are **not** included in this initial v0.3 slice.
- There is no independent face-embedding identity verification yet; a single-face KB image remains a provisional identity assumption.

## Validation

The portrait suite passes 23 automated tests, including both cache-race regressions, preference persistence, fallback, legacy-cache preservation, process cleanup, 20 refresh/tab-switch cycles, and forced-process-failure recovery.

The native Windows integration check in `tests/portrait_preference_native_check.py` also passed using disposable copies of KB images:

- Choose a single-face KB image and confirm it becomes the roster and detail portrait.
- Restart PersonLens and confirm the preference persists and loads from cache.
- Reset to Automatic and confirm restoration of the prior automatic choice.
- Select a photo with multiple faces and verify safe fallback without a crash.
- Remove/replace a selected KB image; verify fallback and no KB writes.
- Repeat the 20-cycle tab/refresh/shutdown and forced-process-failure tests from the committed baseline.
- Change the preference during child-process launch and confirm the frozen request cannot poison the automatic cache.

The native check uses offscreen Qt windows and real face detection, including a fresh application process to verify cache reuse. Original KB images remain untouched. The thumbnail gallery remains a later slice.
