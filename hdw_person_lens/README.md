# PersonLens v1.9.8 — Native KB-Only Rename & Remove (integration preview)

This is the next v1.9.7 management-parity slice. It enables Workbench-native **Rename** and **Remove** for recognition-only people without creating Persons DB rows. It does not enable KB-only Edit Images or Re-encode and does not retire any legacy tools.

## Apply safely

Only **five targeted unified patches** are provided alongside this README, plus a focused test. There are no full replacement `recognition_gui.py` or `persons_workbench.py` files in the deliverable.

After extracting into a separate folder, from your project's root (the parent of `hdw_person_lens`) check each patch using `git apply --check <path-to-patch>`, then apply it with `git apply <path-to-patch>`. If a check fails because your current source differs, merge that patch manually and retain all existing changes. **Do not reset, overwrite or replace current source files.**

Suggested order: `policy.patch`, `rename.patch`, `remove.patch`, `workbench.patch`, `dispatch.patch`.

## Behavior

- Policy permits Rename and Remove when either a real DB record or an actual recognition profile exists. Other KB-only management actions remain disabled.
- Rename and Remove panels open for genuine KB-only identities. They capture confirmation evidence and recheck it after confirmation and again during main-window dispatch. Evidence includes person state, DB record contents, selected-person embedding values and provenance, folder/file identities, and image paths, sizes and modification times. A busy encoding bank rejects confirmation without waiting.
- The confirmed selected identity and external photo-folder path are validated at dispatch. Photo-folder rename/deletion controls are disabled when there is no DB record. A forged enabled choice is also rejected at both panel and dispatcher.
- Workbench Qt signals now pass an immutable confirmed state alongside the existing confirmation inputs.
- Service calls remain the same `PersonService.rename_person()` and `remove_person()` operations. DB-backed behavior is retained. External photos are preserved by default.
- `dispatch.patch` also adds a private PersonService evidence helper. The re-encoding worker, source snapshot forwarding, gallery decoder, and saved KB images are unchanged.
- File revision checks avoid image decoding or image hashing on the GUI thread. Deliberate in-place content edits preserving file identity, size and modification time are not detected; these checks are not SHA-256 source verification.
- KB-only guidance explicitly identifies Rename and Remove as available.

## Local verification

8 focused policy/structural tests passed; Python syntax compilation passed. These are structural checks; native Qt behavior and transactional execution still require the Windows acceptance checks below.

## Windows acceptance (disposable KB copy only)

1. Create a KB-only identity without a Persons DB row, select it, and verify Rename and Remove are enabled; Edit Images/Re-encode still disabled.
2. Rename the KB-only identity. Verify KB folder and face/body encoding labels move, roster selection updates, and no DB row appears.
3. Remove another KB-only identity; ensure folder and embeddings disappear, and external photo-folder option is disabled. Confirm cancellation is a no-op.
4. Change the selected person, source folder, encodings or person type during either confirmation; verify stale state rejects dispatch.
5. Confirm DB-backed rename/remove still offer photo-folder options, retain canonical rename results and exact-path confirmation protection.
6. Exercise service failure/rollback on disposable copies, and confirm Activity records failures without losing context.
7. Run the existing full suite, especially the v1.9.5 **worker snapshot under the service lock**, v1.9.6 preview lifecycle, and v1.9.7 navigation regressions.

## Retirement gates still open

Full management consolidation still requires KB-only Edit Images and Re-encode parity; comprehensive Persons DB schema editing; legacy browse/query/export parity; and end-to-end verification of transactional rollback and operation progress. Legacy menus/dialogs remain available.
