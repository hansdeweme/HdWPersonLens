# Persons Workbench — Phase 0 design and implementation slice

## Confirmed decisions

- Roster: hybrid searchable table with portrait column, name and configurable DB columns.
- Placement: a first-class tab in the main window.
- `browse_persons_custom.py` and reduced distribution-specific settings/schema: **out of scope**, to be removed by the owner.
- `kb_gallery_optimizer.py` remains a KB curation workflow selecting encoding references from a person's photo collection. Reuse narrowly scoped pure scoring logic only after isolating it from curation behavior; do not invoke gallery optimization from the roster.
- The first slice is read-only and additive. Existing Persons DB tab, `QueryPersonsDialog`, dialogs, menu shortcuts and management paths stay intact until parity is established.

## Component boundaries

| Component | Responsibility | Dependency | First slice |
| --- | --- | --- | --- |
| `PersonsWorkbench(QWidget)` | Search toolbar, splitter, selected record presentation, refresh orchestration | Person roster + DB | Implemented |
| `PersonRosterModel(QAbstractTableModel)` | DB records, formatted columns, stable person name role | `PersonDB` | Implemented |
| `PersonRosterFilter(QSortFilterProxyModel)` | Search and sort without row-index caches | Roster model | Implemented |
| `PersonDetails(QWidget)` | Schema editor, gallery, status and contextual actions | `SchemaForm`, services | Planned extraction |
| `PersonPortraitService` | Stable portrait selection, identity checks, crops and cache | Face detection and reference encodings | Planned |
| `PersonService` | Authoritative KB mutations | KB Manager + PersonDB | Retain |
| `PersonDB` | Authoritative metadata operations | JSON/NDJSON file | Retain |

`PersonRosterModel` stores display data by record and exposes stable names through a Qt item role. The proxy queries the source record, so table sorting cannot invalidate boolean caches as it currently can in `QueryPersonsDialog`.

## First implementation slice delivered

`persons_workbench.py` adds a self-contained read-only tab with:

1. Searchable, sortable hybrid table with an explicit placeholder portrait column.
2. Configurable DB columns from `query_persons_view.columns` with fallback columns.
3. Selection-driven record details, grouped birth-date formatting, and an explicit KB-status placeholder.
4. Manual Refresh preserving the selected person where possible.
5. No image decoding, face recognition, encoding writes, or network I/O on the GUI thread.

### Integration patch for `recognition_gui.py`

Add near other local imports:

```python
from .persons_workbench import PersonsWorkbench
```

In `MainWindow.initUI()`, immediately before the existing `self.main_tabs.addTab(self.person_db_editor, "Persons DB",)`:

```python
self.persons_workbench = PersonsWorkbench(self.person_db, self.person_service, self.settings, parent=self)
self.main_tabs.addTab(self.persons_workbench, "Persons Workbench")
```

Leave the old Persons DB editor tab intact during this first milestone. After any existing mutation callbacks, refresh the workbench, e.g.:

```python
if hasattr(self, "persons_workbench"): self.persons_workbench.refresh()
```

Apply this refresh after `_on_person_record_saved`, `_on_person_record_deleted`, `_on_person_database_reloaded`, `_on_person_added`, `_on_person_renamed`, `_on_person_removed`, and `_on_person_images_updated`. The first three are already wired to the schema editor's signals.

### Important integration note

The supplied code is a concatenated `.txt` snapshot, not the actual repository. The import and main-window changes above have deliberately **not** been applied to the snapshot. Copy the module into `hdw_person_lens/` and apply the small integration edit in the live repository after reviewing its current state.

## Mapping of existing user actions

| Existing action | Handler / backend | Workbench destination |
| --- | --- | --- |
| Browse DB | `query_persons` / `QueryPersonsDialog` | Workbench roster |
| Edit DB metadata | `PersonDbEditorWidget.on_save` / `PersonDB.upsert` | Schema form in details |
| Create DB record | `PersonDbEditorWidget.on_save` | New Person flow / schema form |
| Delete DB record | `PersonDbEditorWidget.on_delete` | Explicit metadata-only action; distinguish KB removal |
| Add KB person | `AddPersonDialog` / `PersonService.add_to_knowledge_base` | Contextual Add action |
| Rename person | `AlterPersonDialog` / `PersonService.rename_person` | Contextual Rename action |
| Remove person | `RemovePersonDialog` / `PersonService.remove_person` | Contextual Remove action |
| Edit KB images | `EditPersonImagesDialog` / `PersonService.update_person_images` | KB gallery actions |
| Re-encode person | `MainWindow._start_reencode_worker` / `PersonService.reencode_persons` | Re-encode selected |
| Open KB folder | `QueryPersonsDialog._open_folder` | Selected-person action |
| Open collection folder | `QueryPersonsDialog._reveal_images` | Selected-person action |
| Find lookalikes | `MainWindow.find_lookalikes` | Selected-person contextual launch, once parameter passing is supported |

## Portrait design for next slice

Portrait candidates come **only** from `PersonService.get_person_image_paths(name)` — the person's known KB reference images, not their broader DB photo-collection folder. `kb_faces.extract_primary_face_embedding` returns the largest detected face and `selected_bbox`; this is useful for a candidate crop but insufficient proof of identity in a multi-face image. For ambiguous photos, identify the correct detected face against trusted person encodings, or reject the candidate. Quality ranking then favors suitable face size, sharpness, contrast and framing. Provide manual override, durable preference, deterministic tie-breaking, and a versioned cache keyed to source file fingerprints and model/scoring versions. No automatic KB modifications.

The worker returns immutable portrait results with generation/person keys to prevent stale asynchronous updates attaching the wrong thumbnail after a rename, deletion, re-sort, or fast selection change. Image decoding/face analysis stays off the GUI thread; convert final image data to `QPixmap` on the main thread.

## Existing code issues to address separately

- `browse_persons.py`: `_row_bool_cache` is indexed by displayed row and becomes incorrect after table sorting.
- `browse_persons.py`: synchronous `QPixmap` loading in `_populate_table` delays opening and scrolling.
- `browse_persons.py`: `_display_value_and_sort_key` is defined twice; the later definition overrides date formatting.
- `browse_persons.py`: `_is_dynamic_excluded` recursively calls itself, although its present call path appears unused.
- `SchemaForm` and `PersonDbEditorWidget` already offer reusable schema-driven form and mutation signals. Prefer extracting the form rather than nesting the entire existing dual-pane editor inside another splitter.
- Keep distinction between database-only deletion and full KB person removal explicit.

## Verification checklist

- [x] Python syntax compilation of the new module.
- [ ] Import and Qt offscreen smoke test (PyQt6 unavailable in this analysis environment).
- [ ] Add new tab in actual `recognition_gui.py` package and start Windows app.
- [ ] Search and sort with differently ordered people; confirm correct selection and details.
- [ ] Verify grouped `birth date`, custom column paths and empty DB.
- [ ] Verify refresh after DB record create, rename, delete and reload.
- [ ] Verify startup on Windows Python 3.10 and 3.13.
- [ ] Verify no side effects on existing KB encodings, folders or Persons DB files.

**Release gate:** do not remove any old tab/menu until both editing and KB mutation parity have been demonstrated. This slice is a foundation, not a full workbench release.
