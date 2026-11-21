"""Qt-free visual classification of provisional KB assessment findings."""


FINDING_COLORS = {"normal": "#b7c6d8", "success": "#b2f5ea", "warning": "#fbd38d", "error": "#feb2b2"}


def finding_tone(finding: str) -> str:
    value = str(finding or "").casefold().replace("_", " ")
    # Collection findings append filenames; classify their category first so
    # words in a filename cannot change the assessment's severity.
    if value.startswith("possible duplicate of "): return "warning"
    if any(word in value for word in ("unreadable", "failed", "error", "corrupt")): return "error"
    if any(word in value for word in ("duplicate", "outlier", "inconclusive", "unassessable", "review", "stale")):
        return "success" if "no duplicate" in value else "warning"
    if any(word in value for word in ("supported", "shortlist", "no duplicate")): return "success"
    return "normal"
