"""Structural image-preview regression checks; native Qt lifecycle tests remain required."""

import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "person_workbench_images.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def method(owner, name):
    cls = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == owner)
    return ast.unparse(next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name))


class PendingPreviewContractTests(unittest.TestCase):
    def test_thumbnail_decode_is_worker_only(self):
        self.assertIn("QImageReader(self.path)", method("_ThumbJob", "run"))
        self.assertIn("setScaledSize", method("_ThumbJob", "run"))
        self.assertIn("signals.loaded.emit", method("_ThumbJob", "run"))
        self.assertNotIn("QPixmap", method("_ThumbJob", "run"))

    def test_stale_results_are_rejected(self):
        delivery = method("WorkbenchImageEditor", "_thumb_loaded")
        self.assertIn("generation != self._thumb_generation", delivery)
        self.assertIn("key not in self.additions", delivery)
        self.assertIn("image_signature(self.additions[key]) != signature", delivery)
        self.assertIn("QPixmap.fromImage(image)", delivery)

    def test_pending_render_uses_bounded_queue(self):
        panel = SOURCE.read_text(encoding="utf-8")
        self.assertIn("self._thumb_pool.setMaxThreadCount(2)", panel)
        self.assertIn("self.pending.setIconSize(QSize(72, 72))", panel)
        self.assertIn("self._cancel_queued_thumbs()", method("WorkbenchImageEditor", "_render"))
        self.assertIn("self._request_thumb(item, key, path)", method("WorkbenchImageEditor", "_render"))

    def test_shutdown_reaps_decoder_jobs(self):
        shutdown = method("WorkbenchImageEditor", "shutdown")
        self.assertIn("self._thumb_pool.waitForDone()", shutdown)
        self.assertIn("self._thumb_jobs.clear()", shutdown)
        self.assertIn("thread.wait()", shutdown)

    def test_preview_does_not_change_transaction_inputs(self):
        applying = method("WorkbenchImageEditor", "_apply")
        self.assertIn("_CheckedImageWorker(self.service, name, additions, removals, expected_paths, expected_snapshot)", applying)
        self.assertNotIn("_thumb_cache", applying)


if __name__ == "__main__": unittest.main()
