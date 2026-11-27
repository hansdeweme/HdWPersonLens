"""Read-only management-retirement inventory for an installed PersonLens checkout.

Run: python management_retirement_audit.py --root D:\\Coding\\HdWPersonLens
"""

import argparse
import ast
import json
from pathlib import Path


CAPABILITIES = {
    "add": ("add_new_person", "open_add_person", "add_to_knowledge_base"),
    "rename": ("rename_person", "open_rename", "rename_person"),
    "remove": ("remove_person", "open_remove", "remove_person"),
    "images": ("edit_person_images", "open_image_editor", "update_person_images"),
    "reencode": ("reencode_single_person", "open_reencode", "reencode_persons"),
}
LEGACY_DIALOGS = {"add": "AddPersonDialog", "rename": "AlterPersonDialog", "remove": "RemovePersonDialog",
                  "images": "EditPersonImagesDialog", "reencode": "SelectPersonDialog"}
REQUIRED_NATIVE = ("qt", "db_backed", "kb_only", "cancellation", "failure", "rollback", "context", "freshness", "activity")
INDEPENDENT = {
    "global_encoding": "Global all-person re-encoding has no Workbench-wide replacement.",
    "db_editor": "Complete schema administration and DB-only deletion remain in Persons DB Editor.",
    "legacy_browser": "Query/filter/export parity has not been certified against the legacy browser.",
}


def class_methods(source, class_name):
    tree = ast.parse(source)
    cls = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name), None)
    return {node.name: node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))} if cls else {}


def text(root, filename):
    path = root / "hdw_person_lens" / filename
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def inspect(root):
    main, workbench = text(root, "recognition_gui.py"), text(root, "persons_workbench.py")
    dialogs, service = text(root, "person_management_diags.py"), text(root, "person_service.py")
    main_methods = class_methods(main, "MainWindow") if main else {}
    workbench_methods = class_methods(workbench, "PersonsWorkbench") if workbench else {}
    service_methods = class_methods(service, "PersonService") if service else {}
    findings = {}
    for action, (legacy, native, api) in CAPABILITIES.items():
        findings[action] = {
            "principal_menu_route": f'open_workbench_management("{action}")' in main,
            "native_panel_route": native in workbench_methods,
            "administrator_legacy_route": 'legacy = admin.addMenu("Legacy Person Management Dialogs")' in main and
                f'self.{legacy}, tip="Original' in main,
            "legacy_handler": legacy in main_methods,
            "service_api": api in service_methods,
            "legacy_dialog_module": bool(class_methods(dialogs, LEGACY_DIALOGS[action])) if dialogs else False,
        }
    findings["global_encoding"] = {"legacy_handler": "reencode_knowledge_base" in main_methods}
    findings["db_editor"] = {"legacy_handler": "show_person_database" in main_methods}
    findings["legacy_browser"] = {"legacy_handler": "query_persons" in main_methods}
    return findings


def decide(findings, evidence):
    result = {}
    for capability, checks in findings.items():
        if capability in INDEPENDENT:
            result[capability] = {"decision": "KEEP", "reason": INDEPENDENT[capability], "checks": checks}
            continue
        missing = [key for key, passed in checks.items() if not passed]
        certification = evidence.get(capability, {})
        if not isinstance(certification, dict): certification = {}
        unverified = [key for key in REQUIRED_NATIVE if certification.get(key) is not True]
        if missing: decision, reason = "KEEP", f"Structural gaps: {', '.join(missing)}"
        elif unverified: decision, reason = "KEEP", f"Native evidence missing: {', '.join(unverified)}"
        else: decision, reason = "REVIEW FOR RETIREMENT", "Structural and recorded native gates passed; manual sign-off required"
        result[capability] = {"decision": decision, "reason": reason, "checks": checks}
    return result


def markdown(root, result):
    rows = ["# PersonLens management retirement audit", "", f"Source: `{root}`", "",
            "| Capability | Decision | Reason |", "| --- | --- | --- |"]
    for capability, item in result.items():
        rows.append(f"| {capability} | {item['decision']} | {item['reason']} |")
    rows.extend(["", "This report is read-only. Structural checks do not prove behavioral equivalence. ",
                 "Even REVIEW FOR RETIREMENT requires a manual approval and a separate code-removal change."])
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only PersonLens management retirement audit")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="PersonLens repository root")
    parser.add_argument("--evidence", type=Path, help="Optional native-test evidence JSON")
    parser.add_argument("--json", action="store_true", help="Print machine-readable result")
    args = parser.parse_args(argv)
    evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else {}
    if not isinstance(evidence, dict): parser.error("Evidence must be a JSON object")
    result = decide(inspect(args.root), evidence)
    print(json.dumps(result, indent=2) if args.json else markdown(args.root, result))
    return 0


if __name__ == "__main__": raise SystemExit(main())
