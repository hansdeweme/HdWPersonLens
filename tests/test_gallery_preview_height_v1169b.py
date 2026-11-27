"""Qt-free sizing contract for the v1.16.9b Gallery preview refinement."""
import ast
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "person_kb_gallery.py").read_text(encoding="utf-8")


class GalleryPreviewHeightTests(unittest.TestCase):
    def test_previews_can_expand_without_changing_decode_or_crop_lifecycle(self):
        source = ast.parse(SOURCE)
        gallery = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "PersonKBImageGallery")
        methods = {node.name: node for node in gallery.body if isinstance(node, ast.FunctionDef)}
        setup = ast.unparse(methods["__init__"])
        for label in ("self.preview", "self.crop_preview"):
            self.assertIn(f"{label}.setMaximumHeight(480)", setup)
            self.assertIn(f"{label}.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)", setup)
        self.assertIn("self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)", setup)
        for name in ("resizeEvent", "_scale_previews"):
            method = ast.unparse(methods[name])
            self.assertNotIn("_enqueue(", method)
            self.assertNotIn("_enqueue_crop(", method)


if __name__ == "__main__": unittest.main()
