# rows_to_ndjson.py
import json, sys, pathlib

src = sys.argv[1] if len(sys.argv) > 1 else "persons.json"
dst = sys.argv[2] if len(sys.argv) > 2 else "persons.ndjson"

rows = json.loads(pathlib.Path(src).read_text(encoding="utf-8"))
if not isinstance(rows, list):
    raise SystemExit("Top-level must be a JSON array.")

with pathlib.Path(dst).open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"Wrote NDJSON: {dst} ({len(rows)} lines)")
