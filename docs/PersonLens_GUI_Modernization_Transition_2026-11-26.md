# PersonLens GUI Modernization — Project Transition Brief

**Project:** HdW_Person Recognition / Modernizing PersonLens GUI  
**Prepared:** 26 November 2026  
**Stable baseline:** **v1.15.3**, user-tested in Windows, committed and synced  
**Next planned slice:** **v1.15.4 — Responsive KB Gallery** (not implemented)

## 1. Executive summary

PersonLens is a Python/PyQt6 application for maintaining a Persons database (Persons DB), a knowledge base (KB) of reference photographs, and face/body embedding banks used for recognition and related searches. The modernization project began with three disconnected user experiences—Manage Persons, Browse Persons DB, and the schema-driven Persons DB Editor—and set out to create one integrated **Persons Workbench**.

The Workbench is now the principal person-centered interface. It offers a searchable and sortable hybrid roster, portraits, profile editing, image inspection and management, quality/identity assessment, curation, reference shortlisting, controlled encoding, readiness and provenance, a unified person context, and consistent SignalLens-inspired styling. Important advanced and standalone legacy capabilities remain available intentionally.

**Do not interpret GUI consolidation as authorization to remove legacy modules.** Multiple parity/evidence audits explicitly preserve the standalone editor, legacy browser, global encoding and selected legacy operations until their independent functionality and native acceptance are certified.

## 2. Original purpose and design decisions

### User goals

1. Replace the fragmented experience with a coherent person-centered workspace.
2. Modernize the visual language to match SignalLens: dark surfaces, blue accents, clear role-colored actions, readable status and keyboard focus.
3. Make the roster, profile, KB gallery, assessments and management operations feel integrated.
4. Reuse existing services and schema-driven editing instead of creating competing data rules.
5. Preserve data safety, background responsiveness and Windows-native stability.

### Early explicit choices

- **Roster layout:** hybrid (tabular metadata, portraits, selected-person details).
- **Launch mode:** dedicated tab in the existing main window.
- **Editor:** reuse `SchemaForm`; preserve unknown nested metadata, do not write untouched defaults, and use guarded profile saves.
- **Distribution scope:** `browse_persons_custom.py` is a separate reduced public-distribution variant, not a modernization target.
- **KB tooling:** `kb_gallery_optimizer.py` is a curation aid for selecting reference photos, not a replacement for the Workbench.
- **Read-only by default:** analysis, previews, scoring and shortlisting do not modify source images or embedding banks; mutations require explicit dedicated actions.

## 3. Architectural map

| Responsibility | Principal components / concepts |
| --- | --- |
| Main application, tab/menu dispatch, Activity | `recognition_gui.py` |
| Hybrid roster, person details, internal tabs and focus layout | `persons_workbench.py` |
| DB editing and schema-driven form | `person_db_gui.py`, `SchemaForm`, `person_profile_panel.py`, `person_profile_merge.py` |
| Person identity across workspaces | shared person context, `PersonService`, `PersonState`, action eligibility policy |
| Portraits | `person_portrait_service.py`; signature-specific caching; isolated native child processes |
| Gallery and image management | `person_kb_gallery.py`, `person_workbench_images.py`; background preview decoding |
| Quality, identity and recommendations | collection/identity panels, recommendation service and shortlist, curation review |
| Encoding | controlled selection snapshots, worker/service validation, provenance and bank rollback |
| Readiness | KB health/readiness panels; identity remains explicitly unverified |
| Styling and preferences | `personlens_theme.py`, `person_workbench_preferences.py` (QSettings) |
| Legacy and parity controls | `management_retirement_audit.py`, `workspace_parity_audit.py`, `legacy_component_inventory.py` and related evidence tools |

The main flow is **roster → selected person context → Profile / KB Gallery / KB Assessment / Overview → explicit guarded action**. Internal navigation is designed not to restart native analysis merely because a tab or layout changed.

## 4. Development history (major milestones)

The version labels below summarize project milestones, not a claim that every historical package was independently re-run today.

| Phase | Delivered capabilities and key safeguards |
| --- | --- |
| **v0.2–0.3** | PersonPortraitService, thumbnail/full portrait separation, background delivery, disk cache, immutable source/preference signatures, preferred portrait reset. |
| **v0.4–0.6** | Visual KB Gallery, original and 224px face-crop preview, quality indicators, isolated detection processes and reliable error reporting. Gallery queues support cancellation and shutdown. |
| **v0.7–0.8** | KB collection analysis, duplicate detection, identity-consistency assessment, curated reference shortlist, diversity-aware recommendations, side-by-side visual comparison. |
| **v0.9–RC1** | Workbench UX consolidation, guided KB assessment, lifecycle cleanup, recovery and release preflight. |
| **v1.1–1.3** | Schema-driven selected-person profile editing; Add/Rename/Remove/Edit Images/Re-encode routing; initial SignalLens styling and accessibility focus fixes. |
| **v1.4–1.5** | Menus/shortcuts, Activity ownership and worker progress outcomes, application-wide dialog style, layout/search polish, focus indicators and status classification. |
| **v1.6** | Unified person context, action eligibility, guided KB image curation, persisted review decisions, review-aware shortlisting and filter/progress controls. |
| **v1.7–1.8** | Encoding impact preview, explicitly confirmed controlled reference encoding with freshness snapshots, rollback and provenance; recognition readiness/KB health. |
| **v1.9–1.10** | Migration of management actions to native Workbench flows, recognition-only people, snapshot/state guards, menu dispatch, structural contracts and retirement audits. |
| **v1.11–1.12** | Stronger integration between Persons DB and Workbench, navigation refinement, Advanced/Legacy Tools grouping and workspace parity audit. |
| **v1.13** | Legacy component inventory and native-evidence workflows. Evidence gates are conservative: passing structural tests alone is not a retirement certification. |
| **v1.14.0–1.14.4** | Unified Overview, Suggested Action, KB Workflow Journey, person-specific Activity and persisted Workbench view preferences. |
| **v1.15.0** | Focus Details: temporarily hide roster/search; restore prior split, selection and tab; Ctrl+Shift+F and Ctrl+F behavior. |
| **v1.15.1** | Previous/Next person navigation in Focus Details, respecting visible sorted/filtered rows and unsaved-edit safeguards. Corrected an omitted legacy test fixture in the download package. |
| **v1.15.2** | Responsive KB Assessment layout: Collection Quality and Identity Consistency side by side at wide widths, otherwise stacked. |
| **v1.15.3** | Responsive Profile layout: profile fields/status left and management/readiness right at wide widths, otherwise stacked. **User confirmed tests, GUI acceptance, commit and sync.** |

## 5. Current stable state

**Confirmed by the user:** v1.15.3 passed its eight focused tests, passed visual GUI checks, and was committed and synced. Earlier v1.15.0, v1.15.1 and v1.15.2 slices were likewise tested and synced. The user operates on Windows in `D:\Coding\HdWPersonLens` using `py -3.13`, while the coding environment may be Linux without native PyQt/dlib/Windows integration.

The present Workbench has:

- Searchable/sortable metadata roster with portraits and DB-backed plus KB-only people.
- Profile, KB Gallery, KB Assessment and Overview internal tabs.
- Context-sensitive management and schema-driven profile editing.
- Recognition readiness, assessment journey, quality/identity analysis, reviewed shortlist, controlled encoding and provenance.
- Native, recovery-aware workers and Activity reporting.
- Focus Details, focus-mode person navigation and responsive Profile/Assessment views.
- Persisted *normal* splitter preference even if the app closes while Focus Details is active.

There is no known unresolved regression in the committed **v1.15.3** baseline based on the latest user report. This is not a fresh full-suite certification.

## 6. Non-negotiable behavioral safeguards

1. **No unconfirmed mutation.** Profile saves, image changes, deletion, rename and encoding must validate the exact person and target confirmed by the user. Recheck after modal confirmations and immediately before service-side writes.
2. **Freshness and concurrency.** Keep source membership/signatures, confirmed encoding snapshots, stale-decision rejection, DB record conflict guards, lock coverage, and bank backup/rollback. Avoid GUI-thread lock waits.
3. **Native-process isolation.** Dlib detection/encoding must not crash the GUI; keep isolated worker processes, cancellation tokens, child reaping, recovery and bounded queues.
4. **Read-only analyses.** Gallery previews, face crops, collection scans, identity checks, recommendations and readiness must not rewrite source KB photos, preferences or banks unless a separately confirmed action expressly does so.
5. **Correct evidence language.** Heuristic face quality is not identity verification; identity remains labeled unverified. Do not promote incomplete reports or unavailable provenance to “Technically prepared.”
6. **Selection/dirty-state preservation.** Context, exact-person selection, sorting/filtering, internal tab, unsaved changes, and running workflows must survive navigation and responsive layout transitions.
7. **KB-only support.** Recognition-only people have different editing eligibility. Do not assume every roster person has a Persons DB record.
8. **Legacy parity.** Retain Advanced Tools, standalone Persons DB administration, DB-only deletion, legacy query/filter/export, global re-encoding and legacy paths until explicitly accepted for retirement.
9. **Accessibility.** Maintain visible keyboard focus indicators, scoped shortcuts, stable focus targets and accessible control names.

## 7. Release workflow and testing convention

- Work in **small versioned slices**. Deliver a patch based on the latest committed source, a focused test file, and a README/native Windows acceptance checklist.
- Verify `git apply --check`, Python compilation, targeted tests and diff hygiene before delivery. The user runs the Windows-native GUI and acceptance checks, then commits and syncs.
- Prefer **compact idiomatic Python**, keeping coherent expressions and calls on one line where practical (roughly 120 characters maximum).
- Never replace the current checkout wholesale with an older package or silently discard newer integration guards.
- When tests are structural or AST-based, say so explicitly; they do not substitute for native Qt or end-to-end testing.
- Avoid stale test fixtures when adding widget attributes. In v1.15.1, the initial ZIP omitted the updated v1.15.0 test stub for Previous/Next buttons; the corrected package resolved four `AttributeError` cases.
- Windows smoke testing is especially important around Qt object lifetime, focus, splitter/scroll geometry, worker shutdown and native libraries.

Useful Windows commands (from project root):

```powershell
git status --short
git apply --check .\<release_patch>.patch
py -3.13 -m unittest discover -s tests -p "test_<release>.py" -v
```

For a broad suite, the user previously ran:

```powershell
py -3.13 -c "import torch, unittest; suite = unittest.defaultTestLoader.discover('tests'); result = unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"
```

This pre-import of PyTorch worked around a sporadic Windows DLL initialization issue during full test discovery. It is not a substitute for fixing an actual application import failure.

## 8. Immediate next work: v1.15.4 — Responsive KB Gallery

**Status:** planned, **not implemented or tested**. The user supplied the current versions of these three modules on 26 November 2026:

- `hdw_person_lens/persons_workbench.py`
- `hdw_person_lens/person_kb_gallery.py`
- `hdw_person_lens/person_workbench_images.py`

The previous execution environment became intermittently unavailable before these attachments could be inspected. **A new chat should inspect the actual attached versions or request them again if attachments do not carry over.** Do not invent their contents or assume the previous gallery design remains unchanged.

### Proposed scoped behavior

1. Use wide viewport space for thumbnail browsing and side-by-side **original-image / face-crop preview**; stack vertically when narrow.
2. Keep preferred-portrait actions and image-management controls visible and readable without crowding thumbnails.
3. Reposition **existing widgets** rather than reconstructing the Gallery; retain selected path, thumbnails/full previews, quality badges, cached results and scroll position where practical.
4. Do not restart analysis or enqueue obsolete image decodes merely because Focus Details or window width changes.
5. Preserve gallery lazy loading, hidden-tab deferral, queued preview priority, cancellation, process isolation, freshness and shutdown semantics.

### Suggested acceptance tests

- Wide/narrow breakpoint transitions and original/crop alignment.
- Selection, quality metrics and preferred-image highlight survive repeated resizing.
- Rapid selection still prioritizes the most recent preview; thumbnails remain available.
- Hidden tab, workbench shutdown and person switch leave no stray jobs or processes.
- Image management retains its staged changes and exact target context.
- Focus-mode Previous/Next and layout preference restoration remain correct.

### After v1.15.4

Consider a short **v1.15 release consolidation**: assess layout density and accessibility at several window sizes, run native lifecycle smoke tests and full regression, update screenshots/documentation, and evaluate remaining parity gates separately. Avoid expanding scope into recognition algorithms without a deliberate new phase.

## 9. New-chat starter prompt

> We are continuing **HdW_Person Recognition — Modernizing PersonLens GUI**. Read the attached transition brief first. The stable, user-tested, committed and synced baseline is **v1.15.3**. The Workbench is the principal person-centered GUI, while standalone/legacy capabilities are retained intentionally pending parity certification. Preserve existing worker isolation, source freshness, immutable confirmed encoding snapshots, concurrency/rollback, KB-only eligibility, shared person context and unsaved-edit protection. Use compact idiomatic Python and small patch-based versioned releases with targeted tests plus a native Windows acceptance checklist. Next implement **v1.15.4 — Responsive KB Gallery** against the **current** `persons_workbench.py`, `person_kb_gallery.py` and `person_workbench_images.py` sources. Start by inspecting the Gallery's existing widget/layout and worker lifecycle; do not assume unreviewed details. Make original and face-crop previews responsive without re-running analyses or losing image selection, preview/cache state or staged management edits. Do not retire legacy modules or change DB/KB/bank semantics.

---

**Handoff principle:** treat v1.15.3 as the authoritative stable baseline; treat v1.15.4 as the next proposed change, not as an existing implementation.
