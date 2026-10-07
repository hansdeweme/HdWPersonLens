#person_service.py
# PersnService single point of coordination for person operations across the database, knowledge base, and optional photo folders. 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
# Coordinated person operations across:
# - PersonDB
# - knowledge-base folders
# - encodings.pkl
# - optional photo-collection folders
#
#----------------------------------------------------------------
# Note: The add operation deliberately requires a complete Persons DB record to exist first. 
# The schema contains required fields 
# so silently creating {"personName": name} would introduce an invalid database record.
#----------------------------------------------------------------
from __future__ import annotations
import copy
import os
import shutil
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tempfile
import threading

class PersonServiceError(RuntimeError):
    """Base error for coordinated person operations."""

class PersonNotFoundError(PersonServiceError):
    """Raised when a requested person does not exist."""

class PersonConflictError(PersonServiceError):
    """Raised when a target name or folder already exists."""

@dataclass(frozen=True)
class PersonOperationResult:
    operation: str
    name: str
    previous_name: str | None = None
    database_changed: bool = False
    database_record_exists: bool = False
    knowledge_base_changed: bool = False
    photo_folder_changed: bool = False
    face_encodings: int = 0
    body_encodings: int = 0
    images_processed: int = 0
    images_added: int = 0
    images_removed: int = 0
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class ReencodeBatchResult:
    requested: tuple[str, ...]
    completed: tuple[PersonOperationResult, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()
    cancelled: bool = False

@dataclass(frozen=True)
class UnknownReviewResult:
    assigned_images: int = 0
    updated_persons: tuple[str, ...] = ()
    successful_sources: tuple[str, ...] = ()
    failed_persons: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class PersonState:
    name: str
    database_record_exists: bool
    knowledge_base_folder_exists: bool
    face_encodings: int
    body_encodings: int
    image_count: int

    @property
    def has_encodings(self) -> bool:
        return self.face_encodings > 0 or self.body_encodings > 0

    @property
    def has_recognition_state(self) -> bool:
        return self.knowledge_base_folder_exists or self.has_encodings

    @property
    def has_complete_recognition_profile(self) -> bool:
        return self.knowledge_base_folder_exists and self.has_encodings and self.image_count > 0


class PersonService:
    def __init__(self, *, person_db: Any, knowledge_manager: Any, settings: Mapping[str, Any], logger: Callable[[str], None] | None = None, ) -> None:
        self.person_db = person_db
        self.knowledge_manager = knowledge_manager
        self.settings = settings
        self.logger = logger
        self._operation_lock = threading.RLock()
    # ---------------------------------------------------------
    # General helpers
    # ---------------------------------------------------------
    @staticmethod
    def _clean_name(name: str) -> str:
        return " ".join(str(name or "").split()).strip()

    @staticmethod
    def _same_path(first: str | Path, second: str | Path,) -> bool:
        return (os.path.normcase(os.path.abspath(os.fspath(first))) == os.path.normcase(os.path.abspath(os.fspath(second))))

    def _log(self, message: str) -> None:
        if callable(self.logger):
            self.logger(message)

    def _kb_folder(self, name: str) -> Path:
        getter = getattr(
            self.knowledge_manager,
            "get_person_folder",
            None,
        )
        if callable(getter):
            return Path(getter(name))
        return Path(
            self.settings["knowledge_base"]
        ) / name

    def _encoding_names(self) -> set[str]:
        getter = getattr(
            self.knowledge_manager,
            "get_encoding_names",
            None,
        )
        if callable(getter):
            return set(getter())
        persons = (self.knowledge_manager.persons)
        names = set(persons.get("face_names", []) or [])
        names.update(persons.get("body_names", []) or [])
        return names

    def _snapshot_encodings(self) -> dict:
        return copy.deepcopy(self.knowledge_manager.persons)

    def _restore_encodings(self, snapshot: dict, ) -> None:
        self.knowledge_manager.persons = snapshot
        self.knowledge_manager.save_encodings()

    def _person_record(self, name: str, ) -> dict | None:
        return self.person_db.get_by_name(name)

    def person_exists_anywhere(self, name: str, ) -> bool:
        name = self._clean_name(name)
        return any(
            (
                self._person_record(name)
                is not None,
                name in self._encoding_names(),
                self._kb_folder(name).exists(),
            )
        )

    def get_person_state(self, name: str) -> PersonState:
        name = self._clean_name(name)
        folder = self._kb_folder(name)
        face_count, body_count = self._encoding_counts(name)
        return PersonState(
            name=name,
            database_record_exists=self._person_record(name) is not None,
            knowledge_base_folder_exists=folder.is_dir(),
            face_encodings=face_count,
            body_encodings=body_count,
            image_count=len(self.get_person_image_paths(name)),
        )

    def find_recognition_name(self, name: str) -> str | None:
        key = self._clean_name(name).casefold()
        for existing_name in self.list_recognition_names():
            if self._clean_name(existing_name).casefold() == key:
                return existing_name
        return None

    def list_person_names(self) -> list[str]:
        """
        Return every person name known by the database,
        encodings, or knowledge-base folders.
        """
        names = set(self.person_db.keys())
        names.update(self._encoding_names())
        kb_root = Path(str(self.settings.get("knowledge_base", "", )))
        if kb_root.is_dir():
            try:
                names.update(
                    item.name
                    for item in kb_root.iterdir()
                    if item.is_dir()
                )
            except OSError:
                pass
        return sorted(names, key=lambda name: (name.casefold(), name,),)

    def get_person_record( self, name: str, ) -> dict | None:
        """
        Return a defensive copy of a person's database record.
        """
        record = self._person_record(self._clean_name(name))
        return (copy.deepcopy(record) if record is not None else None)

    def suggest_photo_folder(self, old_name: str, new_name: str,) -> str | None:
        """
        Suggest a sibling photo folder using the new person's name.
        """
        record = self.get_person_record(old_name)
        if not record:
            return None
        current_path = str(record.get("files_path", "")).strip()
        new_name = self._clean_name(new_name)
        if not current_path or not new_name:
            return None
        return str(
            Path(current_path).with_name(new_name)
        )

    def _valid_extensions(self) -> set[str]:
        raw_extensions = self.settings.get("valid_extensions",[".jpg", ".jpeg", ".png", ".webp"], ) or [] 
        extensions = set()
        for raw in raw_extensions:
            extension = str(raw).strip().lower()
            if not extension:
                continue
            extensions.add(extension if extension.startswith(".") else f".{extension}")
        return extensions

    def list_recognition_names(self) -> list[str]:
        """Return persons represented by encodings or a KB folder."""
        names = set(self._encoding_names())
        root = Path(str(self.settings.get("knowledge_base", ""))).expanduser()
        if root.is_dir():
            names.update(path.name for path in root.iterdir() if path.is_dir() and ".pending-delete-" not in path.name)
        return sorted(names, key=lambda value: (value.casefold(), value))

    def get_person_image_paths(self, name: str) -> list[str]:
        """Return the usable images directly inside a person's KB folder."""
        folder = self._kb_folder(self._clean_name(name))
        extensions = self._valid_extensions()
        if not folder.is_dir():
            return []
        paths = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in extensions]
        paths.sort(key=lambda path: (path.name.casefold(), path.name))
        return [str(path) for path in paths]

    def is_in_knowledge_base(self, name: str) -> bool:
        name = self._clean_name(name)
        canonical_name = self.find_recognition_name(name)
        if canonical_name is not None:
            return True
        return self._kb_folder(name).is_dir()

    def list_add_candidates(self) -> list[str]:
        """Return DB persons that do not yet have recognition state."""
        self.person_db.reload_if_changed()
        names = [name for name in self.person_db.keys() if not self.get_person_state(name).has_recognition_state]
        return sorted(names, key=lambda value: (value.casefold(), value))

    # ---------------------------------------------------------
    # Add
    # ---------------------------------------------------------
    def add_to_knowledge_base(self, *, name: str, images: Sequence[str], on_log: Callable[[str], None] | None = None, on_progress: Callable[[int], None] | None = None,) -> PersonOperationResult:
        """
        Create a recognition profile for a person.
        A Persons DB record is optional. If one already exists, the returned
        result reports this through database_record_exists. This method does
        not create or modify a Persons DB record.
        The operation adds:
        - the person's knowledge-base folder;
        - selected training images;
        - face and/or body encodings.
        If the operation fails, the previous encoding state is restored and
        a newly created knowledge-base folder is removed.
        """
        name = self._clean_name(name)
        if not name:
            raise ValueError("Person name cannot be empty.")
        # Normalize and deduplicate image paths while preserving order.
        image_paths: list[str] = []
        seen_paths: set[str] = set()
        for image in images:
            raw_path = str(image or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            normalized_path = os.path.normcase(
                os.path.abspath(os.fspath(path)  ))
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            image_paths.append(os.path.abspath(os.fspath(path)))
        if not image_paths:
            raise ValueError("At least one image is required.")
        missing_images = [path for path in image_paths if not os.path.isfile(path)]
        if missing_images:
            displayed_paths = "\n".join(missing_images[:10])
            additional_count = (len(missing_images) - 10)
            if additional_count > 0:
                displayed_paths += (f"\n...and {additional_count} more.")
            raise PersonServiceError("One or more selected image files " "could not be found:\n" f"{displayed_paths}" )
        # Recognition is authoritative for this operation.
        # A database record is optional.
        database_record = self._person_record(name)
        if self.is_in_knowledge_base(name):
            raise PersonConflictError(f"{name!r} already has a recognition " "profile in the knowledge base.")
        knowledge_base_folder = self._kb_folder(name)
        folder_existed_before = (knowledge_base_folder.exists())
        encoding_snapshot = (self._snapshot_encodings())
        face_names_before = list(self.knowledge_manager.persons.get("face_names", [],) or [] )
        body_names_before = list(self.knowledge_manager.persons.get("body_names", [],) or [] )
        face_count_before = sum(existing_name == name for existing_name in face_names_before )
        body_count_before = sum(existing_name == name for existing_name in body_names_before )

        def emit_log(message: str) -> None:
            """
            Prefer the operation callback because it may be a Qt signal
            crossing from a worker thread to the GUI thread.
            """
            if callable(on_log):
                on_log(message)
            else:
                self._log(message)
        emit_log(f"[PersonService] Creating recognition " f"profile for {name!r} from " f"{len(image_paths)} image(s)." )
        try:
            self.knowledge_manager.add_person(name, image_paths, on_log=on_log, on_progress=on_progress,)
            face_names_after = (self.knowledge_manager.persons.get("face_names", [], )
                or []
            )
            body_names_after = (self.knowledge_manager.persons.get("body_names", [], )
                or []
            )
            face_count_after = sum(existing_name == name for existing_name in face_names_after)
            body_count_after = sum(existing_name == name for existing_name in body_names_after )
            faces_added = max(0, face_count_after - face_count_before,)
            bodies_added = max(0, body_count_after - body_count_before,)
            if (faces_added == 0 and bodies_added == 0):
                raise PersonServiceError("No usable face or body encodings " f"were created for {name!r}.")
            if not knowledge_base_folder.exists():
                raise PersonServiceError("The recognition operation completed " "without creating the expected " "knowledge-base folder:\n" f"{knowledge_base_folder}"  )
        except Exception as original_error:
            rollback_errors: list[str] = []
            try:
                self._restore_encodings(encoding_snapshot)
            except Exception as rollback_error:
                rollback_errors.append("Could not restore the previous " "encoding state: " f"{rollback_error}" )
            if (not folder_existed_before and knowledge_base_folder.exists()):
                try:
                    shutil.rmtree(
                        knowledge_base_folder
                    )
                except Exception as rollback_error:
                    rollback_errors.append(
                        "Could not remove the incomplete "
                        "knowledge-base folder "
                        f"{knowledge_base_folder}: "
                        f"{rollback_error}"
                    )
            rollback_detail = ""
            if rollback_errors:
                rollback_detail = (
                    "\n\nRollback issues:\n"
                    + "\n".join(
                        f"• {issue}"
                        for issue in rollback_errors
                    )
                )
            if isinstance(original_error, PersonServiceError):
                raise PersonServiceError(
                    f"{original_error}"
                    f"{rollback_detail}"
                ) from original_error
            raise PersonServiceError("Could not add the recognition profile " f"for {name!r}: {original_error}" f"{rollback_detail}" ) from original_error
        emit_log(f"[PersonService] Added recognition profile " f"for {name!r}: {faces_added} face and " f"{bodies_added} body encoding(s).")
        if database_record is None:
            emit_log(f"[PersonService] No Persons DB record " f"exists yet for {name!r}.")
        else:
            emit_log(f"[PersonService] Existing Persons DB " f"record found for {name!r}."
            )
        return PersonOperationResult(
            operation="add",
            name=name,
            database_changed=False,
            database_record_exists=(
                database_record is not None
            ),
            knowledge_base_changed=True,
            photo_folder_changed=False,
            face_encodings=faces_added,
            body_encodings=bodies_added,
        )
    
    # ---------------------------------------------------------
    # Rename
    # ---------------------------------------------------------
    def rename_person(self, *, old_name: str, new_name: str, rename_photo_folder: bool = False, new_photo_path: str | None = None, ) -> PersonOperationResult:
        old_name = self._clean_name(old_name)
        new_name = self._clean_name(new_name)
        if not old_name or not new_name:
            raise ValueError("Both old and new names are required." )
        if old_name == new_name:
            raise ValueError("The new name must be different.")
        db_record = self._person_record(old_name)
        old_kb_folder = self._kb_folder(old_name)
        new_kb_folder = self._kb_folder(new_name)
        old_in_encodings = (old_name in self._encoding_names() )
        if (db_record is None and not old_in_encodings and not old_kb_folder.exists()):
            raise PersonNotFoundError( f"{old_name!r} was not found.")
        if self._person_record(new_name):
            raise PersonConflictError(f"A database record named " f"{new_name!r} already exists.")
        if new_name in self._encoding_names():
            raise PersonConflictError(f"{new_name!r} already exists in ""the encodings.")
        if new_kb_folder.exists():
            raise PersonConflictError(f"Knowledge-base folder already "f"exists:\n{new_kb_folder}" )
        old_photo_path: Path | None = None
        target_photo_path: Path | None = None
        if rename_photo_folder:
            if db_record is None:
                raise PersonNotFoundError("The person has no database record, " "so files_path cannot be resolved.")
            raw_photo_path = str(db_record.get("files_path", "",)).strip()
            if not raw_photo_path:
                raise PersonServiceError("The database record has no ""files_path.")
            old_photo_path = Path(raw_photo_path)
            if not old_photo_path.is_dir():
                raise PersonServiceError("Photo folder does not exist:\n"f"{old_photo_path}")
            target_photo_path = (Path(new_photo_path) if new_photo_path else old_photo_path.with_name(new_name))
            if (not self._same_path(old_photo_path, target_photo_path,) and target_photo_path.exists()):
                raise PersonConflictError("Target photo folder already " f"exists:\n{target_photo_path}" )
        encoding_snapshot = (self._snapshot_encodings())
        kb_moved = False
        photo_moved = False
        db_renamed = False
        try:
            if old_kb_folder.exists():
                shutil.move(str(old_kb_folder), str(new_kb_folder),)
                kb_moved = True
            face_count, body_count = (self.knowledge_manager.rename_encoding_labels(old_name, new_name, ))
            self.knowledge_manager.save_encodings()
            if (old_photo_path is not None and target_photo_path is not None and not self._same_path(old_photo_path, target_photo_path,)):
                shutil.move(str(old_photo_path), str(target_photo_path),)
                photo_moved = True
            if db_record is not None:
                if not self.person_db.rename_person(old_name, new_name,):
                    raise PersonServiceError("Could not rename the database record.")
                db_renamed = True
                if (photo_moved and target_photo_path is not None):
                    if not self.person_db.update_fields(new_name, files_path=str(target_photo_path),):
                        raise PersonServiceError("Could not update files_path.")
        except Exception as original_error:
            rollback_errors: list[str] = []
            if db_renamed:
                try:
                    self.person_db.rename_person(new_name, old_name,)
                    if old_photo_path is not None:
                        self.person_db.update_fields(old_name, files_path=str(old_photo_path),)
                except Exception as exc:
                    rollback_errors.append(f"database rollback: {exc}")
            try:
                self._restore_encodings(encoding_snapshot)
            except Exception as exc:
                rollback_errors.append(f"encoding rollback: {exc}")
            if (photo_moved and target_photo_path and target_photo_path.exists() ):
                try:
                    shutil.move(str(target_photo_path), str(old_photo_path),)
                except Exception as exc:
                    rollback_errors.append(f"photo rollback: {exc}")
            if (kb_moved and new_kb_folder.exists()):
                try:
                    shutil.move(str(new_kb_folder), str(old_kb_folder), )
                except Exception as exc:
                    rollback_errors.append(f"KB rollback: {exc}" )
            detail = ("\nRollback issues:\n" + "\n".join(rollback_errors) if rollback_errors else "")
            raise PersonServiceError(f"Rename failed: {original_error}" f"{detail}") from original_error
        self._log(
            f"[PersonService] Renamed " f"{old_name} -> {new_name}." )
        return PersonOperationResult(
            operation="rename",
            name=new_name,
            previous_name=old_name,
            database_changed=db_renamed,
            knowledge_base_changed=(
                kb_moved
                or face_count > 0
                or body_count > 0
            ),
            photo_folder_changed=photo_moved,
            face_encodings=face_count,
            body_encodings=body_count,
        )

    # ---------------------------------------------------------
    # Remove
    # ---------------------------------------------------------
    def remove_person(self, *, name: str, remove_database_record: bool = True, delete_photo_folder: bool = False, ) -> PersonOperationResult:
        name = self._clean_name(name)
        if not name:
            raise ValueError("Person name cannot be empty.")
        db_record = self._person_record(name)
        kb_folder = self._kb_folder(name)
        in_encodings = (name in self._encoding_names())
        if (db_record is None and not kb_folder.exists() and not in_encodings):
            raise PersonNotFoundError(f"{name!r} was not found.")
        photo_folder: Path | None = None
        if delete_photo_folder and db_record:
            raw_path = str(db_record.get("files_path", "",)).strip()
            if raw_path:
                photo_folder = Path(raw_path)
        encoding_snapshot = (self._snapshot_encodings())
        staged_folders: list[tuple[Path, Path]] = []
        database_deleted = False

        def stage_folder(folder: Path | None, ) -> None:
            if (folder is None or not folder.exists()):
                return
            for original, _pending in staged_folders:
                if self._same_path(original, folder, ):
                    return
            pending = folder.with_name("." + folder.name + ".pending-delete-" + uuid.uuid4().hex)
            shutil.move(str(folder), str(pending),)
            staged_folders.append((folder, pending))
        try:
            stage_folder(kb_folder)
            if delete_photo_folder:
                stage_folder(photo_folder)
            face_count, body_count = (self.knowledge_manager.remove_person_encodings(name))
            self.knowledge_manager.save_encodings()
            if (remove_database_record and db_record is not None):
                if not self.person_db.delete_by_name(name):
                    raise PersonServiceError("Could not delete the database record.")
                database_deleted = True
        except Exception as original_error:
            rollback_errors: list[str] = []
            if (database_deleted and db_record is not None):
                try:
                    self.person_db.upsert(db_record, original_name=None,)
                except Exception as exc:
                    rollback_errors.append(f"database rollback: {exc}")
            try:
                self._restore_encodings(encoding_snapshot)
            except Exception as exc:
                rollback_errors.append(f"encoding rollback: {exc}")
            for original, pending in reversed(staged_folders):
                if pending.exists():
                    try:
                        shutil.move(str(pending), str(original),)
                    except Exception as exc:
                        rollback_errors.append(f"folder rollback: {exc}")
            detail = ("\nRollback issues:\n" + "\n".join(rollback_errors) if rollback_errors else "" )
            raise PersonServiceError(f"Removal failed: {original_error}" f"{detail}") from original_error
        warnings: list[str] = []
        for _original, pending in staged_folders:
            try:
                shutil.rmtree(pending)
            except Exception as exc:
                warnings.append("Could not permanently delete " f"{pending}: {exc}")
        self._log(f"[PersonService] Removed {name}.")
        return PersonOperationResult(
            operation="remove",
            name=name,
            database_changed=database_deleted,
            knowledge_base_changed=True,
            photo_folder_changed=(
                delete_photo_folder
                and photo_folder is not None
            ),
            face_encodings=face_count,
            body_encodings=body_count,
            warnings=tuple(warnings),
        )

#-------------------------------------
# Update Person Images
#-------------------------------------
    def update_person_images(self,  *, name: str, add_images: Sequence[str] = (), remove_images: Sequence[str] = (), on_log: Callable[[str], None] | None = None, on_progress: Callable[[int], None] | None = None, ) -> PersonOperationResult:
        """
        Apply image additions and removals transactionally, then re-encode.
        New files are copied into a staging folder first. Removed files are
        moved into that staging folder instead of being deleted immediately.
        If copying, re-encoding, or persistence fails, files and encodings
        are restored.
        """
        with self._operation_lock:
            name = self._clean_name(name)
            if not name:
                raise ValueError("Person name cannot be empty.")
            folder = self._kb_folder(name)
            if not folder.is_dir():
                raise PersonNotFoundError(
                    f"Knowledge-base folder not found for {name!r}:\n{folder}"
                )
            extensions = self._valid_extensions()

            def path_key(path: str | Path) -> str:
                return os.path.normcase(os.path.abspath(os.fspath(path)))
            folder_key = path_key(folder)
            def inside_person_folder(path: Path) -> bool:
                try:
                    return os.path.commonpath([folder_key, path_key(path)]) == folder_key
                except ValueError:
                    return False

            current = {path_key(path): Path(path) for path in self.get_person_image_paths(name) }
            additions: dict[str, Path] = {}
            removals: dict[str, Path] = {}

            for raw_path in add_images:
                path = Path(str(raw_path)).expanduser().resolve()
                if not path.is_file():
                    raise PersonServiceError(f"Image file not found:\n{path}")
                if path.suffix.lower() not in extensions:
                    raise PersonServiceError(f"Unsupported image type:\n{path}")
                additions.setdefault(path_key(path), path)

            for raw_path in remove_images:
                path = Path(str(raw_path)).expanduser().resolve()
                key = path_key(path)
                if not inside_person_folder(path):
                    raise PersonServiceError(f"Refusing to remove a file outside the person's KB folder:\n{path}")
                if key not in current:
                    raise PersonServiceError(f"Knowledge-base image not found:\n{path}")
                removals[key] = current[key]
            # Adding an existing KB file is a no-op. Adding and removing the
            # same existing file in one request cancels both operations.
            for key in set(additions) & set(current):
                additions.pop(key, None)
                removals.pop(key, None)
            if not additions and not removals:
                raise ValueError("No effective image changes were supplied.")
            final_image_count = len(current) - len(removals) + len(additions)
            if final_image_count < 1:
                raise PersonServiceError("The operation would leave the person without any knowledge-base images.")
            snapshot = self._snapshot_encodings()
            # Keep staging inside the person's folder. The current recognition
            # implementation reads only files directly in that folder, so these
            # staging subfolders are ignored during re-encoding.
            transaction_dir = Path(tempfile.mkdtemp(prefix=".image-edit-", dir=str(folder)))
            additions_stage = transaction_dir / "added"
            removals_stage = transaction_dir / "removed"
            additions_stage.mkdir()
            removals_stage.mkdir()
            reserved_names = {path.name.casefold() for key, path in current.items() if key not in removals}
            addition_plan: list[tuple[Path, Path, Path]] = []
            staged_removals: list[tuple[Path, Path]] = []
            installed_additions: list[Path] = []

            def unique_target_name(source: Path) -> str:
                candidate = source.name
                index = 1
                while candidate.casefold() in reserved_names:
                    candidate = f"{source.stem}__{index}{source.suffix}"
                    index += 1
                reserved_names.add(candidate.casefold())
                return candidate
            for index, source in enumerate(additions.values(), start=1):
                target_name = unique_target_name(source)
                staged = additions_stage / f"{index:04d}_{target_name}"
                target = folder / target_name
                addition_plan.append((source, staged, target))

            manager = self.knowledge_manager
            log_connected = False
            progress_connected = False

            def emit_log(message: str) -> None:
                if callable(on_log):
                    on_log(message)
                else:
                    self._log(message)
            try:
                if callable(on_log) and hasattr(manager, "progress_signal"):
                    manager.progress_signal.connect(on_log)
                    log_connected = True
                if callable(on_progress) and hasattr(manager, "progress_update"):
                    manager.progress_update.connect(on_progress)
                    progress_connected = True
                emit_log(f"[PersonService] Updating {name!r}: " f"+{len(addition_plan)} / -{len(removals)} image(s)." )
                # Copy all additions before touching the live folder.
                for source, staged, _target in addition_plan:
                    shutil.copy2(source, staged)
                # Move removals aside so they remain recoverable.
                for index, original in enumerate(removals.values(), start=1):
                    staged = removals_stage / f"{index:04d}_{original.name}"
                    shutil.move(str(original), str(staged))
                    staged_removals.append((staged, original))
                # Install additions into the live folder.
                for _source, staged, target in addition_plan:
                    shutil.move(str(staged), str(target))
                    installed_additions.append(target)
                reencode_result = self.reencode_person(name=name, on_log=on_log, on_progress=on_progress,)
                face_count = reencode_result.face_encodings
                body_count = reencode_result.body_encodings
                if face_count == 0 and body_count == 0:
                    raise PersonServiceError(
                        f"Re-encoding produced no face or body encodings for {name!r}."
                    )
            except Exception as original_error:
                rollback_errors: list[str] = []
                try:
                    self._restore_encodings(snapshot)
                except Exception as exc:
                    rollback_errors.append(f"encoding rollback: {exc}")
                for target in reversed(installed_additions):
                    try:
                        if target.exists():
                            target.unlink()
                    except Exception as exc:
                        rollback_errors.append(f"remove added file {target.name}: {exc}")
                for staged, original in reversed(staged_removals):
                    try:
                        if staged.exists():
                            shutil.move(str(staged), str(original))
                    except Exception as exc:
                        rollback_errors.append(f"restore removed file {original.name}: {exc}")
                shutil.rmtree(transaction_dir, ignore_errors=True)
                rollback_detail = ""
                if rollback_errors:
                    rollback_detail = ("\n\nRollback issues:\n" + "\n".join(f"- {issue}" for issue in rollback_errors))
                raise PersonServiceError(f"Could not update images for {name!r}: " f"{original_error}{rollback_detail}") from original_error
            finally:
                if log_connected:
                    try:
                        manager.progress_signal.disconnect(on_log)
                    except TypeError:
                        pass
                if progress_connected:
                    try:
                        manager.progress_update.disconnect(on_progress)
                    except TypeError:
                        pass
            shutil.rmtree(transaction_dir, ignore_errors=True)
            emit_log(
                f"[PersonService] Updated {name!r}: "
                f"+{len(addition_plan)}, -{len(removals)}, "
                f"face={face_count}, body={body_count}."
            )
            return PersonOperationResult(
                operation="update_images",
                name=name,
                knowledge_base_changed=True,
                face_encodings=face_count,
                body_encodings=body_count,
                images_added=len(addition_plan),
                images_removed=len(removals),
            )

#------------------------------------------------
# Assign Unknown Images
#----------------------------------------------
            
    def apply_unknown_review_assignments(self, *, assignments: Mapping[str, Sequence[str]],  remove_sources: bool = True, on_log: Callable[[str], None] | None = None, 
                                         on_progress: Callable[[int], None] | None ) -> UnknownReviewResult:
        """
        Add reviewed unknown images to recognition profiles.
        Each person is updated transactionally and re-encoded only once.
        A failure for one person does not roll back successful updates for
        other persons. Failed source images remain in the Unknown folder.
        """
        with self._operation_lock:
            grouped: dict[str, list[str]] = {}
            for raw_name, raw_paths in assignments.items():
                name = self._clean_name(raw_name)
                if not name:
                    continue
                seen: set[str] = set()
                paths: list[str] = []
                for raw_path in raw_paths:
                    path = os.path.abspath(os.fspath(Path(str(raw_path)).expanduser()))
                    key = os.path.normcase(path)
                    if key not in seen:
                        seen.add(key)
                        paths.append(path)
                if paths:
                    grouped[name] = paths
            if not grouped:
                raise ValueError("No unknown-image assignments were supplied.")
            updated_persons: list[str] = []
            successful_sources: list[str] = []
            failed_persons: list[tuple[str, str]] = []
            warnings: list[str] = []
            assigned_images = 0
            names = sorted(grouped, key=lambda value: (value.casefold(), value))
            total = len(names)

            def emit_log(message: str) -> None:
                if callable(on_log):
                    on_log(message)
                else:
                    self._log(message)

            for index, name in enumerate(names, start=1):
                paths = grouped[name]
                emit_log(
                    f"[Unknown Review] Updating {name!r} with "
                    f"{len(paths)} reviewed image(s)."
                )
                def person_progress(value: int, *, current=index) -> None:
                    if not callable(on_progress):
                        return

                    value = max(0, min(100, int(value)))
                    overall = int(((current - 1) + value / 100) / total * 100)
                    on_progress(overall)
                try:
                    result = self.update_person_images(
                        name=name,
                        add_images=paths,
                        remove_images=(),
                        on_log=on_log,
                        on_progress=person_progress,
                    )
                except Exception as exc:
                    failed_persons.append((name, str(exc)))
                    emit_log(f"[Unknown Review] Failed for {name!r}: {exc}")
                    continue

                updated_persons.append(name)
                successful_sources.extend(paths)
                assigned_images += result.images_added
                if remove_sources:
                    for source in paths:
                        try:
                            path = Path(source)
                            if path.exists():
                                path.unlink()
                        except Exception as exc:
                            warnings.append(
                                f"Image was added to {name!r}, but the source "
                                f"could not be removed: {source} ({exc})"
                            )

                emit_log(
                    f"[Unknown Review] Updated {name!r}: "
                    f"{result.images_added} image(s), "
                    f"{result.face_encodings} face and "
                    f"{result.body_encodings} body encoding(s)."
                )
            if callable(on_progress):
                on_progress(100)
            return UnknownReviewResult(
                assigned_images=assigned_images,
                updated_persons=tuple(updated_persons),
                successful_sources=tuple(successful_sources),
                failed_persons=tuple(failed_persons),
                warnings=tuple(warnings),
            )
        
    def _encoding_counts(self, name: str) -> tuple[int, int]:
        persons = self.knowledge_manager.persons
        face_count = sum(value == name for value in persons.get("face_names", []))
        body_count = sum(value == name for value in persons.get("body_names", []))
        return face_count, body_count

    def _snapshot_person_encodings(self, name: str) -> dict[str, list[tuple[int, Any]]]:
        persons = self.knowledge_manager.persons
        snapshot: dict[str, list[tuple[int, Any]]] = {}
        for kind in ("face", "body"):
            names = persons.get(f"{kind}_names", [])
            encodings = persons.get(f"{kind}_encodings", [])
            if len(names) != len(encodings):
                raise PersonServiceError(
                    f"{kind.title()} encoding/name lists have different lengths."
                )
            snapshot[kind] = [
                (index, copy.deepcopy(encodings[index]))
                for index, current_name in enumerate(names)
                if current_name == name
            ]
        return snapshot

    def _restore_person_encodings(self, name: str, snapshot: dict[str, list[tuple[int, Any]]],) -> None:
        manager = self.knowledge_manager
        manager.remove_person_encodings(name)
        for kind in ("face", "body"):
            names = manager.persons.setdefault(f"{kind}_names", [])
            encodings = manager.persons.setdefault(f"{kind}_encodings", [])
            for original_index, encoding in snapshot.get(kind, []):
                index = min(original_index, len(names))
                names.insert(index, name)
                encodings.insert(index, encoding)
        manager.save_encodings()
            
    @contextmanager
    def _forward_manager_signals(self, on_log: Callable[[str], None] | None = None, on_progress: Callable[[int], None] | None = None,):
        manager = self.knowledge_manager
        connections = []
        try:
            if callable(on_log):
                manager.progress_signal.connect(on_log)
                connections.append((manager.progress_signal, on_log))
            if callable(on_progress):
                manager.progress_update.connect(on_progress)
                connections.append((manager.progress_update, on_progress))
            yield
        finally:
            for signal, callback in reversed(connections):
                try:
                    signal.disconnect(callback)
                except (TypeError, RuntimeError):
                    pass
                
    def reencode_person(self, *, name: str, on_log: Callable[[str], None] | None = None, on_progress: Callable[[int], None] | None = None,) -> PersonOperationResult:
        """
        Re-encode one recognition profile with rollback protection.
        Existing encodings are restored if re-encoding, validation, or saving
        fails. A Persons DB record is optional and is not modified.
        """
        with self._operation_lock:
            name = self._clean_name(name)
            if not name:
                raise ValueError("Person name cannot be empty.")
            folder = self._kb_folder(name)
            if not folder.is_dir():
                raise PersonNotFoundError(
                    f"Knowledge-base folder not found for {name!r}:\n{folder}"
                )
            image_paths = self.get_person_image_paths(name)
            if not image_paths:
                raise PersonServiceError(
                    f"No usable knowledge-base images were found for {name!r}."
                )
            snapshot = self._snapshot_person_encodings(name)

            def emit_log(message: str) -> None:
                if callable(on_log):
                    on_log(message)
                else:
                    self._log(message)
            emit_log(
                f"[PersonService] Re-encoding {name!r} from "
                f"{len(image_paths)} image(s)."
            )
            try:
                with self._forward_manager_signals(on_log, on_progress):
                    self.knowledge_manager.reencode_person(name)
                face_count, body_count = self._encoding_counts(name)
                if face_count == 0 and body_count == 0:
                    raise PersonServiceError(f"Re-encoding produced no usable encodings for {name!r}.")

            except Exception as original_error:
                rollback_error = None
                try:
                    self._restore_person_encodings(name, snapshot)
                except Exception as exc:
                    rollback_error = exc
                detail = (
                    f"\n\nEncoding rollback also failed: {rollback_error}"
                    if rollback_error
                    else ""
                )
                raise PersonServiceError(f"Could not re-encode {name!r}: {original_error}{detail}") from original_error
            warnings = []
            if face_count == 0:
                warnings.append("No face encodings were produced.")
            if body_count == 0:
                warnings.append("No body encodings were produced.")
            emit_log(f"[PersonService] Re-encoded {name!r}: " f"{face_count} face and {body_count} body encoding(s).")
            return PersonOperationResult(
                operation="reencode",
                name=name,
                database_record_exists=self._person_record(name) is not None,
                knowledge_base_changed=True,
                face_encodings=face_count,
                body_encodings=body_count,
                images_processed=len(image_paths),
                warnings=tuple(warnings),
            )

    def reencode_persons(self, *, names: Sequence[str], continue_on_error: bool = True, on_log: Callable[[str], None] | None = None, on_progress: Callable[[int], None] | None = None,
        on_person_done: Callable[[str, int, int], None] | None = None, stop_flag: Callable[[], bool] | None = None,) -> ReencodeBatchResult:
        """Re-encode several persons sequentially and independently."""
        with self._operation_lock:
            cleaned_names = {
                self._clean_name(name)
                for name in names
                if self._clean_name(name)
            }
            ordered_names = tuple(
                sorted(cleaned_names, key=lambda value: (value.casefold(), value))
            )
            if not ordered_names:
                raise ValueError("No persons were selected for re-encoding.")
            completed = []
            failures = []
            cancelled = False
            total = len(ordered_names)
            def emit_log(message: str) -> None:
                if callable(on_log):
                    on_log(message)
                else:
                    self._log(message)
            emit_log(
                f"[PersonService] Starting re-encoding for "
                f"{total} person(s)."
            )
            for index, name in enumerate(ordered_names, start=1):
                if callable(stop_flag) and stop_flag():
                    cancelled = True
                    emit_log("[PersonService] Re-encoding cancelled.")
                    break
                def mapped_progress(value: int, current=index) -> None:
                    if not callable(on_progress):
                        return
                    value = max(0, min(100, int(value)))
                    overall = int(((current - 1) + value / 100) / total * 100)
                    on_progress(overall)

                try:
                    result = self.reencode_person(name=name, on_log=on_log, on_progress=mapped_progress,)
                except Exception as exc:
                    failures.append((name, str(exc)))
                    emit_log(f"[PersonService] Re-encoding failed for {name!r}: {exc}")
                    if not continue_on_error:
                        raise
                else:
                    completed.append(result)
                    if callable(on_person_done):
                        on_person_done(name, result.face_encodings, result.body_encodings)
                if callable(on_progress):
                    on_progress(int(index / total * 100))
            emit_log(
                f"[PersonService] Re-encoding completed: "
                f"{len(completed)} succeeded, {len(failures)} failed."
            )
            return ReencodeBatchResult(
                requested=ordered_names,
                completed=tuple(completed),
                failures=tuple(failures),
                cancelled=cancelled,
            )

    def reencode_all_persons(self, *, on_log:Callable[[str], None] | None = None, on_progress:Callable[[str], None] | None = None, 
                             on_person_done:Callable[[str], None] | None = None, stop_flag:Callable[[str], None] | None = None)-> ReencodeBatchResult:
        # Perform one true full knowledge-base rebuild and return the ReencodeBatchResult expected by the worker and GUI.
        with self._operation_lock:
            manager = self.knowledge_manager
            kb_root = Path(manager.knowledge_base_path)
            if not kb_root.is_dir():
                raise PersonServiceError(f"Knowledge-base directory does not exist: {kb_root}")
            requested = tuple(sorted((path.name for path in kb_root.iterdir() if path.is_dir() ),
                    key=lambda value: (value.casefold(), value,),))
            if not requested:
                raise PersonServiceError( "No person folders were found in the knowledge base.")
            completed: list[PersonOperationResult] = []
            completed_names: set[str] = set()
            failures: list[tuple[str, str]] = []

            def emit_log(message: str) -> None:
                if callable(on_log):
                    on_log(message)
                else:
                    self._log(message)

            def handle_person_done(name: str, face_count: int, body_count: int, ) -> None:
                completed_names.add(name)
                try:
                    image_count = len(self.get_person_image_paths(name))
                except Exception:
                    image_count = 0
                warnings: list[str] = []
                if face_count == 0:
                    warnings.append("No face encodings were produced.")
                if body_count == 0:
                    warnings.append("No body encodings were produced.")
                result = PersonOperationResult(operation="reencode", name=name, database_record_exists=(self._person_record(name) is not None ),
                    knowledge_base_changed=True, face_encodings=int(face_count), body_encodings=int(body_count), images_processed=image_count,  warnings=tuple(warnings),)
                completed.append(result)
                if callable(on_person_done):
                    on_person_done(name, int(face_count), int(body_count), )
            emit_log("[PersonService] Starting true full knowledge-base " f"rebuild for {len(requested)} person(s)." )
            try:
                with self._forward_manager_signals(on_log, on_progress, ):
                    manager.reencode_knowledge_base(on_person_done=handle_person_done, stop_flag=stop_flag, )
            except Exception as exc:
                raise PersonServiceError( f"Complete knowledge-base rebuild failed: {exc}" ) from exc
            cancelled = bool(callable(stop_flag) and stop_flag())
            # If the rebuild was not cancelled, every requested person folder
            # should have produced an on_person_done callback.
            if not cancelled:
                for name in requested:
                    if name not in completed_names:
                        failures.append((name, "The full rebuild did not report this person as completed.", ))
            if callable(on_progress):
                on_progress(100)
            emit_log(
                "[PersonService] Full rebuild finished: "
                f"{len(completed)} completed, "
                f"{len(failures)} failed, "
                f"cancelled={cancelled}."
            )
            return ReencodeBatchResult(
                requested=requested,
                completed=tuple(completed),
                failures=tuple(failures),
                cancelled=cancelled,
            )
                    