"""Summarize reported checks without treating historical smoke tests as sign-off."""

import argparse
import json
from pathlib import Path


ACTIONS = ("add", "rename", "remove", "images", "reencode")
GATES = ("qt", "db_backed", "kb_only", "cancellation", "failure", "rollback", "context", "freshness", "activity")
STATUSES = {"not_recorded", "partial", "ready_for_review", "certified"}


def validate(ledger):
    if not isinstance(ledger, dict) or set(ledger) != set(ACTIONS): raise ValueError("Ledger needs exactly five actions")
    for action, gates in ledger.items():
        if not isinstance(gates, dict) or set(gates) != set(GATES): raise ValueError(f"Wrong gates for {action}")
        for gate, entry in gates.items():
            if not isinstance(entry, dict) or entry.get("status") not in STATUSES: raise ValueError(f"Invalid {action}.{gate}")
            if not isinstance(entry.get("notes"), str): raise ValueError(f"Missing notes for {action}.{gate}")
            if entry["status"] == "certified" and not entry.get("evidence_id"): raise ValueError(f"Missing evidence ID for {action}.{gate}")
    return ledger


def audit_evidence(ledger):
    """Export only explicitly certified gates in the v1.10.1 audit's input format."""
    validate(ledger)
    return {action: {gate: entry["status"] == "certified" for gate, entry in gates.items()} for action, gates in ledger.items()}


def report(ledger):
    validate(ledger)
    lines = ["# Management acceptance evidence — review ledger", "",
             "Historical reports are leads, not automatic native certification.", "",
             "| Action | Certified | Partial or ready for review | Not recorded |", "| --- | ---: | ---: | ---: |"]
    for action, gates in ledger.items():
        counts = {status: sum(item["status"] == status for item in gates.values()) for status in STATUSES}
        lines.append(f"| {action} | {counts['certified']}/9 | {counts['partial'] + counts['ready_for_review']} | {counts['not_recorded']} |")
    lines.extend(["", "## Gate-level follow-up", ""])
    for action, gates in ledger.items():
        lines.append(f"### {action.title()}")
        lines.append("")
        for gate, item in gates.items():
            if item["status"] != "certified": lines.append(f"- **{gate}** ({item['status']}): {item['notes']}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only evidence consolidation")
    parser.add_argument("--ledger", type=Path, default=Path(__file__).with_name("evidence_ledger.json"))
    parser.add_argument("--export", type=Path, help="Write audit-compatible booleans (never modifies the PersonLens checkout)")
    args = parser.parse_args(argv)
    ledger = validate(json.loads(args.ledger.read_text(encoding="utf-8")))
    if args.export: args.export.write_text(json.dumps(audit_evidence(ledger), indent=2) + "\n", encoding="utf-8")
    print(report(ledger))
    return 0


if __name__ == "__main__": raise SystemExit(main())
