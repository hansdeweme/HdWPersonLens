"""Focused no-Qt tests for explicit, non-destructive native evidence recording."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_acceptance_recorder", ROOT / "native_acceptance_recorder.py")
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


class Reconciler:
    @staticmethod
    def reconcile(gates, observations):
        accepted, issues = {}, []
        for item in observations:
            key = (item["scope"], item["capability"], item["gate"])
            if key in accepted: issues.append("duplicate")
            else: accepted[key] = item
        return accepted, issues


class NativeAcceptanceRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "ledger.json"
        self.ledger.write_text("[]\n", encoding="utf-8")
        self.gates = {"workspace": {"navigation": ("context", "unsaved")}}
        self.scenario = {"id": "N02", "title": "Dirty selection", "scope": "workspace", "capability": "navigation",
                         "gates": ["context", "unsaved"], "steps": "Cancel selection", "expected": "Draft retained"}

    def record(self, gate="context", result="pass"):
        return recorder.make_observation(self.scenario, gate, result, "Windows 11 / Python 3.13 / disposable DB",
                                         "Observed exact person A retained after navigation", "2026-11-25T09:00:00+00:00")

    def test_single_explicit_observation(self):
        recorder.append_observation(self.ledger, self.gates, Reconciler, self.record())
        entries = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["scenario_id"], "N02")
        self.assertEqual(entries[0]["gate"], "context")
        self.assertIn("1 passed · 0 failed · 1 unobserved", recorder.status({"N02": self.scenario},
                  {("workspace", "navigation", "context"): entries[0]}))

    def test_duplicate_record_refused_and_preserved(self):
        recorder.append_observation(self.ledger, self.gates, Reconciler, self.record())
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "Already recorded"):
            recorder.append_observation(self.ledger, self.gates, Reconciler, self.record(result="fail"))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_unknown_gate_and_unmapped_scenario_gate_rejected(self):
        with self.assertRaisesRegex(ValueError, "not mapped"):
            recorder.make_observation(self.scenario, "qt", "pass", "Windows", "Observed")
        with self.assertRaisesRegex(ValueError, "Unknown evidence gate"):
            recorder.append_observation(self.ledger, self.gates, Reconciler,
                                        {**self.record(), "gate": "qt"})

    def test_missing_observation_rejected(self):
        with self.assertRaisesRegex(ValueError, "required"):
            recorder.make_observation(self.scenario, "context", "pass", "Windows", "  ")

    def test_malformed_or_duplicate_ledger_never_overwritten(self):
        self.ledger.write_text("not JSON", encoding="utf-8")
        with self.assertRaises(ValueError): recorder.append_observation(self.ledger, self.gates, Reconciler, self.record())
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), "not JSON")
        self.ledger.write_text(json.dumps([self.record(), self.record()]), encoding="utf-8")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "Invalid ledger"):
            recorder.append_observation(self.ledger, self.gates, Reconciler, self.record("unsaved"))
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_lock_prevents_concurrent_write(self):
        lock = self.ledger.with_name(self.ledger.name + ".lock")
        lock.write_text("busy", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            recorder.append_observation(self.ledger, self.gates, Reconciler, self.record())
        self.assertEqual(json.loads(self.ledger.read_text(encoding="utf-8")), [])

    def test_scenario_steps_are_human_readable(self):
        displayed = recorder.show_scenario(self.scenario)
        self.assertIn("Cancel selection", displayed)
        self.assertIn("Draft retained", displayed)
        self.assertIn("each gate separately", displayed)


if __name__ == "__main__": unittest.main()
