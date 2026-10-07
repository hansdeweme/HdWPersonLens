# dict_to_rows.py
import json, sys, pathlib

src = sys.argv[1] if len(sys.argv) > 1 else "persons.json"
dst = sys.argv[2] if len(sys.argv) > 2 else "persons.json"

obj = json.loads(pathlib.Path(src).read_text(encoding="utf-8"))
if not isinstance(obj, dict):
    raise SystemExit("Top-level must be a dict for this script.")

rows = []
for k, v in obj.items():
    if isinstance(v, dict):
        rec = {**v}
        rec.setdefault("personName", k)  # keep key as personName
    else:
        rec = {"personName": k, "value": v}
    rows.append(rec)

pathlib.Path(dst).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote JSON array: {dst} ({len(rows)} rows)")
