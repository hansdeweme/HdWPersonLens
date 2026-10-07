#kb_workers.py
# Knowledge Base Manager of face & body encodings for known people for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
import os, shutil, datetime, csv
# PyQt imports for threads
from   PyQt6.QtCore import QThread, pyqtSignal
# local imports
from  kb_utils      import _normalize_exts
from  recognition_decision import TargetMatchDecision, decide_target_match
from  config        import DEFAULT_RECOGNITION_EXTENSIONS  

#-----------------------------------------------------
# Helpers
#-----------------------------------------------------
def _target_exists_in_kb(manager, target_name: str,) -> bool:
    target = str(target_name or "").strip()
    face_names = (manager.persons.get("face_names", []) or [])
    body_names = (manager.persons.get("body_names", []) or [])
    return (target in face_names or target in body_names)

def _evaluate_target_image(*, manager, image_path: str, target_name: str, settings,):
    result = manager.recognize_image(image_path, topk=3, context="search",)
    if not isinstance(result, dict):
        raise RuntimeError("recognize_image returned a non-dictionary result." )
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return (result, decide_target_match(target_name, result, settings,),)

def _recognition_log_details(result: dict,) -> str:
    diagnostics = dict(result.get("diagnostics", {}) or {})
    face = dict(diagnostics.get("face", {}) or {})
    body = dict(diagnostics.get("body", {}) or {})
    return (
        f"final={result.get('final_name', 'Unknown')} "
        f"decision={diagnostics.get('decision', 'none')} "
        f"reason={diagnostics.get('reason', 'unknown')} "
        f"face={face.get('name')}:{face.get('score')} "
        f"face_margin={face.get('margin')} "
        f"body={body.get('name')}:{body.get('score')} "
        f"body_margin={body.get('margin')}"
    )

def _copy_with_unique_name(source_path: str, destination_directory: str,) -> str:
    os.makedirs(destination_directory, exist_ok=True,)
    filename = os.path.basename(source_path)
    destination = os.path.join(destination_directory, filename,)
    if not os.path.exists(destination):
        shutil.copy2(source_path, destination,)
        return destination
    stem, extension = os.path.splitext(filename)
    counter = 2
    while True:
        candidate = os.path.join(destination_directory, f"{stem}__{counter}{extension}", )
        if not os.path.exists(candidate):
            shutil.copy2(source_path, candidate,)
            return candidate
        counter += 1

#------------------------------------------------------
# Person Searcher Worker
#------------------------------------------------------
class PersonSearcher(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, name, folder_path, manager, settings):
        super().__init__()
        self.name = name
        self.folder_path = folder_path
        self.manager = manager
        self.settings = settings

    def run(self):
        valid_exts = _normalize_exts(DEFAULT_RECOGNITION_EXTENSIONS)
        if not os.path.isdir(self.folder_path):
            self.finished.emit(f"Search folder does not exist: {self.folder_path}")
            return
        if not _target_exists_in_kb(self.manager, self.name,):
            self.finished.emit(f"No face or body data found for '{self.name}'.")
            return
        try:
            files = sorted(filename for filename in os.listdir(self.folder_path) if (os.path.isfile(os.path.join(self.folder_path, filename,)) and filename.lower().endswith(valid_exts)))
        except Exception as exc:
            self.finished.emit(f"Could not list folder: {exc}")
            return
        total = len(files)
        if total == 0:
            self.finished.emit("No images found in selected folder.")
            return
        self.log_message.emit(f"Searching {total} images for '{self.name}' " f"in: {self.folder_path}")
        search_results_dir = os.path.join(self.folder_path, f"results_{self.name}",)
        os.makedirs(search_results_dir, exist_ok=True,)
        archive_root = (self.settings.get("person_match_output_path") or self.settings.get("persons_images_found", "", ) or "")
        run_tag = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archive_dir = (
            os.path.join(archive_root, f"{self.name}_{run_tag}",)
            if archive_root
            else ""
        )
        if archive_dir:
            os.makedirs(archive_dir, exist_ok=True,)
        matched = 0
        failed = 0
        copy_failed = 0
        self.progress.emit(0)
        for index, filename in enumerate(files, start=1,):
            path = os.path.join(self.folder_path, filename,)
            try:
                if self.isInterruptionRequested():
                    self.log_message.emit(
                        "Person search cancelled."
                    )
                    break
                result, target_decision = (
                    _evaluate_target_image(manager=self.manager, image_path=path, target_name=self.name, settings=self.settings,))
                details = _recognition_log_details(result)
                self.log_message.emit(
                    f"[Search] {filename}: "
                    f"target_match={target_decision.matched} "
                    f"target_reason={target_decision.reason} "
                    f"| {details}"
                )
                if not target_decision.matched:
                    continue
                matched += 1
                try:
                    _copy_with_unique_name(path,search_results_dir,)
                    if archive_dir:
                        _copy_with_unique_name(path, archive_dir, )
                    self.log_message.emit(
                        f"[Match] {filename} matched "
                        f"'{self.name}' via "
                        f"{target_decision.modality} "
                        f"({target_decision.reason})"
                    )
                except Exception as exc:
                    copy_failed += 1
                    self.log_message.emit(f"[Copy] {filename}: {exc}")
            except Exception as exc:
                failed += 1
                self.log_message.emit(f"[Error] {filename}: {exc}" )
            finally:
                self.progress.emit(int(100 * index / max(1, total)))
        summary = (
            f"Search for '{self.name}': "
            f"{matched} of {total} images matched, "
            f"{failed} recognition error(s), "
            f"{copy_failed} copy error(s)."
        )
        self.finished.emit(summary)

# -----------------------------------------------------------------------------
# recursive person searcher
# -----------------------------------------------------------------------------
class PersonRecursiveSearcher(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, name, root_path, manager, settings):
        super().__init__()
        self.name = name
        self.root_path = root_path
        self.manager = manager
        self.settings = settings

    def run(self):
        valid_exts = _normalize_exts(DEFAULT_RECOGNITION_EXTENSIONS)
        if not os.path.isdir(self.root_path):
            self.finished.emit(f"Search root does not exist: {self.root_path}")
            return
        if not _target_exists_in_kb(self.manager, self.name,):
            self.finished.emit(f"No face or body data found for '{self.name}'.")
            return

        root_abs = os.path.abspath(self.root_path)
        archive_root = (self.settings.get("person_match_output_path") or self.settings.get("persons_images_found", "",) or "")
        archive_root_abs = (os.path.abspath(archive_root) if archive_root else "")

        def archive_is_inside_search_root() -> bool:
            if not archive_root_abs:
                return False
            if os.path.normcase(archive_root_abs) == os.path.normcase(root_abs):
                return False
            try:
                return (os.path.commonpath([root_abs, archive_root_abs]) == root_abs)
            except ValueError:
                return False

        exclude_archive_tree = (archive_is_inside_search_root())
        all_files: list[str] = []
        for directory_path, directory_names, filenames in os.walk(root_abs):
            retained_directories = []
            for directory_name in directory_names:
                candidate = os.path.abspath(os.path.join(directory_path, directory_name,))
                # Never scan generated search results from prior runs.
                if directory_name.casefold().startswith("results_"):
                    continue
                # Do not recursively search the central archive when it
                # is located inside the selected search root.
                if (exclude_archive_tree and (os.path.normcase(candidate) == os.path.normcase(archive_root_abs) or os.path.commonpath([candidate, archive_root_abs]) == archive_root_abs)):
                    continue
                retained_directories.append(directory_name)
            directory_names[:] = retained_directories
            for filename in filenames:
                if filename.lower().endswith(valid_exts):
                    all_files.append(os.path.join(directory_path, filename,))
        all_files.sort()
        total = len(all_files)
        if total == 0:
            self.finished.emit("No images found under the selected root.")
            return
        run_tag = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        results_dir = os.path.join(root_abs,f"results_{self.name}_{run_tag}",)
        os.makedirs(results_dir, exist_ok=True,)
        archive_dir = (
            os.path.join(archive_root_abs,f"{self.name}_{run_tag}",) if archive_root_abs else "")
        if archive_dir:
            os.makedirs(archive_dir, exist_ok=True,)
        self.log_message.emit(f"[Recursive] Searching {total} images for '{self.name}' in: {root_abs}")
        matched = 0
        failed = 0
        copy_failed = 0
        self.progress.emit(0)
        for index, path in enumerate(all_files, start=1,):
            relative_path = os.path.relpath(path, root_abs,)
            display_name = relative_path
            try:
                if self.isInterruptionRequested():
                    self.log_message.emit("Recursive person search cancelled.")
                    break
                result, target_decision = (_evaluate_target_image(manager=self.manager, image_path=path, target_name=self.name, settings=self.settings, ))
                details = _recognition_log_details(result)
                self.log_message.emit(
                    f"[Recursive] {display_name}: "
                    f"target_match={target_decision.matched} "
                    f"target_reason={target_decision.reason} "
                    f"| {details}"
                )
                if not target_decision.matched:
                    continue
                matched += 1
                try:
                    result_destination = os.path.join(results_dir, relative_path, )
                    os.makedirs(os.path.dirname(result_destination), exist_ok=True,)
                    shutil.copy2(path, result_destination,)
                    if archive_dir:
                        archive_destination = os.path.join(archive_dir, relative_path,)
                        os.makedirs(os.path.dirname(archive_destination), exist_ok=True,)
                        shutil.copy2(path, archive_destination,)
                    self.log_message.emit(
                        f"[Recursive][Match] "
                        f"{display_name} matched "
                        f"'{self.name}' via "
                        f"{target_decision.modality} "
                        f"({target_decision.reason})"
                    )
                except Exception as exc:
                    copy_failed += 1
                    self.log_message.emit(f"[Recursive][Copy] " f"{display_name}: {exc}")
            except Exception as exc:
                failed += 1
                self.log_message.emit(f"[Recursive][Error] " f"{display_name}: {exc}")
            finally:
                self.progress.emit(int(100 * index / max(1, total)))
        summary = (
            f"Recursive search for '{self.name}': "
            f"{matched} of {total} images matched, "
            f"{failed} recognition error(s), "
            f"{copy_failed} copy error(s)."
        )
        self.finished.emit(summary)

# -----------------------------------------------------------------------------
# Batch processing thread
# Routes images by disposition, uses collision-safe copying, and records unified contender evidence alongside the old face/body columns
# -----------------------------------------------------------------------------           
class BatchProcessor(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    VALID_DISPOSITIONS = frozenset({"accepted", "review", "unknown"})

    def __init__(self, knowledge_manager, settings):
        super().__init__()
        self.knowledge_manager = knowledge_manager
        self.settings = settings

    @staticmethod
    def _result_pair(rows, index):
        if (
            rows is not None
            and len(rows) > index
            and isinstance(rows[index], (tuple, list))
            and len(rows[index]) >= 2
        ):
            return rows[index][0], rows[index][1]
        return "", ""

    @staticmethod
    def _contender_at(rows, index) -> dict:
        if rows is not None and len(rows) > index and isinstance(rows[index], dict):
            return rows[index]
        return {}

    @classmethod
    def _resolve_disposition(cls, result: dict, *, accepted: bool) -> str:
        """
        Read the new outcome disposition while remaining compatible with
        recognition results produced before dispositions were introduced.
        """
        disposition = str(result.get("disposition", "") or "").strip().casefold()
        if disposition in cls.VALID_DISPOSITIONS:
            return disposition
        return "accepted" if accepted else "unknown"

    @staticmethod
    def _destination_name(disposition: str, final_name: str) -> str:
        if disposition == "accepted" and final_name.casefold() != "unknown":
            return final_name
        if disposition == "review":
            return "Review"
        return "Unknown"

    def run(self):
        input_folder = str(self.settings.get("input_folder", "")).strip()
        output_folder = str(self.settings.get("output_folder", "")).strip()
        valid_exts = _normalize_exts(DEFAULT_RECOGNITION_EXTENSIONS)
        # ---------------------------------------------------------
        # Validate folders
        # ---------------------------------------------------------
        if not os.path.isdir(input_folder):
            message = f"Input folder does not exist: {input_folder}"
            self.log_message.emit(message)
            self.finished.emit(message)
            return
        try:
            os.makedirs(output_folder, exist_ok=True)
        except Exception as exc:
            message = f"Could not create output folder: {exc}"
            self.log_message.emit(message)
            self.finished.emit(message)
            return

        images = sorted(
            filename
            for filename in os.listdir(input_folder)
            if (
                os.path.isfile(os.path.join(input_folder, filename))
                and filename.lower().endswith(valid_exts)
            )
        )
        total = len(images)
        if total == 0:
            message = "No supported images found."
            self.log_message.emit(message)
            self.progress.emit(100)
            self.finished.emit(message)
            return

        # ---------------------------------------------------------
        # CSV schema
        #
        # Existing face/body columns remain because the current review
        # dialog and external reports may still consume them.
        # ---------------------------------------------------------
        fieldnames = [
            "Image",
            "Assigned Name",
            "Disposition",
            "Review Required",
            "Destination Folder",
        ]
        for contender_number in range(1, 4):
            prefix = f"Contender {contender_number}"
            fieldnames.extend(
                [
                    prefix,
                    f"{prefix} Evidence",
                    f"{prefix} Tier",
                    f"{prefix} Rank Score",
                    f"{prefix} Face Distance",
                    f"{prefix} Face Rank",
                    f"{prefix} Face Plausible",
                    f"{prefix} Body Similarity",
                    f"{prefix} Body Rank",
                    f"{prefix} Body Plausible",
                ]
            )
        fieldnames.extend(
            [
                "Face Match 1",
                "Face Score 1",
                "Face Match 2",
                "Face Score 2",
                "Face Match 3",
                "Face Score 3",
                "Body Match 1",
                "Body Score 1",
                "Body Match 2",
                "Body Score 2",
                "Body Match 3",
                "Body Score 3",
                "Decision Modality",
                "Decision Reason",
                "Accepted",
                "Face Error",
                "Body Error",
                "Face Margin",
                "Body Margin",
                "Face Status",
                "Body Status",
                "Face Strong Threshold",
                "Face Extended Threshold",
                "Face Supportable Threshold",
                "Body Support Threshold",
                "Body Alone Threshold",
                "Face Margin Minimum",
                "Face Conflict Margin Minimum",
                "Body Margin Minimum",
                "Total Time ms",
                "Copied Path",
            ]
        )

        csv_rows = []
        report_lines = []
        recognized_count = 0
        failed_count = 0
        copy_failed_count = 0
        disposition_counts = {
            "accepted": 0,
            "review": 0,
            "unknown": 0,
        }
        reason_counts = {}

        # ---------------------------------------------------------
        # Process images
        # ---------------------------------------------------------
        self.progress.emit(0)
        for index, image_file in enumerate(images, start=1):
            path = os.path.join(input_folder, image_file)
            try:
                if self.isInterruptionRequested():
                    self.log_message.emit("Batch recognition cancelled.")
                    break
                try:
                    result = self.knowledge_manager.recognize_image(
                        path,
                        topk=3,
                        context="batch",
                    )
                    if not isinstance(result, dict):
                        raise RuntimeError(
                            "recognize_image returned a non-dictionary result."
                        )
                    if result.get("error"):
                        raise RuntimeError(str(result["error"]))
                except Exception as exc:
                    failed_count += 1
                    message = f"Error processing {image_file}: {exc}"
                    self.log_message.emit(message)
                    report_lines.append(message)
                    continue

                recognized_count += 1
                final_name = str(result.get("final_name", "Unknown") or "Unknown")
                face_result = list(result.get("face_result", []) or [])
                body_result = list(result.get("body_result", []) or [])
                contenders = list(result.get("contenders", []) or [])
                diagnostics = dict(result.get("diagnostics", {}) or {})

                decision_modality = str(diagnostics.get("decision", "none"))
                decision_reason = str(diagnostics.get("reason", "unknown"))
                accepted = bool(
                    diagnostics.get("accepted", final_name.casefold() != "unknown")
                )
                disposition = self._resolve_disposition(result, accepted=accepted)
                review_required = disposition == "review"
                destination_name = self._destination_name(disposition, final_name)

                disposition_counts[disposition] += 1
                reason_counts[decision_reason] = (
                    reason_counts.get(decision_reason, 0) + 1
                )

                face_diagnostics = dict(diagnostics.get("face", {}) or {})
                body_diagnostics = dict(diagnostics.get("body", {}) or {})
                statuses = dict(diagnostics.get("status", {}) or {})
                thresholds = dict(diagnostics.get("thresholds", {}) or {})
                timings = dict(diagnostics.get("timings_ms", {}) or {})
                errors = dict(diagnostics.get("errors", {}) or {})

                # -------------------------------------------------
                # Copy result according to disposition.
                # Use the existing collision-safe helper rather than
                # overwriting a prior image with the same filename.
                # -------------------------------------------------
                copied_path = ""
                try:
                    destination_dir = os.path.join(output_folder, destination_name)
                    copied_path = _copy_with_unique_name(path, destination_dir)
                except Exception as exc:
                    copy_failed_count += 1
                    self.log_message.emit(
                        f"Copy failed for {image_file} "
                        f"to {destination_name}: {exc}"
                    )

                face_1_name, face_1_score = self._result_pair(face_result, 0)
                face_2_name, face_2_score = self._result_pair(face_result, 1)
                face_3_name, face_3_score = self._result_pair(face_result, 2)
                body_1_name, body_1_score = self._result_pair(body_result, 0)
                body_2_name, body_2_score = self._result_pair(body_result, 1)
                body_3_name, body_3_score = self._result_pair(body_result, 2)

                row = {
                    "Image": image_file,
                    # Machine-accepted identity. Review and unknown outcomes
                    # intentionally retain final_name == Unknown.
                    "Assigned Name": final_name,
                    "Disposition": disposition,
                    "Review Required": review_required,
                    "Destination Folder": destination_name,
                    "Face Match 1": face_1_name,
                    "Face Score 1": face_1_score,
                    "Face Match 2": face_2_name,
                    "Face Score 2": face_2_score,
                    "Face Match 3": face_3_name,
                    "Face Score 3": face_3_score,
                    "Body Match 1": body_1_name,
                    "Body Score 1": body_1_score,
                    "Body Match 2": body_2_name,
                    "Body Score 2": body_2_score,
                    "Body Match 3": body_3_name,
                    "Body Score 3": body_3_score,
                    "Decision Modality": decision_modality,
                    "Decision Reason": decision_reason,
                    "Accepted": accepted,
                    "Face Error": errors.get("face", ""),
                    "Body Error": errors.get("body", ""),
                    "Face Margin": face_diagnostics.get("margin", ""),
                    "Body Margin": body_diagnostics.get("margin", ""),
                    "Face Status": statuses.get("face", ""),
                    "Body Status": statuses.get("body", ""),
                    "Face Strong Threshold": thresholds.get("face_strong", ""),
                    "Face Extended Threshold": thresholds.get("face_extended", ""),
                    "Face Supportable Threshold": thresholds.get(
                        "face_supportable", ""
                    ),
                    "Body Support Threshold": thresholds.get("body_support", ""),
                    "Body Alone Threshold": thresholds.get("body_alone", ""),
                    "Face Margin Minimum": thresholds.get("face_margin_min", ""),
                    "Face Conflict Margin Minimum": thresholds.get(
                        "face_conflict_margin_min", ""
                    ),
                    "Body Margin Minimum": thresholds.get("body_margin_min", ""),
                    "Total Time ms": timings.get("total", ""),
                    "Copied Path": copied_path,
                }

                for contender_index in range(3):
                    contender = self._contender_at(contenders, contender_index)
                    prefix = f"Contender {contender_index + 1}"
                    row.update(
                        {
                            prefix: contender.get("name", ""),
                            f"{prefix} Evidence": contender.get("evidence", ""),
                            f"{prefix} Tier": contender.get("tier", ""),
                            f"{prefix} Rank Score": contender.get(
                                "rank_score", ""
                            ),
                            f"{prefix} Face Distance": contender.get(
                                "face_distance", ""
                            ),
                            f"{prefix} Face Rank": contender.get("face_rank", ""),
                            f"{prefix} Face Plausible": contender.get(
                                "face_plausible", ""
                            ),
                            f"{prefix} Body Similarity": contender.get(
                                "body_similarity", ""
                            ),
                            f"{prefix} Body Rank": contender.get("body_rank", ""),
                            f"{prefix} Body Plausible": contender.get(
                                "body_plausible", ""
                            ),
                        }
                    )

                csv_rows.append(row)

                contender_names = [
                    str(contender.get("name", ""))
                    for contender in contenders[:3]
                    if isinstance(contender, dict) and contender.get("name")
                ]
                summary = (
                    f"{image_file} -> {destination_name} "
                    f"| final={final_name} "
                    f"| disposition={disposition} "
                    f"| decision={decision_modality} "
                    f"| reason={decision_reason} "
                    f"| contenders={contender_names} "
                    f"| Face: {face_result} "
                    f"| Body: {body_result}"
                )
                self.log_message.emit(summary)
                report_lines.append(summary)
            finally:
                self.progress.emit(int(index * 100 / max(1, total)))

        # ---------------------------------------------------------
        # Summary
        # ---------------------------------------------------------
        def percentage(count: int) -> float:
            return (
                round(count / recognized_count * 100, 2)
                if recognized_count
                else 0.0
            )

        accepted_count = disposition_counts["accepted"]
        review_count = disposition_counts["review"]
        unknown_count = disposition_counts["unknown"]
        accepted_percentage = percentage(accepted_count)
        review_percentage = percentage(review_count)
        unknown_percentage = percentage(unknown_count)

        summary_line = (
            f"Summary: discovered={total}, "
            f"recognized={recognized_count}, "
            f"failed={failed_count}, "
            f"accepted={accepted_count} ({accepted_percentage:.2f}%), "
            f"review={review_count} ({review_percentage:.2f}%), "
            f"unknown={unknown_count} ({unknown_percentage:.2f}%), "
            f"copy_failed={copy_failed_count}"
        )
        report_lines.append("")
        report_lines.append(summary_line)
        if reason_counts:
            report_lines.append("")
            report_lines.append("Decision reasons:")
            for reason, count in sorted(
                reason_counts.items(),
                key=lambda item: (-item[1], item[0]),
            ):
                report_lines.append(f"  {reason}: {count}")

        # ---------------------------------------------------------
        # Save text report
        # ---------------------------------------------------------
        try:
            report_path = os.path.join(output_folder, "batch_report.txt")
            with open(report_path, "w", encoding="utf-8") as report_file:
                report_file.write("Batch Processing Report\n")
                report_file.write("=======================\n\n")
                for line in report_lines:
                    report_file.write(line + "\n")
        except Exception as exc:
            self.log_message.emit(f"Failed to save batch report: {exc}")

        # ---------------------------------------------------------
        # Save clean CSV
        # ---------------------------------------------------------
        try:
            csv_path = os.path.join(output_folder, "batch_report.csv")
            # utf-8-sig opens cleanly in Excel on Windows.
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_rows)
        except Exception as exc:
            self.log_message.emit(f"Failed to save CSV report: {exc}")

        self.finished.emit(
            f"Batch processing completed. "
            f"{recognized_count}/{total} files recognized, "
            f"{failed_count} failed, "
            f"{accepted_count} accepted, "
            f"{review_count} need review, "
            f"{unknown_count} unknown."
        )

