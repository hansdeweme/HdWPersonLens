"""Fail-closed confirmation policy for the controlled reference encoding action."""
from pathlib import Path


def confirmation_details(person, preview, snapshot):
    if not isinstance(person, str) or not person or not isinstance(preview, dict) or preview.get("status") != "preview_ready":
        raise ValueError("Build a current reference shortlist before encoding.")
    rows = preview.get("rows")
    if not isinstance(rows, list) or not rows or not snapshot or not getattr(snapshot, "selected", None):
        raise ValueError("The proposed encoding inputs are incomplete.")
    selected = [row for row in rows if isinstance(row, dict) and row.get("action") == "Proposed input"]
    omitted = [row for row in rows if isinstance(row, dict) and row.get("action") == "Omitted from proposal"]
    if len(selected) + len(omitted) != len(rows) or not selected or any(not isinstance(row.get("path"), str) for row in rows):
        raise ValueError("The reference proposal is malformed.")
    if [Path(row["path"]).name for row in selected] != [entry[0] for entry in snapshot.selected]:
        raise ValueError("The reviewed selection no longer matches the encoding snapshot.")
    if len({row["path"] for row in rows}) != len(rows) or len(snapshot.members) != len(rows):
        raise ValueError("The KB reference membership has changed.")
    if {Path(row["path"]).name for row in rows} != {entry[0] for entry in snapshot.members}:
        raise ValueError("The selected KB files differ from the reviewed membership.")
    return {"person": person, "selected": tuple(row["path"] for row in selected),
            "omitted": tuple(row["path"] for row in omitted),
            "old_faces": int(preview["existing_face_encodings"]), "old_bodies": int(preview["existing_body_encodings"])}
