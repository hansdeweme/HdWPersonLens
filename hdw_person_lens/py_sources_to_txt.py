# Read multiple Python files and combine them into a single text file
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
with (APP_DIR.parent / "person_recognition-codebase.txt").open("w", encoding="utf-8") as output_file:
    for filename in [
                    "analysis_workers.py",
                    "benchmark_pairwise_distances.py",
                    "browse_persons.py",
                    "browse_persons_custom.py",
                    "config.py",
                    "dedup_worker.py",
                    "encoding_bank_unpickler.py",
                    "find_lookalikes.py",
                    "image_drop_list.py",
                    "kb_bodies.py",
                    "kb_compare.py",
                    "kb_compatibility.py",
                    "kb_curation.py",
                    "kb_curation_dialog.py",                   
                    "kb_faces.py",
                    "kb_gallery_dialog.py",                    
                    "kb_gallery_optimizer.py",
                    "kb_initialize.py",
                    "kb_layout.py",
                    "kb_manager.py",
                    "kb_utils.py",
                    "kb_workers.py",
                    "knowledge_workers.py",
                    "legacy_kb_upgrade.py",
                    "main.py",
                    "person_db.py",
                    "person_db_gui.py",
                    "person_management_diags.py",
                    "person_service.py",
                    "recognition_contenders.py",
                    "recognition_decision.py",
                    "recognition_gui.py",
                    "recognition_gui_dialogs.py",
                    "recognition_workers.py",
                    "review_session_reporting.py",
                    "unknown_review.py",
                    "validate_persons.py",
                    "settings.json",
                    "settings_custom.json",
                    "person.schema.json"
                    ]:
        with (APP_DIR / filename).open("r", encoding="utf-8") as input_file:
            content = input_file.read()
            output_file.write(f"--- Start of {filename} ---\n")
            output_file.write(content)
            output_file.write(f"\n--- End of {filename} ---\n\n")   
