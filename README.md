# HdW PersonLens

PersonLens is a Python/PyQt6 desktop application for managing a knowledge base
of people and recognizing them in photo collections. It supports face and body
comparison, person database management, knowledge-base curation, and duplicate
image review.

## Repository layout

- `hdw_person_lens/`: current application source and person schema.
- `tests/`: automated regression tests and an offscreen GUI smoke test.
- `docs/`: technical notes, articles, and supporting assets.
- `previous_versions/`: historical source snapshots; these are not the active app.
- `requirements.txt`: current dependency snapshot. The other requirements files
  record machine-specific working environments.

## Setup and launch

The application currently runs as a collection of scripts, rather than an
installable Python package. Use Python 3.13 on Windows and run commands from
the repository root.

Install the local HdWDedupEngine wheel before the application dependencies.
See [duplicate engine installation](docs/DEDUP_MIGRATION.md).
The dependency snapshot includes GPU and platform-specific packages; choose
the PyTorch build appropriate to your machine.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item hdw_person_lens/settings.example.json hdw_person_lens/settings.json
python hdw_person_lens/main.py
```

Edit `hdw_person_lens/settings.json` to point to your input, output, knowledge
base, database, and schema locations. Relative application data paths resolve
from `hdw_person_lens/`. Settings load and save beside the application.
The GUI provides knowledge-base initialization and management.

Personal datasets, database records, model weights, local settings, generated
exports, and caches are excluded from version control.

## Verification

Install `pytest` in the application environment, then run:

```powershell
python -m pytest -q
$env:QT_QPA_PLATFORM = 'offscreen'
python tests/smoke_dedup_gui.py
```

The current regression suite covers duplicate processing. The smoke test uses
a disposable knowledge base for startup, report-only scanning, quarantine,
and shutdown. Historical manual and hardware-specific test scripts are not
collected by pytest.

## License

MIT. See [LICENSE](LICENSE).
