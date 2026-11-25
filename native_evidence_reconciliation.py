"""Reconcile explicit native test observations into reviewable PersonLens evidence candidates."""

import argparse
import importlib.util
import json
from pathlib import Path


REQUIRED_FIELDS = ("scope", "capability", "gate", "result", "environment", "observed_at", "observation")


def load_gates(root):
    gates = {}
    for scope, filename, attribute in (("workspace", "workspace_parity_audit.py", "GATES"),
                                       ("management", "management_retirement_audit.py", "REQUIRED_NATIVE")):
        path = root / filename
        if not path.is_file(): raise FileNotFoundError(f"Required audit missing: {path}")
        spec = importlib.util.spec_from_file_location(f"evidence_{scope}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if scope == "workspace": gates[scope] = {name: tuple(items) for name, items in getattr(module, attribute).items()}
        else: gates[scope] = {name: tuple(getattr(module, attribute)) for name in ("add", "rename", "remove", "images", "reencode")}
    return gates


def reconcile(gates, observations):
    if not isinstance(observations, list): raise ValueError("Observation ledger must contain a JSON list")
    accepted, issues = {}, []
    for index, item in enumerate(observations, start=1):
        if not isinstance(item, dict):
            issues.append(f"Entry {index}: expected a JSON object")
            continue
        missing = [field for field in REQUIRED_FIELDS if field not in item]
        if missing:
            issues.append(f"Entry {index}: missing fields: {', '.join(missing)}")
            continue
        scope, capability, gate = item["scope"], item["capability"], item["gate"]
        if not isinstance(scope, str) or not isinstance(capability, str) or not isinstance(gate, str):
            issues.append(f"Entry {index}: scope, capability and gate must be strings")
            continue
        if scope not in gates or capability not in gates[scope] or gate not in gates[scope][capability]:
            issues.append(f"Entry {index}: unknown gate {scope}/{capability}/{gate}")
            continue
        if item["result"] not in ("pass", "fail") or any(not isinstance(item[field], str) or not item[field].strip()
                                                            for field in ("environment", "observed_at", "observation")):
            issues.append(f"Entry {index}: require pass/fail and nonempty environment, observed_at and observation")
            continue
        key = (scope, capability, gate)
        if key in accepted:
            issues.append(f"Entry {index}: duplicate observation for {scope}/{capability}/{gate}")
            accepted.pop(key)
            continue
        accepted[key] = item
    return accepted, issues


def candidates(gates, accepted):
    result = {}
    for scope, capabilities in gates.items():
        result[scope] = {name: {gate: accepted.get((scope, name, gate), {}).get("result") == "pass" for gate in required}
                         for name, required in capabilities.items()}
    return result


def markdown(gates, accepted, issues):
    lines = ["# PersonLens v1.13.1 native evidence reconciliation", "", "| Scope | Capability | Passing | Required | Missing / failed |",
             "| --- | --- | ---: | ---: | --- |"]
    for scope, capabilities in gates.items():
        for capability, required in capabilities.items():
            passed = [gate for gate in required if accepted.get((scope, capability, gate), {}).get("result") == "pass"]
            remaining = [gate for gate in required if gate not in passed]
            lines.append(f"| {scope} | {capability} | {len(passed)} | {len(required)} | {', '.join(remaining) or 'None'} |")
    lines.extend(["", f"Invalid or duplicate ledger entries: {len(issues)}"])
    lines.extend(f"- {issue}" for issue in issues)
    lines.extend(["", "This is a review worksheet, not automatic certification. Structural parity and manual sign-off remain separate."])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reconcile explicit native acceptance observations without modifying evidence")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, help="Write new candidate JSON files; existing files are never overwritten")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        gates = load_gates(args.root)
        ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
        accepted, issues = reconcile(gates, ledger)
        result = candidates(gates, accepted)
        if args.output_dir:
            if not args.output_dir.is_dir(): parser.error("--output-dir must be an existing directory")
            targets = {scope: args.output_dir / f"{scope}_evidence_candidate.json" for scope in result}
            if any(path.exists() for path in targets.values()): parser.error("Candidate output already exists; refusing to overwrite")
            for scope, path in targets.items():
                with path.open("x", encoding="utf-8") as stream: json.dump(result[scope], stream, indent=2)
        print(json.dumps({"candidates": result, "issues": issues}, indent=2) if args.json else markdown(gates, accepted, issues))
    except (OSError, ValueError, json.JSONDecodeError) as exc: parser.error(str(exc))
    return 0 if not issues else 1


if __name__ == "__main__": raise SystemExit(main())
