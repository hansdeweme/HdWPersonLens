# PersonLens v1.9.0 — Management Parity Audit

This is a **read-only audit slice**. No application modules are replaced, no database or KB content is modified, and no legacy entry point is retired.

## Source baseline

Reviewed the current versions of `recognition_gui.py`, `persons_workbench.py`, `person_management_diags.py`, `person_service.py`, and `person_action_policy.py` supplied for the v1.8 line. The checks in `tests/test_management_contract_inventory.py` are *structural inventory checks*, not behavioral or native-Qt parity certification.

## Action mapping

| Workbench action | Current route | Service operation | Native destination |
| --- | --- | --- | --- |
| Add Person | `AddPersonDialog` | `add_to_knowledge_base(name, images, ...)` | Guided creation pane, with optional DB-record creation after success |
| Rename | `AlterPersonDialog` | `rename_person(old_name, new_name, rename_photo_folder, new_photo_path)` | Selected-person rename pane |
| Remove | `RemovePersonDialog` | `remove_person(name, remove_database_record=True, delete_photo_folder=False)` | Selected-person removal pane and destructive confirmation |
| Edit Images | `EditPersonImagesDialog` | `update_person_images(name, add_images, remove_images, ...)` | KB Gallery staging mode |
| Re-encode | Direct `_start_reencode_worker(names=[name])` | `reencode_persons(...)` | Workbench progress/outcome integration; retain all-image semantics |
| Edit Profile | Native `SchemaForm` editing | Existing guarded PersonDB save | Retain; no replacement needed |

## Required behavior before retirement

### Add Person

- Existing metadata-only DB entry may be used; a new recognition name is also allowed.
- Recognized-name conflicts are rejected, with a redirect to Edit Images/Re-encode.
- Images support file selection and drag/drop, path normalization, extension validation, duplicate suppression, removal, and clearing.
- At least one image is required; explicitly confirm name and count before launching the worker.
- Use background encoding, Activity log/progress, and failure reporting; do not close while busy.
- Show face/body encoding totals. If the DB record is absent, offer to create it after success; infer `files_path` only if all selected images share one parent.

### Rename

- Use the *selected* identity, not a default person from an independent dropdown; detect stale/deleted selection immediately before dispatch.
- Preview changes to KB folder, face/body encoding labels, and DB record when present.
- Optionally rename the external photo collection folder, allowing a custom destination or service-suggested sibling path.
- Obtain explicit confirmation, preserve service conflict/error handling, then update shared person context, DB editor, and Workbench selection.

### Remove

- **Full removal** deletes KB folder, face/body encoding entries, and DB record when present; the external photo collection is **preserved by default**.
- An optional, separately indicated choice permanently deletes that external photo folder, only if the path exists.
- Show the exact resource scope and ask for destructive confirmation (default No). Report changed resources, face/body counts, and warnings.
- **DB-record-only deletion is a different operation** and must remain available without touching KB, encodings, or media.
- Refresh context after success; failure must not claim removal.

### Edit Images

- Show existing images; stage additions and removals, cancel pending additions, restore pending removals, preview full images, discard pending changes.
- Lock the selected person while changes are pending. Unsaved-change navigation must explicitly offer to discard or stay.
- Confirm addition/removal counts; apply via `update_person_images` in a worker, then rebuild encodings.
- Preserve staged edits if the operation fails. Refresh KB Gallery, assessments, portrait preferences/cache, provenance, and readiness as appropriate.
- **Curation `Exclude` is an advisory decision, not image deletion.** No migration may conflate them.

### Re-encode

- Preserve the conventional all-image re-encode route. Controlled reference encoding from v1.7.x remains an explicit, separate pathway.
- Ensure progress ownership, Activity outcomes, worker lifecycle cleanup, and post-encode freshness/invalidation.

## Cross-cutting acceptance gates

1. Exact person-context agreement at confirmation and execution; no silent fallbacks to another person.
2. Current DB/profile/source membership verification; appropriate conflict handling for external edits.
3. Confirmation captures an immutable operation proposal; later UI changes cannot alter its target.
4. All blocking image/embedding operations run outside the GUI thread; cancellation and shutdown clean up workers.
5. Success, partial failure, and unexpected termination are reported accurately in Activity and progress state.
6. No change to unrelated people; source images are preserved except where explicit full-removal semantics authorize deletion.
7. Current assessment, shortlist, preference, portrait cache, provenance, and readiness state is invalidated or refreshed after relevant writes.
8. Functional service tests, native Qt interaction tests, and real Windows smoke tests pass before the matching legacy entry point is removed.

## Proposed migration order

1. v1.9.1 Rename, 2. v1.9.2 Edit Images, 3. v1.9.3 Add Person, 4. v1.9.4 Remove Person, 5. v1.9.5 Re-encode consolidation and retirement review.

**Decision:** Keep legacy dialogs and menu entry points throughout v1.9.0–v1.9.4. Retirement is conditional on *demonstrated* parity, not merely the presence of replacement controls.

## Verification

Run structural checks against a complete codebase:

```bash
python -m unittest discover -s tests -p 'test_management_contract_inventory.py' -v
```

These tests expect the package at `hdw_person_lens/`, with `person_management_diags.py` and `recognition_gui.py` from the current baseline. They intentionally do not import dlib or launch Qt.
