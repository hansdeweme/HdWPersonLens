"""Build a display-only union of DB records and actual recognition identities."""


def combined_roster(db_records, recognition_names):
    records = [dict(record) for record in db_records]
    known = {record.get("personName") for record in records if isinstance(record.get("personName"), str)}
    for name in recognition_names:
        if not isinstance(name, str) or not name.strip() or name in known: continue
        records.append({"personName": name, "_kb_only": True})
        known.add(name)
    return sorted(records, key=lambda record: (str(record.get("personName", "")).casefold(), str(record.get("personName", ""))))
