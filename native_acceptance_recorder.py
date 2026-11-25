"""Guide native PersonLens acceptance and record explicit, individual gate observations."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile


def load_module(path, name):
    if not path.is_file(): raise FileNotFoundError(f"Required script missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plan(root, scenario_path):
    planner = load_module(root / "targeted_acceptance_plan.py", "acceptance_plan_v1133")
    reconciler = load_module(root / "native_evidence_reconciliation.py", "acceptance_reconciler_v1131")
    gates = reconciler.load_gates(root)
    scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))
    issues, _, missing = planner.validate(gates, scenarios)
    if issues or missing: raise ValueError("Invalid acceptance plan: " + "; ".join(issues + [f"Unmapped: {sorted(missing)}"] ))
    return gates, {item["id"]: item for item in scenarios}, reconciler


def read_ledger(path, gates, reconciler):
    observations = json.loads(path.read_text(encoding="utf-8"))
    accepted, issues = reconciler.reconcile(gates, observations)
    if issues: raise ValueError("Invalid ledger: " + "; ".join(issues))
    return observations, accepted


def show_scenario(scenario):
    return (f"{scenario['id']} — {scenario['title']}\n"
            f"Scope: {scenario['scope']}/{scenario['capability']}\n"
            f"Gates: {', '.join(scenario['gates'])}\n"
            f"Steps: {scenario['steps']}\nExpected: {scenario['expected']}\n"
            "Record each gate separately only after observing its specific condition.")


def status(scenarios, accepted):
    lines = ["# PersonLens v1.13.4 native acceptance observations", "",
             "| Scenario | Passed | Failed | Unobserved |", "| --- | ---: | ---: | ---: |"]
    totals = [0, 0, 0]
    for scenario in scenarios.values():
        states = [accepted.get((scenario["scope"], scenario["capability"], gate), {}).get("result")
                  for gate in scenario["gates"]]
        counts = [states.count("pass"), states.count("fail"), states.count(None)]
        totals = [a + b for a, b in zip(totals, counts)]
        lines.append(f"| {scenario['id']} | {counts[0]} | {counts[1]} | {counts[2]} |")
    lines.extend(["", f"**Total:** {totals[0]} passed · {totals[1]} failed · {totals[2]} unobserved.",
                  "These are reported observations, not automatic approval to retire legacy code."])
    return "\n".join(lines)


def make_observation(scenario, gate, result, environment, observation, observed_at=None):
    if gate not in scenario["gates"]: raise ValueError(f"Gate '{gate}' is not mapped to {scenario['id']}")
    if result not in ("pass", "fail"): raise ValueError("Result must be pass or fail")
    if not environment.strip() or not observation.strip(): raise ValueError("Environment and observation are required")
    return {"scope": scenario["scope"], "capability": scenario["capability"], "gate": gate,
            "result": result, "environment": environment.strip(),
            "observed_at": observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "observation": observation.strip(), "scenario_id": scenario["id"]}


def append_observation(path, gates, reconciler, observation):
    """Exclusive lock plus atomic replacement; never silently replace an earlier observation."""
    lock_path = path.with_name(path.name + ".lock")
    lock_fd = None
    temporary = None
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        entries, accepted = read_ledger(path, gates, reconciler)
        key = (observation["scope"], observation["capability"], observation["gate"])
        if key in accepted: raise ValueError(f"Already recorded: {'/'.join(key)}; review the ledger manually")
        if key[0] not in gates or key[1] not in gates[key[0]] or key[2] not in gates[key[0]][key[1]]:
            raise ValueError(f"Unknown evidence gate: {'/'.join(key)}")
        entries.append(observation)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".acceptance-",
                                         suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(entries, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
        if lock_fd is not None:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Guide and record witnessed native acceptance checks")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--scenarios", type=Path, default=Path("targeted_acceptance_scenarios.json"))
    parser.add_argument("--ledger", type=Path, default=Path("native_acceptance_ledger.json"))
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--list", action="store_true", help="Show unobserved/pass/fail counts")
    actions.add_argument("--show", metavar="ID", help="Show scenario steps and expected results")
    actions.add_argument("--init-ledger", action="store_true", help="Create empty ledger; never overwrite")
    actions.add_argument("--record", metavar="ID", help="Record one observed gate from a scenario")
    parser.add_argument("--gate")
    parser.add_argument("--result", choices=("pass", "fail"))
    parser.add_argument("--environment", help="Concrete Windows/Python/Qt/fixture environment")
    parser.add_argument("--observation", help="Specific observed outcome, including fixture and evidence")
    args = parser.parse_args(argv)
    try:
        gates, scenarios, reconciler = load_plan(args.root, args.scenarios)
        if args.init_ledger:
            with args.ledger.open("x", encoding="utf-8") as stream: stream.write("[]\n")
            print(f"Created empty ledger: {args.ledger}")
        elif args.show:
            if args.show not in scenarios: raise ValueError(f"Unknown scenario: {args.show}")
            print(show_scenario(scenarios[args.show]))
        elif args.list:
            _, accepted = read_ledger(args.ledger, gates, reconciler)
            print(status(scenarios, accepted))
        else:
            if args.record not in scenarios: raise ValueError(f"Unknown scenario: {args.record}")
            if any(value is None for value in (args.gate, args.result, args.environment, args.observation)):
                raise ValueError("Recording requires --gate, --result, --environment and --observation")
            record = make_observation(scenarios[args.record], args.gate, args.result, args.environment, args.observation)
            append_observation(args.ledger, gates, reconciler, record)
            print(f"Recorded {args.record}/{args.gate}: {args.result}; no other gates changed")
    except (OSError, ValueError, json.JSONDecodeError) as exc: parser.error(str(exc))
    return 0


if __name__ == "__main__": raise SystemExit(main())
