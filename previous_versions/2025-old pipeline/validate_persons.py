# validate_persons.py
import json
import sys
import pathlib
from jsonschema import Draft202012Validator

SCHEMA_PATH = "person.schema.json"
DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else "persons.json"

def read_data(path: str):
    text = pathlib.Path(path).read_text(encoding="utf-8").lstrip()
    if not text:
        return []
    # If it starts with '[' assume a JSON array; else treat as NDJSON
    if text[0] == '[':
        return json.loads(text)
    if text[0] == '{':
        obj = json.loads(text)
        if isinstance(obj, dict):
            # Convert dict -> rows on the fly
            rows = []
            for k, v in obj.items():
                if isinstance(v, dict):
                    rec = {**v}
                    rec.setdefault("personName", k)
                else:
                    rec = {"personName": k, "value": v}
                rows.append(rec)
            return rows
        return [obj]    
    # NDJSON: one JSON object per non-empty line
    items = []
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        try:
            items.append(json.loads(s))
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"NDJSON parse error on line {i}: {e.msg} (col {e.colno})"
            )
    return items

def main():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    validator = Draft202012Validator(schema)

    data = read_data(DATA_PATH)
    if not isinstance(data, list):
        data = [data]

    ok = True

    # Validate each record
    for i, item in enumerate(data):
        errors = sorted(validator.iter_errors(item), key=lambda e: e.path)
        for e in errors:
            where = ".".join(map(str, e.path)) or "<root>"
            print(f"ERROR item[{i}] {where}: {e.message}")
            ok = False

    # Cross-record uniqueness (schema can't enforce this)
    names = [d.get("personName") for d in data]
    dups = {n for n in names if n and names.count(n) > 1}
    if dups:
        print(f"ERROR duplicate personName values: {sorted(dups)}")
        ok = False

    print("VALID ✅" if ok else "INVALID ❌")

if __name__ == "__main__":
    main()
