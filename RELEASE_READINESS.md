# Persons Workbench — Release Readiness (RC1)

Scope: read-only Persons Workbench roster, portrait service, KB Gallery, crop/quality preview,
collection/identity assessment, shortlist recommendations, and guided assessment.

## Changes in this candidate

- Release cleanup: a failed portrait job is removed from `_portrait_pending`, including stale generations.
- Added regression tests for current, obsolete, and shutdown-time failure deliveries.
- Added this operational checklist and a lightweight preflight script.
- No KB photos, person records, portrait preferences, caches, or supplied settings were edited.

## Release gate

1. Freeze a commit and record its hash, the application version from `hdw_person_lens/config.py`,
   and the package version from `pyproject.toml`.
2. Run `python release_preflight.py --settings <path-to-settings.json> --schema <path-to-person.schema.json>`.
3. In the actual Windows application environment run `python -m pytest -q tests` from the project root.
4. Run native smoke paths for workbench opening/closing, preferred portrait reset and persistence,
   gallery selection, crop/quality errors and retry, collection/identity scan, and guided shortlist.
5. Stress 20 refresh/person-switch/tab-switch cycles; confirm worker count is bounded and all child
   processes are reaped on main-window exit. Force one crop/portrait detector crash and verify retry.
6. Verify KB images and database are unchanged by assessment, except for explicitly requested
   portrait preference changes. Verify cache writes stay in the configured cache location.
7. Confirm packaging includes the required Python modules, native/model dependencies, settings,
   and schema. Confirm startup from the installed location with no project working directory.
8. Have a reviewer sign off native checks and package startup before tagging a stable build.

## Configuration and portability

- `config.py` supplies Windows-specific fallback paths. Shipping without `settings.json` can
  silently target those defaults. Always package and validate deployment-specific settings.
- The supplied `settings.json` contains machine-local paths; do not publish it unchanged.
- Settings should identify actual KB, database, and schema paths; the last two need to exist
  before opening the deployed application. Use a disposable KB copy for destructive test scenarios.
- `persons_workbench.py` is imported by `recognition_gui.py`; package discovery must include
  the analysis child entry points imported through `python -m hdw_person_lens.<module>`.

## Preflight coverage and limits

Preflight checks required UI modules, isolated child-process entry points, and their relative
Python imports. It parses source for syntax errors without importing application modules,
loading native models, or writing bytecode. It requires an existing KB directory and existing
database and schema files at absolute configured paths. The configured schema must have the
object root expected by the form; the supplied `--schema` must identify that same file.
Foreign Windows paths cannot be certified on another operating system and fail validation.

These are source and configuration checks, not full JSON Schema validation, database-content
validation, or verification of installed third-party packages and native models. Automated
regressions supplement the Windows-native smoke scenarios; they do not replace testing the
frozen distribution from its installed location. Preflight does not modify settings or user data.

## Release decision

**Conditional / not yet signed off** until the Windows-native regression suite, stress smoke,
distribution configuration, and packaged startup checks above pass on the frozen candidate.
