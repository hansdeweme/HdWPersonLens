"""Read-only PersonLens workspace integration and retirement-gate audit."""
import argparse
import ast
import json
from pathlib import Path


GATES = {
    "profile": ("qt", "db_backed", "kb_only", "validation", "conflict", "unsaved", "standalone"),
    "navigation": ("qt", "exact_person", "context", "unsaved", "missing_person", "tab_switch"),
    "roster": ("qt", "search", "sort", "source_filter", "portraits", "unsaved", "refresh"),
}
RETAINED = {
    "db_editor": "Standalone schema administration, DB-only deletion, file reload and record creation remain independent.",
    "legacy_browser": "Legacy query/filter/export behavior has not received full feature-parity certification.",
    "global_encoding": "All-person re-encoding is separate from selected-person Workbench encoding.",
    "management_dialogs": "Selected-person dialog retirement is governed by management_retirement_audit.py.",
}


def source(root, filename):
    path = root / "hdw_person_lens" / filename
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def methods(text, name):
    if not text: return set()
    try: tree = ast.parse(text)
    except SyntaxError: return set()
    cls = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name), None)
    return {node.name for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))} if cls else set()


def inspect(root):
    workbench = source(root, "persons_workbench.py")
    main = source(root, "recognition_gui.py")
    panel = source(root, "person_profile_panel.py")
    db = source(root, "person_db_gui.py")
    policy = source(root, "person_roster_filter_policy.py")
    return {
        "profile": {
            "shared_form": "SchemaForm(" in panel and "PersonProfilePanel(" in workbench,
            "merge": "merge_profile(" in workbench,
            "validation": "Draft202012Validator(self.profile_schema)" in workbench,
            "write_conflict": "with self.person_db._write_lock():" in workbench and "current != self._profile_original" in workbench,
            "unsaved_guard": "_confirm_leave_profile" in methods(workbench, "PersonsWorkbench"),
            "standalone_editor": "PersonDbEditorWidget" in db,
        },
        "navigation": {
            "advanced_route": "advanced_editor_requested.connect(self.open_advanced_person)" in main,
            "exact_target": "name != self.person_context.name" in main and "editor.select_person(name)" in main,
            "unsaved_destination": "editor.has_unsaved_changes()" in main,
            "unsaved_source": "self.persons_workbench._confirm_leave_profile()" in main,
            "missing_record": "self.person_db.get_by_name(name) is None" in main,
            "shared_context": "PersonContext()" in main,
        },
        "roster": {
            "shared_model": "PersonRosterModel(" in workbench and "combined_roster(" in workbench,
            "nested_search": "search_terms(record)" in policy,
            "source_filter": "record_matches_filters(" in policy and "set_source_mode" in workbench,
            "portrait_workers": "_schedule_visible_portraits" in methods(workbench, "PersonsWorkbench"),
            "refresh": "refresh" in methods(workbench, "PersonsWorkbench"),
        },
        "db_editor": {"standalone": "PersonDbEditorWidget" in db, "db_delete": "on_delete" in methods(db, "PersonDbEditorWidget")},
        "legacy_browser": {"entry_point": "query_persons" in methods(main, "MainWindow")},
        "global_encoding": {"entry_point": "reencode_knowledge_base" in methods(main, "MainWindow")},
        "management_dialogs": {"separate_audit": (root / "management_retirement_audit.py").is_file()},
    }


def decide(findings, evidence):
    result = {}
    for capability, checks in findings.items():
        if capability in RETAINED:
            result[capability] = {"decision": "KEEP", "reason": RETAINED[capability], "checks": checks}
            continue
        missing = [key for key, passed in checks.items() if not passed]
        certified = evidence.get(capability, {})
        certified = certified if isinstance(certified, dict) else {}
        pending = [key for key in GATES[capability] if certified.get(key) is not True]
        if missing: decision, reason = "INCOMPLETE", f"Structural gaps: {', '.join(missing)}"
        elif pending: decision, reason = "VERIFY", f"Native evidence missing: {', '.join(pending)}"
        else: decision, reason = "ACCEPTED", "Integration gates recorded; retirement remains a separate decision"
        result[capability] = {"decision": decision, "reason": reason, "checks": checks}
    return result


def markdown(result):
    lines = ["# PersonLens v1.11.5 workspace parity audit", "", "| Capability | Decision | Reason |",
             "| --- | --- | --- |"]
    lines.extend(f"| {name} | {item['decision']} | {item['reason']} |" for name, item in result.items())
    lines.extend(["", "This is a read-only structural/evidence audit, not an authorization to delete legacy code.",
                  "An ACCEPTED integration decision does not imply that Persons DB or the legacy browser can be removed."])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only PersonLens workspace parity audit")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--evidence", type=Path, help="Optional JSON of completed native acceptance gates")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else {}
    if not isinstance(evidence, dict): parser.error("Evidence must be a JSON object")
    result = decide(inspect(args.root), evidence)
    print(json.dumps(result, indent=2) if args.json else markdown(result))
    return 0


if __name__ == "__main__": raise SystemExit(main())
