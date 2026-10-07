# validate_persons.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

import json
from pathlib import Path
from   jsonschema import Draft202012Validator
# local imports
from   config import PERSON_SCHEMA_FILENAME

SCHEMA_PATH = Path(__file__).resolve().parent / PERSON_SCHEMA_FILENAME


with SCHEMA_PATH.open("r", encoding="utf-8") as f:
    schema = json.load(f)

validator = Draft202012Validator(schema)

def validate_doc(doc, idx=None):
    errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
    if errors:
        tag = f" (item {idx})" if idx is not None else ""
        for e in errors:
            print(f"ERROR{tag}: {list(e.path)} -> {e.message}")
        return False
    return True

# Validate array JSON
with SCHEMA_PATH.open("r", encoding="utf-8") as f:
    data = json.load(f)

ok = True
if isinstance(data, list):
    for i, item in enumerate(data):
        ok &= validate_doc(item, i)
else:
    ok &= validate_doc(data)

# Optional: enforce uniqueness of personName (schema can’t do cross-record uniqueness)
if isinstance(data, list):
    names = [d.get("personName") for d in data]
    dups = {n for n in names if names.count(n) > 1}
    if dups:
        ok = False
        print(f"ERROR: duplicate personName values found: {sorted(dups)}")
print("VALID ✅" if ok else "INVALID ❌")
