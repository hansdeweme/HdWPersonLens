# HdW PersonLens — Persons Workbench modernization

## Context and objective

HdW PersonLens is a local-first PyQt6 desktop application for managing persons in photo collections. It combines a schema-driven Persons DB (`persons.json` and `person.schema.json`), person-specific knowledge-base (KB) folders, face and body encodings, recognition, lookalike searches, image review, and KB maintenance. The application now uses the `hdw_person_lens` Python package structure. It runs on the development machine with Python 3.13 and has been tested successfully on a second Windows machine with Python 3.10.

The current interface exposes overlapping workflows through **Manage Persons**, **Browse Persons DB**, and **Persons DB Editor**. We want to consolidate these into one central, modern **Persons Workbench**, borrowing the cleaner visual language of SignalLens without disrupting PersonLens's established architecture or existing KB data.

The key design decision is **search-first person management**: begin with the existing Persons DB search/roster interface and expand it into the primary place for finding, inspecting, editing, and maintaining persons. The workbench should show a small, representative face portrait for each person, selected automatically from that person's KB images using a reliable face-quality assessment.

## Recovered findings from the original design discussion

The following findings come from the recovered *Modernizing PersonLens GUI* discussion. Verify that they still hold in the latest repository before implementation.

| Existing module | Existing role | Intended reuse |
| --- | --- | --- |
| `browse_persons.py` | Searchable Persons DB roster with filtering and image preview | Main person browser |
| `browse_persons_custom.py` | Second browser implementation | Consolidate with the primary browser; do not modernize both |
| `person_db_gui.py` | Schema-driven metadata editor | Embedded person-details panel |
| `person_management_diags.py` | Add, rename, remove, edit images | Selected-person actions |
| `person_service.py` | Coordinates Persons DB, KB folders, and encodings | Existing authoritative management backend |
| `kb_gallery_optimizer.py` | Face-quality analysis and gallery assessment | Source of portrait-selection scoring |
| `kb_faces.py` | Existing face pipeline, including `selected_bbox` | Face localization for portraits |

One precise UI finding: **the current browser already supports an image preview**, but the preview selection in `recognition_gui.py` was based on the first alphabetically sorted KB image. The first image is not necessarily a representative portrait. The aim is to improve that selection logic, not start the image-preview functionality from scratch.

## Intended user experience

1. Open **Persons Workbench** from the main window.
2. Search, filter, and sort people in a responsive roster. Reuse the existing schema-driven column model and user-configurable view settings where practical.
3. See a representative portrait alongside each person; selecting a person reveals the full profile.
4. View and edit the selected person's schema-driven metadata, inspect their KB reference images, and see compact KB status information (for example, image and encoding counts when readily available).
5. Perform common actions in context: add person, edit details, rename, remove, manage KB images, re-encode, open the person's KB folder, and launch lookalike search where supported.
6. Receive clear feedback after actions, with the roster, portrait, image gallery, and details refreshed without restarting the app.

### Suggested screen composition

- **Left / roster:** search box, filters, sortable columns or compact rows, thumbnail and person name, and optional status badges.
- **Right / details:** a larger portrait, editable DB fields, a KB image strip/grid, metadata and encoding summary, and context-specific actions.
- **Top toolbar:** New Person, Refresh, optional view controls, and other high-frequency actions.
- **Status area:** semantic status indicators, progress, warning messages, and a collapsible activity log.

Keep the **restrained dark SignalLens aesthetic**: clear typography, resizable panels, image-led presentation, and consistent controls. This should remain a practical workbench, not a dashboard filled with decorative metrics. The layout is a design starting point, not a commitment before inspecting the present widgets. A splitter and remembered panel sizes would suit desktop use.

## Architecture principles

- **Reuse the existing logic.** Treat `browse_persons.py` / `QueryPersonsDialog` as the starting point for search and roster behavior, consolidate the overlapping `browse_persons_custom.py`, and reuse `person_db_gui.py`'s schema-driven form logic where possible. Avoid building parallel person-management logic.
- **Keep the GUI thin.** All writes should continue through existing service/manager APIs, particularly `PersonService` and the established Persons DB / KB management services. The workbench should orchestrate them, not write directly to `persons.json`, person folders, or encoding files.
- **Separate components.** The recovered architecture proposes `PersonsWorkspace` (integrated UI), `PersonBrowser` (Qt model and filters), `PersonDetails` (schema form and gallery), `PersonDB`/`PersonService` (existing backend), and `PersonPortraitService` (face scoring and cache). Confirm exact names and boundaries against the current source.
- **Preserve the schema-driven model.** The general `person.schema.json` should remain independent of any particular collection's custom fields; display columns can be configured via `settings.json`. Existing grouped fields, such as birth-date year/month/day presented as one date, should still work.
- **Keep expensive work off the GUI thread.** Face analysis, portrait scoring, image enumeration at scale, and encoding maintenance should use background workers, with deliberate progress/cancellation and robust `QThread` lifecycle handling.
- **Preserve existing KB standards.** Do not change the v2 KB structure, compatibility/consistency rules, safe encoding-bank loading, or the distinction between person folders and system folders. Avoid accidental person creation from a batch of images or automatic teaching from recognition results.

## Portrait selection — proposed `PersonPortraitService`

The portraits are an important usability improvement, not just decoration. For each person:

1. Enumerate eligible image files in the **known person's KB folder**, not arbitrary system folders.
2. Detect faces with the existing face pipeline. `kb_faces.py` already exposes `selected_bbox`, which can provide the crop coordinates.
3. Prefer **one clearly visible face**. For multi-person photos, verify that the chosen face matches the person's existing face encodings before accepting it.
4. Rank qualified faces using `kb_gallery_optimizer.py`'s `_face_quality_score()` and `GalleryImageAssessment`, which cover sharpness, face size, and contrast. Add a portrait-framing preference only if needed.
5. Select the best candidate deterministically; generate a square, face-centered crop with some surrounding context and a larger preview where useful.
6. **Allow the user to choose a preferred portrait manually** from the KB gallery, overriding the automatic choice; preserve that preference across sessions.
7. Cache results so reopening or scrolling through the roster does not rerun face detection for every image. Track enough source information to invalidate the cache when a person's KB images change.
8. Fall back to a neutral placeholder when no suitable face is available. A profile must remain usable even if its KB folder is empty, missing, or contains no detected face.

**Face quality is not identity confidence.** A sharp picture of the wrong person must never become that person's portrait simply because it has a high quality score. Reuse the established face-quality calculation, but verify the identity of ambiguous faces. Define a bounded initial scan and async/lazy loading so large KBs remain responsive: the browser must open immediately with cached portraits or placeholders.

## Proposed implementation phases

### Phase 0 — inspect and design

- Inspect the current `recognition_gui`, `browse_persons`, Persons DB editor, `person_service`, KB manager, existing workers, settings, and tests.
- Compare `browse_persons.py` and `browse_persons_custom.py` and choose one browser/model to carry forward.
- Trace the current alphabetical image preview selection in `recognition_gui.py`; inspect `kb_gallery_optimizer._face_quality_score()`, `GalleryImageAssessment`, and `kb_faces`'s `selected_bbox`.
- Inventory every existing action under the three person-related menu areas and its service call, validation, side effects, shortcuts, and refresh signals.
- Identify reusable widgets/model logic and how the existing editor emits record-saved/deleted/reloaded and person-action signals.
- Sketch a compact workbench wireframe and agree on its first-release scope.

**Deliverable:** class/component boundaries, action mapping, UI wireframe, and a minimal-risk implementation sequence.

### Phase 1 — portrait pipeline

- Implement/test portrait candidate selection, identity verification, reusable face-quality scoring, crop generation, automatic/manual portrait selection, cache handling, and placeholders.
- Add tests for empty/missing KB folders, multiple images/faces, wrong-face rejection, manual override, unreadable images, cache invalidation, and deterministic selection.
- Integrate thumbnail retrieval asynchronously into the existing roster as an isolated improvement.

**Deliverable:** the current person browser displays useful face thumbnails without UI freezes.

### Phase 2 — integrated browse and detail workspace

- Reuse or extract the search/filter/sort table or model from `QueryPersonsDialog` so it can be embedded in a persistent workbench.
- Reuse the schema-driven editor for the selected record rather than duplicating form-building and validation.
- Show KB reference images, portrait preview, and lightweight per-person status.
- Persist suitable view preferences and splitter/column settings.

**Deliverable:** users can browse, select, inspect, and edit persons in one place.

### Phase 3 — unify person actions

- Move or expose Add, Rename, Remove, Manage Images, Re-encode, and other relevant actions within the workbench.
- Route operations through existing services/workers; preserve confirmations, error handling, cancellation, and transaction boundaries.
- Ensure all views refresh after successful mutations, including name changes, image changes, and person deletion.
- Carefully test failure cases where a DB write and KB operation might only partially succeed.

**Deliverable:** the common person-management workflow is complete inside the workbench.

### Phase 4 — navigation and polish

- Make **Persons Workbench…** the primary navigation entry.
- Consolidate or retire redundant *Manage Persons*, *Browse Persons DB*, and *Persons DB Editor* entry points only after the replacement reaches functional parity. Preserve useful keyboard shortcuts, mapping them to equivalent workbench actions.
- Apply the restrained dark SignalLens-inspired style, resizable panels, semantic status indicators, a collapsible activity log, consistent dialogs, and responsive loading indicators; avoid decorative metric panels.
- Keep specialist tools such as KB compatibility, gallery optimization, review/curation, and deduplication available in their appropriate menus; these are adjacent workflows, not automatically part of the workbench.

**Deliverable:** a clear and coherent main-window navigation structure.

### Phase 5 — validation and release hardening

- Test with empty, small, and large databases; missing KB folders; empty image galleries; custom schemas; stale portrait caches; and slow or unreadable files.
- Regression-test Add, Edit, Rename, Remove, Re-encode, lookalike navigation, and DB/KB consistency.
- Exercise repeated operations in one application session to catch worker/thread lifecycle issues.
- Smoke-test Windows Python 3.13 and 3.10, including settings migration and existing KB compatibility.
- Update README, screenshots, help text, and menu descriptions after the UX stabilizes.

## Definition of done

- A user can locate a person, inspect their portrait and KB images, edit their DB record, and carry out normal management tasks without switching between three unrelated interfaces.
- Portraits are helpful, reasonably representative, cached, refresh when needed, and never block roster navigation.
- Existing KB and Persons DB files remain compatible; no mandatory data migration is introduced by the UI redesign.
- There is a single authoritative path for each mutation, consistent status/error reporting, and no duplicate business rules.
- The app remains responsive and stable across repeated operations on both supported development/test installations.

## Guardrails and open decisions

1. **Inspect before editing:** the exact current source may differ from earlier uploaded snapshots. Use the current repository as the authority.
2. **Do not redesign recognition engines:** this project is primarily a workflow/UI modernization. The earlier discussion considered `PersonService` and existing recognition infrastructure reusable.
3. **Avoid expensive up-front thumbnail analysis:** decide whether portraits are computed on first display, precomputed in a background task, or progressively cached; measure on a representative KB.
4. **Clarify image management behavior:** viewing a reference, removing it, promoting a reviewed candidate, and rebuilding encodings are different actions with different safeguards.
5. **Decide the smallest viable first release:** likely a searchable roster with portraits and read-only detail; add editing and destructive operations incrementally.

## Prompt to start the new chat

> We are starting the **Persons Workbench** modernization of **HdW PersonLens**, our local-first PyQt6 application. The goal is to replace the separate **Manage Persons**, **Browse Persons DB**, and **Persons DB Editor** workflows with one coherent, search-first workspace using a restrained dark SignalLens style. Reuse the existing `browse_persons.py` roster, consolidate its overlapping `browse_persons_custom.py`, and embed `person_db_gui.py`'s schema-driven editor. The current browser already previews an alphabetically selected KB image; improve that preview using a proposed `PersonPortraitService`. Reuse `kb_gallery_optimizer.py`'s `_face_quality_score()` / `GalleryImageAssessment` and `kb_faces.py`'s `selected_bbox`; distinguish face-quality ranking from identity verification, especially for multi-person images. Implement async portrait selection, a thumbnail cache, placeholders, and a manual preferred-portrait override. Integrate selected-person actions from `person_management_diags.py` through the existing `PersonService`/`PersonDB` APIs. Preserve the v2 KB, encoding formats, compatibility checks, current worker architecture, and Python 3.10/3.13 operation.
>
> **Start with Phase 0:** inspect the current codebase and map the three existing workflows, reusable dialogs/models, services, signals, workers, and action callbacks. Then propose a compact wireframe, precise class boundaries, a first implementation slice, and tests. Do not begin a broad refactor or replace proven business logic before this review. I will provide the current sources (or repository access).
