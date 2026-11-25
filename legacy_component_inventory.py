"""Read-only PersonLens v1.13.0 legacy-component rationalization report."""

import argparse
import importlib.util
import json
from pathlib import Path


SELECTED = ("add", "rename", "remove", "images", "reencode")
INDEPENDENT = {
    "db_editor": "Standalone schema administration, record creation, file reload and DB-only deletion remain independent.",
    "legacy_browser": "Legacy query/filter/export parity has not been certified against the Workbench.",
    "global_encoding": "Global all-person encoding has no equivalent selected-person Workbench operation.",
}


def load_audit(path):
    if not path.is_file(): return None
    spec = importlib.util.spec_from_file_location(f"personlens_audit_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_evidence(path):
    if path is None: return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict): raise ValueError(f"Evidence must be a JSON object: {path}")
    return data


def rationalize(workspace_results, management_results):
    """A positive integration result never independently authorizes code retirement."""
    result = {}
    for name in SELECTED:
        entry = management_results.get(name)
        status = entry.get("decision") if isinstance(entry, dict) else None
        if status == "REVIEW FOR RETIREMENT":
            decision = "MANUAL REVIEW"
            reason = "Management parity gates passed; native end-to-end sign-off and separate removal approval still required."
        else:
            decision = "KEEP"
            reason = entry.get("reason", "Management audit evidence unavailable.") if isinstance(entry, dict) else "Management audit unavailable."
        result[name] = {"decision": decision, "reason": reason, "management_audit": status or "UNAVAILABLE"}
    for name, reason in INDEPENDENT.items():
        result[name] = {"decision": "KEEP", "reason": reason,
                        "workspace_audit": workspace_results.get(name, {}).get("decision", "UNAVAILABLE")}
    for name in ("profile", "navigation", "roster", "advanced_tools"):
        status = workspace_results.get(name, {}).get("decision", "UNAVAILABLE")
        result[f"workspace_{name}"] = {"decision": "INTEGRATION VERIFIED" if status == "ACCEPTED" else "VERIFY",
                                       "reason": f"Workspace parity: {status}; this is not a legacy retirement decision.",
                                       "workspace_audit": status}
    return result


def markdown(result):
    lines = ["# PersonLens v1.13.0 legacy component rationalization", "", "| Component | Decision | Reason |",
             "| --- | --- | --- |"]
    for name, item in result.items():
        lines.append(f"| {name} | {item['decision']} | {item['reason']} |")
    lines.extend(["", "Read-only inventory. No code is modified or marked safe for automatic deletion.",
                  "MANUAL REVIEW requires explicit approval and a separate verified removal change."])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only PersonLens legacy component inventory")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--workspace-evidence", type=Path)
    parser.add_argument("--management-evidence", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        workspace_evidence = read_evidence(args.workspace_evidence)
        management_evidence = read_evidence(args.management_evidence)
    except (OSError, ValueError, json.JSONDecodeError) as exc: parser.error(str(exc))
    workspace = load_audit(args.root / "workspace_parity_audit.py")
    management = load_audit(args.root / "management_retirement_audit.py")
    workspace_results = workspace.decide(workspace.inspect(args.root), workspace_evidence) if workspace else {}
    management_results = management.decide(management.inspect(args.root), management_evidence) if management else {}
    result = rationalize(workspace_results, management_results)
    print(json.dumps(result, indent=2) if args.json else markdown(result))
    return 0


if __name__ == "__main__": raise SystemExit(main())
