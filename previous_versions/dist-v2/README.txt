# Managing Persons in Photo Collections

A local-first desktop application for managing a person-recognition knowledge base for large photo collections.

The app helps you organize photo collections by recognizing known people, reviewing uncertain matches, curating reference images, checking knowledge-base health, and improving the quality of the recognition gallery over time.

This project grew from an earlier educational prototype into a more complete PyQt6 desktop application with a managed knowledge-base workflow.

---

## What the app does

Managing Persons in Photo Collections supports a full recognition lifecycle:

- build and maintain a local knowledge base of known people
- encode face and body/person-appearance references
- recognize people in new image folders
- review uncertain recognition results
- keep images unknown or defer them for later review
- curate candidate images before adding them to the knowledge base
- analyze and optimize reference galleries
- detect duplicate or near-duplicate images
- run compatibility checks on the knowledge base
- upgrade older knowledge bases into the new workspace layout

The app is designed around the idea that recognition quality depends on the quality of the knowledge base. More reference images are not always better. The goal is to keep useful, representative and trustworthy reference images.

---

## What this app is not

This is not a production surveillance system.

It is also not a fully automatic identity system. Recognition results can be uncertain, especially when images are blurry, old, low-resolution, partially visible, or when people look similar.

The app is intended for controlled personal, educational or research collections where the user has a legitimate reason to organize the images and understands the limits of automated recognition.

---

## Local-first workflow

The app runs locally. Your photo collection, person database, encodings and reports stay in local folders chosen by you.

No photo collection needs to be uploaded to a cloud service.

---

## Tested environment

This release was developed and tested with:

- Windows 10/11
- 64-bit CPython 3.13
- PyQt6
- NumPy
- OpenCV
- Pillow
- face_recognition / dlib
- PyTorch / TorchVision
- TorchReID

The setup commands in this README use:

```powershell
py -3.13

Using another Python version may work, but it is not the tested path. This matters because packages such as dlib, face_recognition, torch, torchvision, PyQt6 and opencv-python can be sensitive to Python version and wheel availability.

Recommended:

Python 3.13.x, 64-bit
clean virtual environment
Windows 10 or Windows 11

Not recommended:

32-bit Python
Python 3.14 unless the full dependency stack has been retested
installing into an old environment with unrelated packages

Check your installed Python versions:

py -0p
py -3.13 --version

## Installation

Clone or download the project, then open PowerShell in the project folder.

Create and activate a virtual environment:

py -3.13 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip

Install the base dependencies:

python -m pip install -r requirements-base.txt

Then install the PyTorch build that matches your machine.

CPU-only PyTorch
python -m pip install torch torchvision
NVIDIA CUDA PyTorch

Use the PyTorch install command that matches your CUDA version. For example, for CUDA 12.8 builds:

python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

DirectML / AMD optional support
For Windows DirectML support:

python -m pip install torch-directml

DirectML support is optional. If unavailable or unstable, the app can fall back to CPU for body-recognition work.

## Suggested requirements-base.txt

A practical base requirements file looks like this:

face-recognition==1.3.0
dlib==20.0.1
ImageHash==4.3.2
jsonschema==4.26.0
numpy==2.5.1
opencv-python==4.13.0.92
Pillow==12.3.0
pillow-heif==1.3.0
PyQt6==6.11.0
send2trash==2.1.0
scikit-image==0.26.0
torchreid==1.4.0

Do not include both opencv-python and opencv-contrib-python unless you know you need contrib modules.

If installation of dlib or face-recognition fails on Windows, check that you are using the tested Python version and a clean 64-bit environment.

## Starting the app

After activating the virtual environment:

python main.py


## New installation workflow

For a new knowledge base, start with an empty folder.

Recommended first setup:

Create an empty folder for the new knowledge base.
Start the app.
Open Knowledge Base → Setup / Migration → Initialize New KB.
Select the empty folder.
Add person records and trusted reference images.
Run Knowledge Base → Maintenance / Repair → Rebuild All Encodings.
Run Knowledge Base → Setup / Migration → Check KB Compatibility.
Start with a small recognition test batch.

Do not begin with the full archive. For a first test, create a small folder with 20–50 images, run recognition, inspect the review results, and only then scale up.

## Upgrading from the previous app

Users of the earlier prototype should use the upgrade workflow instead of manually copying files into the new layout.

Recommended upgrade path:

Keep a separate backup of the old knowledge-base folder.
Start the new app.
Open Knowledge Base → Setup / Migration → Import / Upgrade Legacy KB.
Select the old knowledge-base folder as the source.
Select a new destination folder for the upgraded v2 workspace.
Let the app copy the useful data.
Run Check KB Compatibility.
Run Rebuild All Encodings if the report recommends it.
Review the generated upgrade and compatibility reports.

The upgrade workflow should copy data into a new v2 workspace. It should not modify the old knowledge base in place.

Old encoding banks may lack newer metadata, especially body-recognition pipeline metadata. If the compatibility report mentions missing or incompatible metadata, rebuild all encodings.


## Knowledge-base workspace layout

The old prototype used a simple folder layout:

persons_dataset/
├── Alice/
│   ├── image1.jpg
│   └── image2.jpg
├── Bob/
│   ├── image1.jpg
│   └── image2.jpg
└── encodings.pkl

The new app uses a managed workspace:

knowledge_base/
├── Alice/
├── Bob/
├── encodings.pkl
├── persons.json
├── person.schema.json
├── .kb_version.json
├── batch_sessions/
├── review_sessions/
├── kb_curation/
├── gallery_reports/
├── kb_compatibility/
├── dedup_reports/
└── upgrade_reports/

Person folders contain trusted reference images.

System folders contain reports, review sessions, curation data, compatibility output and upgrade artifacts.

Initialization creates the workspace. It does not mean “scan a random folder and treat every subfolder as a valid person.”


## Main menu structure

The Knowledge Base menu is organized around the lifecycle of the app:

Knowledge Base
├── Setup / Migration
│   ├── Initialize New KB
│   ├── Import / Upgrade Legacy KB
│   └── Check KB Compatibility
│
├── Curation / Optimization
│   ├── Curate Recognition Candidates
│   └── Analyze and Optimize KB Gallery
│
├── Maintenance / Repair
│   ├── Repair DB / KB Folder Consistency
│   ├── Rebuild All Encodings
│   ├── Find Duplicate Images
│   └── Quarantine Duplicate Images
│
└── Diagnostics / Reports
    ├── Show Knowledge Base Stats
    ├── Media Folder Report
    └── Analyze Recognition Thresholds


## Person database

The new app uses a JSON-backed person database:

persons.json

This file stores structured information about known people, such as:

display name
alternate names
media folder path
notes
tags
custom user fields

The exact structure is controlled by:

person.schema.json
Schema-driven person records

The app uses JSON Schema to define the person database fields.

A minimal public starter schema might contain:

{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Person",
  "type": "object",
  "properties": {
    "#person_id": { "type": "string" },
    "personName": { "type": "string" },
    "otherName": { "type": "string" },
    "files_path": { "type": "string" },
    "notes": { "type": "string" },
    "tags": { "type": "array", "items": { "type": "string" } },
    "active": { "type": "boolean", "default": true }
  },
  "required": ["personName"]
}

Users can extend the schema for their own collection.

Examples:

family archive: relationship, generation, birth year, family branch
sports archive: team, season, role, shirt number
research archive: source collection, consent status, review status, annotation notes
media-management workflow: priority, category, collection path, known aliases

The recognition engine does not need to know every metadata field. The database editor does not need to know the biometric implementation details. The person service coordinates the database, knowledge-base folders and encoding operations behind the scenes.

Query Persons roster view

The schema controls what fields exist and how person records are edited.

The Query Persons dialog is a roster view. It shows selected fields from persons.json, plus a preview image where available.

The roster columns can be configured through settings.json.

Example:

{
  "query_persons_view": {
    "columns": [
      ["personName", "Name"],
      ["otherName", "Other name"],
      ["rating", "Rating"],
      ["birth date", "Birth date"],
      ["birth_place", "Birth place"],
      ["ethnicity", "Ethnicity"],
      ["colors.skin", "Skin"],
      ["colors.hair", "Hair"],
      ["dimensions.length", "Len"],
      ["dimensions.weight", "Wgt"]
    ],
    "default_sort": {
      "path": "personName",
      "order": "asc"
    },
    "dynamic_columns": true,
    "max_dynamic_columns": 6,
    "preview": true
  }
}

This keeps person.schema.json focused on the data model and settings.json focused on application preferences.


## Typical workflow

A normal workflow might look like this:

Add or update person records.
Add trusted reference images to person folders.
Rebuild encodings.
Run recognition on a folder of unknown images.
Review recognition results.
Assign known people, keep images unknown, or defer uncertain cases.
Promote only good candidates into the knowledge base.
Periodically optimize the KB gallery.
Periodically run duplicate detection.
Re-run compatibility checks after structural changes.

The knowledge base is not meant to be a dumping ground. It is curated.

## Duplicate detection

The app includes duplicate and near-duplicate detection based on the standalone Dedup workflow.

Two separate actions are available:

Find Duplicate Images

Runs a dry-run analysis and writes a visual report.

Quarantine Duplicate Images

Moves non-keeper files into a dedicated quarantine folder after confirmation.

The app does not automatically delete duplicate files.


## Safer encoding-bank handling

The app still supports the existing encodings.pkl format, but pickle loading is handled cautiously.

A pickle file should not be treated like a harmless data file. Python pickle can execute code if a file is malicious.

For normal use:

encoding banks created by the app should load normally
old or incompatible banks should not be overwritten automatically
if safe loading fails, rebuild all encodings
longer-term, the project may move to a safer format such as NumPy .npz plus JSON metadata


## Architecture overview

The app is structured in layers:

GUI
 ↓
Workers
 ↓
Services / Managers
 ↓
Engines
 ↓
Knowledge Base / Reports / Metadata

The GUI handles menus, dialogs, review screens, progress display and confirmations.

Workers run long-running tasks without blocking the main window.

Services and managers coordinate application logic.

Engines perform recognition, comparison, hashing, duplicate grouping, threshold analysis and reporting.

The knowledge base stores persistent artifacts: reference images, encodings, person records, reports and review-session output.

## Main components

Important project files include:

recognition_gui.py        Main window, menus, tabs, GUI orchestration
person_service.py         Coordinates person DB and biometric KB operations
person_db.py              JSON-backed person catalog
person_db_gui.py          Schema-driven person editor
kb_manager.py             Encoding-bank and KB operations
analysis_workers.py       Long-running recognition / comparison / analysis workers
knowledge_workers.py      Re-encoding workers
kb_compatibility.py       KB validation and compatibility reports
kb_curation.py            Candidate store and promotion/rejection logic
kb_gallery_optimizer.py   Reference-gallery analysis and optimization
find_duplicates.py        Duplicate detection, reporting and quarantine support
kb_layout.py              Shared KB folder-layout rules
kb_initialize.py          New v2 KB workspace creation
legacy_kb_upgrade.py      Legacy KB import/upgrade workflow


## Troubleshooting
dlib or face_recognition does not install

Use the tested Python version and a clean virtual environment.

py -3.13 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip

If installation still fails, check whether a compatible dlib wheel is available for your Python version and platform.

PyQt starts but recognition fails

Check that the correct virtual environment is active and that all dependencies are installed:

python -m pip list
Existing encodings.pkl cannot be loaded safely

Do not overwrite it manually.

Start the app if possible and run:

Knowledge Base → Maintenance / Repair → Rebuild All Encodings

If this happens during upgrade, check the compatibility report and rebuild the encoding bank in the new v2 workspace.

The app sees system folders as persons

Run: Knowledge Base → Setup / Migration → Check KB Compatibility

The v2 workspace uses system folders such as review_sessions, kb_curation, gallery_reports, kb_compatibility, dedup_reports and upgrade_reports. These should not be treated as person folders.

Torch / GPU memory issues

If GPU acceleration is unstable, use CPU mode or disable the relevant acceleration setting. Long-running body-recognition or re-encoding jobs can use substantial memory.


## Recommended first test

Before processing a full archive:

Create a small test folder with 20–50 images.
Run recognition.
Review the results.
Check unknown and deferred cases.
Tune thresholds if needed.
Rebuild encodings after changing reference images.
Only then scale up to a larger folder.


## Privacy and responsibility

This app works with person-recognition data. Use it only on collections where you have a legitimate reason to organize the images.

Respect privacy, consent and applicable laws in your location.

## License

MIT License.
