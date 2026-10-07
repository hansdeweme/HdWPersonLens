#find_lookalikes.py
# Workers for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
from __future__ import annotations
from collections.abc import Callable, Mapping
from typing import Any

import os
import numpy as np
from numbers  import Real
# PyQt imports
from PyQt6.QtWidgets import QWidget, QMessageBox, QDialog
# local imports
from recognition_gui_dialogs import LookalikeFinderDialog, LookalikeResultsDialog
from kb_utils import _group_by_person

#-----------------------------------
# ---------- helpers ----------   
#-----------------------------------     
def _build_capabilities(manager) -> tuple[list[str], dict[str, dict[str, bool]]]:
    persons = getattr(manager, "persons", {}) or {}
    face_names = {
        _normalize_name(name)
        for name in persons.get("face_names", [])
        if _normalize_name(name)
    }
    body_names = {
        _normalize_name(name)
        for name in persons.get("body_names", [])
        if _normalize_name(name)
    }
    all_names = sorted(face_names | body_names)
    capabilities = {
        name: {
            "face": name in face_names,
            "body": name in body_names,
        }
        for name in all_names
    }
    return all_names, capabilities

def _has_callable(obj, name: str) -> bool:
    return callable(getattr(obj, name, None))

def _detect_body_capability(manager, capabilities: Mapping[str, Mapping[str, bool]],) -> bool:
    has_body_data = any(entry.get("body", False) for entry in capabilities.values())
    return has_body_data and _has_callable(manager, "lookalikes_for")

def _compute_rows(*, manager, person: str, mode: str, topk: int):
    if mode not in {"face", "body"}:
        raise ValueError(f"Unsupported lookalike mode: {mode!r}")
    return manager.lookalikes_for(person, mode=mode, topk=topk)

def _log(logger, message: str) -> None:
    if callable(logger):
        logger(message)
    else:
        print(message)

def _normalize_name(value: str) -> str:
    return " ".join((value or "").split()).strip()

def _iter_rows(rows):
    """Yield row-like entries uniformly."""
    if rows is None:
        return
    if isinstance(rows, dict):
        for k, v in rows.items():
            if isinstance(v, dict):
                yield {"name": k, **v}
            elif isinstance(v, (list, tuple)) and v and isinstance(v[-1], Real):
                yield {"name": k, "__val__": float(v[-1])}
            elif isinstance(v, Real):
                yield {"name": k, "__val__": float(v)}
            else:
                yield {"name": k}
        return
    for x in rows:
        yield x

def _make_default_folder_getter(manager, settings: Mapping[str, Any],) -> Callable[[str], str | None]:
    def get_folder(name: str) -> str | None:
        public_getter = getattr(manager, "get_person_folder", None,)
        if callable(public_getter):
            try:
                return public_getter(name)
            except Exception:
                pass
        legacy_getter = getattr(manager, "_get_person_folder",  None,)
        if callable(legacy_getter):
            try:
                return legacy_getter(name)
            except Exception:
                pass
        base = str(
            settings.get("knowledge_base", "")
        ).strip()
        if not base:
            return None
        return os.path.normpath(os.path.join(base, name))
    return get_folder

#------------------------------------------------------------------
# Analyze knowledge base to find lookalikes        
#------------------------------------------------------------------
def show_lookalike_finder( *, manager: Any, settings: Mapping[str, Any], parent: QWidget | None = None, sample_getter: Callable[[str], str | None] | None = None,
    folder_getter: Callable[[str], str | None] | None = None, logger: Callable[[str], None] | None = None,) -> None:
    all_names, capabilities = _build_capabilities(manager)
    if not all_names:
        QMessageBox.information(parent, "No Persons", "Knowledge base is empty.",)
        return       
    has_body = _detect_body_capability(manager, capabilities)

    dlg = LookalikeFinderDialog(all_names, default_topk=10, parent=parent, has_body=has_body,)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    person, mode, topk = dlg.get_values()
    person = _normalize_name(person)
    # ---------- capability gating ----------
    cap = capabilities.get(person, {"face": False, "body": False})
    if mode == "body" and not has_body:
        QMessageBox.warning(parent, "Body lookalikes unavailable", ("Body lookalike search is not available. The knowledge-base manager must provide lookalikes_for(..., mode='body')."),)
        return
    if mode not in {"face", "body"}:
        QMessageBox.warning(parent, "Unsupported mode", f"Unsupported lookalike mode: {mode!r}",)
        return
    if not cap.get(mode, False):
        other = "face" if mode == "body" else "body"
        if cap.get(other, False) and (other != "body" or has_body):
            QMessageBox.information(parent, "No encodings for selected mode", f"'{person}' has no {mode} encodings. Switching to {other}.",)
            mode = other
        else:
            QMessageBox.information(parent, "No encodings", f"'{person}' has no usable {mode} encodings.", )
            return
    # ---------- compute (oversample, then filter) ----------
    over_k = topk
    try:
        rows_raw = _compute_rows(manager=manager, person=person, mode=mode, topk=over_k,)
    except (ValueError, NotImplementedError) as exc:
        QMessageBox.warning(parent, "Lookalike search unavailable", str(exc),)
        return
    except Exception as exc:
        _log(logger, f"[Lookalikes:error] person={person} mode={mode}: {exc}",)
        QMessageBox.critical(parent, "Lookalike search failed", f"Could not calculate {mode} lookalikes for '{person}'.\n\n{exc}",)
        return
    # Materialize once because downstream code needs both iteration and len().
    if rows_raw is None:
        rows_raw = []
    else:
        rows_raw = list(_iter_rows(rows_raw))
       
    # ---------------------------------------------------------
    # Finalize robust lookalike ranking
    #
    # Lookalike search is a retrieval/ranking operation, not a
    # same-identity acceptance decision. Do not filter candidates
    # using recognition thresholds.
    # ---------------------------------------------------------
    def _optional_float(value, default=None,) -> float | None:
        try:
            if value is None:
                return default
            result = float(value)
            if not (float("-inf") < result < float("inf")):
                return default
            return result
        except (TypeError, ValueError):
            return default
    dialog_rows: list[dict[str, Any]] = []
    for raw_row in rows_raw:
        # -----------------------------------------------------
        # Preferred robust dictionary result
        # -----------------------------------------------------
        if isinstance(raw_row, Mapping):
            row = dict(raw_row)
            name = _normalize_name(row.get("name") or row.get("candidate") or row.get("person") or row.get("B") or "" )
            if not name:
                continue
            # Primary robust ranking value: lower is better.
            support_distance = _optional_float(row.get("support_distance", row.get("distance"),))
            # Compatibility fallback for similarity-style rows.
            if support_distance is None:
                raw_score = row.get("score", row.get("similarity"),)
                score = _optional_float(raw_score)
                if score is not None:
                    if mode == "body":
                        support_distance = (1.0 - score)
                    else:
                        # Legacy face rows may expose the transformed score 1 / (1 + distance).
                        score = max(score, 1e-12,)
                        support_distance = max(0.0, (1.0 / score) - 1.0,)
            if support_distance is None:
                _log(logger, (
                        "[Lookalikes:skip] "
                        f"Candidate {name!r} has no "
                        "usable ranking distance."
                    ), )
                continue
            best_pair_distance = _optional_float(row.get("best_pair_distance", row.get("min_distance"), ), support_distance,)
            mean_nearest_distance = _optional_float(row.get("mean_nearest_distance", row.get("avg_distance"), ), support_distance,)
            dialog_rows.append(
                {
                    **row,
                    "name": name,
                    "support_distance": float(support_distance),
                    # Keep `distance` as a compatibility alias.
                    "distance": float(support_distance),
                    "best_pair_distance": float( best_pair_distance),
                    "mean_nearest_distance": float(mean_nearest_distance),
                }
            )
        # -----------------------------------------------------
        # Temporary backward compatibility with legacy tuples:
        # (name, average_distance, minimum_distance)
        # -----------------------------------------------------
        elif (isinstance(raw_row, (list, tuple)) and len(raw_row) >= 3):
            name = _normalize_name(str(raw_row[0]))
            average_distance = _optional_float(raw_row[1])
            minimum_distance = _optional_float(raw_row[2])
            if (not name or minimum_distance is None):
                continue
            dialog_rows.append(
                {
                    "name": name,
                    # Legacy rows have no robust support score.
                    # Retain their former minimum-pair ranking.
                    "support_distance": float(minimum_distance),
                    "distance": float(minimum_distance),
                    "best_pair_distance": float(minimum_distance),
                    "mean_nearest_distance": float(average_distance if average_distance is not None else minimum_distance),
                    "support_count": None,
                    "target_references": None,
                    "candidate_references": None,
                }
            )
    if not dialog_rows:
        QMessageBox.information(parent, "No lookalikes", (f"No {mode} lookalike candidates "  f"were found for '{person}'." ),)
        return
    # Primary sort: robust support distance.
    # Tie-breakers: closest individual pair, then identity name.
    dialog_rows.sort(key=lambda row: (_optional_float(row.get("support_distance"), float("inf"), ), _optional_float( row.get("best_pair_distance"), float("inf"), ), str(row.get("name", "")).casefold(),))
    dialog_rows = dialog_rows[:topk]
    # ---------------------------------------------------------
    # Review-only collision threshold
     # This does not filter lookalikes. It only highlights a very
    # close Best Pair for manual inspection.
    # ---------------------------------------------------------
    dialog_threshold = None
    if mode == "face":
        dialog_threshold = _optional_float(settings.get("lookalike_face_collision_distance", settings.get("face_threshold_extended", settings.get("face_threshold_strong", 0.3849, ),),) )
    elif mode == "body":
        configured_distance = _optional_float(settings.get("lookalike_body_collision_distance"))
        if configured_distance is not None:
            dialog_threshold = (configured_distance)
        else:
            body_similarity = _optional_float(settings.get("body_threshold_alone", settings.get("body_threshold", 0.87, ), ), 0.87,)
            body_similarity = min(1.0, max(0.0, body_similarity, ), )
            dialog_threshold = (1.0 - body_similarity)
    _log(logger, (
            f"[Lookalikes] person={person} "
            f"mode={mode} "
            f"raw={len(rows_raw)} "
            f"shown={len(dialog_rows)} "
            f"collision_threshold="
            f"{dialog_threshold}"
        ), )
    _log(
        logger, ("[Lookalikes:robust-peek] " f"{dialog_rows[:3]}" ), )
    if folder_getter is None:
        folder_getter = (_make_default_folder_getter(manager, settings, ))
    title = (f"Lookalikes for {person} " f"({mode})")
    LookalikeResultsDialog(
        title,
        dialog_rows,
        mode=mode,
        threshold=dialog_threshold,
        sample_getter=sample_getter,
        folder_getter=folder_getter,
        target_name=person,
        parent=parent,
    ).exec()