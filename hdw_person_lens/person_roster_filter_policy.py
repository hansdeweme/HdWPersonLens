"""Pure, inexpensive roster search and source-mode policy."""


def search_terms(value):
    if isinstance(value, dict):
        return " ".join(search_terms(item) for key, item in value.items() if not str(key).startswith("_"))
    if isinstance(value, (list, tuple)):
        return " ".join(search_terms(item) for item in value)
    if isinstance(value, (str, int, float)) and not isinstance(value, bool): return str(value)
    return ""


def record_matches_filters(record, needle="", source_mode="all"):
    if source_mode == "kb_only" and not record.get("_kb_only"): return False
    if source_mode == "db" and record.get("_kb_only"): return False
    searchable = search_terms(record) + (" KB-only recognition profile" if record.get("_kb_only") else "")
    return needle.strip().casefold() in searchable.casefold()
