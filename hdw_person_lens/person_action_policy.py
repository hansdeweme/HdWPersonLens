"""Presentation-level eligibility for actions targeting the active Workbench person."""


ACTION_LABELS = {"add": "Add Person", "rename": "Rename", "remove": "Remove", "images": "Edit Images", "reencode": "Re-encode"}


def person_action_allowed(action: str, name: str, state) -> tuple[bool, str]:
    if action == "add": return True, ""
    if action not in ACTION_LABELS: return False, "Unknown person action."
    if not name or state is None or not state.database_record_exists:
        return False, "The selected person is no longer available. Refresh and try again."
    if action in ("images", "reencode") and not state.has_recognition_state:
        return False, f"No recognition profile is available for '{name}'."
    if action == "reencode" and not state.image_count:
        return False, f"No usable KB images are available for '{name}'."
    return True, ""
