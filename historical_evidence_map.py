"""Review historical test claims without promoting them to certified native evidence."""

import argparse
import importlib.util
import json
from pathlib import Path


FIELDS = ("scope", "capability", "gate", "version", "source", "claim", "review_status")
STATUSES = {"pending", "confirmed", "rejected"}


def load_gates(root):
    path = root / "native_evidence_reconciliation.py"
    if not path.is_file(): raise FileNotFoundError(f"Required v1.13.1 reconciler missing: {path}")
    spec = importlib.util.spec_from_file_location("personlens_native_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_gates(root)


def validate(gates, entries):
    if not isinstance(entries, list): raise ValueError("Historical candidates must be a JSON list")
    issues, seen = [], set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            issues.append(f"Entry {index}: expected object")
            continue
        if any(not isinstance(entry.get(field), str) or not entry[field].strip() for field in FIELDS):
            issues.append(f"Entry {index}: missing or empty required field")
            continue
        scope, capability, gate = (entry[field] for field in ("scope", "capability", "gate"))
        if scope not in gates or capability not in gates[scope] or gate not in gates[scope][capability]:
            issues.append(f"Entry {index}: unknown gate {scope}/{capability}/{gate}")
            continue
        if entry["review_status"] not in STATUSES:
            issues.append(f"Entry {index}: invalid review_status")
            continue
        key = (scope, capability, gate)
        if key in seen: issues.append(f"Entry {index}: duplicate gate {scope}/{capability}/{gate}")
        seen.add(key)
    return issues


def summarize(gates, entries):
    index = {(entry["scope"], entry["capability"], entry["gate"]): entry for entry in entries}
    rows = []
    for scope, capabilities in gates.items():
        for capability, required in capabilities.items():
            pending = [gate for gate in required if (scope, capability, gate) in index and
                       index[(scope, capability, gate)]["review_status"] == "pending"]
            confirmed = [gate for gate in required if (scope, capability, gate) in index and
                         index[(scope, capability, gate)]["review_status"] == "confirmed"]
            missing = [gate for gate in required if (scope, capability, gate) not in index]
            rows.append((scope, capability, len(confirmed), len(pending), len(missing), len(required)))
    return rows


def markdown(gates, entries):
    lines = ["# PersonLens v1.13.2 historical evidence mapping", "", "| Scope | Capability | Confirmed candidates | Awaiting review | Unmapped | Required |",
             "| --- | --- | ---: | ---: | ---: | ---: |"]
    lines.extend(f"| {scope} | {capability} | {confirmed} | {pending} | {missing} | {required} |"
                 for scope, capability, confirmed, pending, missing, required in summarize(gates, entries))
    lines.extend(["", "All mappings are historical leads only. 'Confirmed' means reviewed as a candidate, not certified by the native evidence audit.",
                  "No audit evidence is modified or promoted automatically."])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate historical evidence candidates without certifying gates")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        gates = load_gates(args.root)
        entries = json.loads(args.candidates.read_text(encoding="utf-8"))
        issues = validate(gates, entries)
        if issues: parser.error("; ".join(issues))
        print(json.dumps({"mapping": summarize(gates, entries), "candidates": len(entries)}, indent=2)
              if args.json else markdown(gates, entries))
    except (OSError, ValueError, json.JSONDecodeError) as exc: parser.error(str(exc))
    return 0


if __name__ == "__main__": raise SystemExit(main())
