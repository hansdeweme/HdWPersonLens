# Duplicate engine migration (6 October 2026)

The active GUI imports `DedupConfig` from `hdw_dedup_engine`; the worker
calls `plan_duplicates(DedupRunOptions(...))` and converts `raw_summary` to
the existing UI dictionary. The five knowledge-base directory exclusions
remain intact. Report-only runs never execute moves. Action percentages
are adapted to Qt progress `(percent, 100, "moving")`. Error summaries now
display an error in the GUI rather than an empty successful scan.

## Installation

The distribution is not assumed to exist on PyPI. Install the local wheel
in the Python environment used to start the application, then install the
application requirements as usual:

```powershell
py -3.13 -m pip install D:\Coding\HdWDedupEngine\dist\hdw_dedup_engine-0.1.0-py3-none-any.whl
py -3.13 -m pip install -r requirements.txt
```

No DedupTool checkout or PYTHONPATH setting is required. To verify:

```powershell
$env:PYTHONPATH = ''
py -3.13 -c "import hdw_dedup_engine as e; import importlib.metadata as m; print(e.__file__); print(m.version('hdw-dedup-engine'))"
py -3.13 -m pytest tests/test_dedup_migration.py -q
$env:QT_QPA_PLATFORM = 'offscreen'
py -3.13 tests/smoke_dedup_gui.py
```

The smoke script creates a disposable knowledge base, starts the actual
main window, runs report-only detection and real quarantine through the GUI
worker/thread connections, then closes the window. It does not use the
configured personal dataset or load recognition model weights.

## Inventory and baseline

- Active retired imports: `dedup_worker.py` and `recognition_gui.py`.
- No active `find_duplicates`, copied engine, sys.path modification,
  PyInstaller specification, hidden imports, or packaging recipe was found.
- `previous_versions/dist-v2` is a historical source snapshot (not a frozen executable build).
  It and other folders under `previous_versions` contain standalone copied `find_duplicates.py`
  engines and historical GUI imports. These archives are retained; the current
  application does not import them. No active compatibility module needed removal.
- Historical collection scripts modify sys.path for their own script directory.
- `person_recognition-codebase.txt` is a generated pre-migration source export.
- The inherited environment had `PYTHONPATH=D:\Coding\DedupTool`; `deduptool`
  was unavailable and importing the original worker failed with
  `ModuleNotFoundError`. Migration validation clears PYTHONPATH per process;
  no global environment settings were changed.
- There was no maintained current application test suite. Archived scripts
  named test*.py are hardware/ML/manual utilities, not an automated regression
  suite for the current application, and were not executed against personal data.

## Validation

- Unmodified HdWDedupEngine suite: 79 passed before migration and 79 passed
  against the installed wheel after migration.
- Complete new current consumer suite: 9 passed (including three parametrized
  failure paths). Covers report-only behavior, all five exclusions, CSV columns
  `cluster_id,keep,path,decision`, action results `moved,skipped,failed,failures`,
  dry-run, actual quarantine, settings isolation, signal delivery on a QThread,
  and the real GUI summary/progress methods.
- Actual offscreen GUI startup, report-only scan, quarantine scan, and shutdown
  passed using disposable data.
- Validation environment installed the local wheel, with module origin under
  `.migration/venv/Lib/site-packages/hdw_dedup_engine`, and PYTHONPATH empty.
- The existing Python environment originally used an editable engine install;
  migration installation replaces it with the built distribution.

If a frozen build recipe is added later, collect `hdw_dedup_engine` (for example
`--collect-all hdw_dedup_engine`), and do not collect `deduptool`.
