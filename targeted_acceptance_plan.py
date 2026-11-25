"""Validate a compact native acceptance plan against PersonLens's actual audit gates."""

import argparse
import importlib.util
import json
from pathlib import Path


FIELDS = ("id", "title", "scope", "capability", "gates", "steps", "expected")


def load_gates(root):
    path = root / "native_evidence_reconciliation.py"
    if not path.is_file(): raise FileNotFoundError(f"Missing v1.13.1 reconciler: {path}")
    spec = importlib.util.spec_from_file_location("native_evidence_reconciliation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_gates(root)


def validate(gates, scenarios):
    if not isinstance(scenarios, list): raise ValueError("Scenarios must be a JSON list")
    issues, ids, covered = [], set(), set()
    for number, scenario in enumerate(scenarios, start=1):
        if not isinstance(scenario, dict) or any(field not in scenario for field in FIELDS):
            issues.append(f"Scenario {number}: missing required fields")
            continue
        if any(not isinstance(scenario[field], str) or not scenario[field].strip()
               for field in ("id", "title", "scope", "capability", "steps", "expected")):
            issues.append(f"Scenario {number}: invalid text fields")
            continue
        if scenario["id"] in ids: issues.append(f"Scenario {number}: duplicate ID {scenario['id']}")
        ids.add(scenario["id"])
        scope, capability = scenario["scope"], scenario["capability"]
        if scope not in gates or capability not in gates[scope]:
            issues.append(f"Scenario {number}: unknown capability {scope}/{capability}")
            continue
        names = scenario["gates"]
        if not isinstance(names, list) or not names or any(not isinstance(gate, str) for gate in names) or len(names) != len(set(names)):
            issues.append(f"Scenario {number}: gates must be a unique, nonempty list of names")
            continue
        for gate in names:
            if gate not in gates[scope][capability]: issues.append(f"Scenario {number}: unknown gate {scope}/{capability}/{gate}")
            else: covered.add((scope, capability, gate))
    required = {(scope, capability, gate) for scope, capabilities in gates.items()
                for capability, names in capabilities.items() for gate in names}
    return issues, covered, required - covered


def markdown(scenarios, covered, missing):
    lines = ["# PersonLens v1.13.3 targeted native acceptance plan", "",
             f"Planned scenarios: **{len(scenarios)}** · Gates addressed by plan: **{len(covered)}** · Unmapped: **{len(missing)}**", "",
             "| Scenario | Scope | Capability | Gates addressed |", "| --- | --- | --- | --- |"]
    for item in scenarios:
        lines.append(f"| {item['id']} — {item['title']} | {item['scope']} | {item['capability']} | {', '.join(item['gates'])} |")
    lines.extend(["", "These are **planned checks**, not passing results. Every mapped gate requires its specified subcondition to be observed.",
                  "Use disposable DB/KB/bank copies for any write, delete, re-encode, conflict or fault-injection test."])
    if missing: lines.append("Unmapped gates: " + ", ".join("/".join(key) for key in sorted(missing)))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate targeted Windows Qt acceptance plan without running destructive tests")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        gates = load_gates(args.root)
        scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
        issues, covered, missing = validate(gates, scenarios)
        if issues: parser.error("; ".join(issues))
        print(json.dumps({"scenarios": len(scenarios), "planned_gates": len(covered), "unmapped": sorted(missing)}, indent=2)
              if args.json else markdown(scenarios, covered, missing))
    except (OSError, ValueError, json.JSONDecodeError) as exc: parser.error(str(exc))
    return 0


if __name__ == "__main__": raise SystemExit(main())
