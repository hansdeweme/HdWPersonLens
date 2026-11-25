"""Pure presentation guidance for the selected PersonLens person; not an authorization policy."""


def suggested_person_action(name, state, readiness=None):
    """Return (label, route, explanation) without changing data or eligibility."""
    if not name: return "Add Person", "add", "Select a person or create a new profile."
    if state is None or not (state.database_record_exists or state.has_recognition_state):
        return "Refresh roster", "refresh", "This person is no longer available. Refresh before continuing."
    if not state.has_recognition_state:
        return "Open Profile", "profile", "No recognition profile is available for this DB record."
    if not state.image_count:
        return "Edit KB Images", "images", "The recognition profile has no reference images."
    report = readiness if isinstance(readiness, dict) else {}
    if not report or report.get("status") != "Technically prepared":
        detail = str(report.get("next_action") or "Review collection, identity and reference evidence.")
        return "Review KB Assessment", "assessment", detail
    return "Inspect KB Gallery", "gallery", "Technical checks are prepared; identity remains unverified."
