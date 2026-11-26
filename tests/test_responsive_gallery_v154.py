"""Qt-free happy-path contracts for v1.15.4 Gallery resizing."""
import ast
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "person_kb_gallery.py").read_text(encoding="utf-8")


class ResponsiveGalleryTests(unittest.TestCase):
    def test_resizing_only_reflows_and_rescales_existing_previews(self):
        module = ast.parse(SOURCE)
        gallery = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "PersonKBImageGallery")
        methods = {node.name: node for node in gallery.body if isinstance(node, ast.FunctionDef)}
        resize = ast.unparse(methods["resizeEvent"])
        layout = ast.unparse(methods["_update_preview_layout"])
        scale = ast.unparse(methods["_scale_previews"])
        self.assertIn("self._update_preview_layout()", resize)
        self.assertIn("self._scale_previews", resize)
        self.assertIn("self.width() < 620", layout)
        self.assertIn("TopToBottom", layout)
        self.assertIn("LeftToRight", layout)
        self.assertIn("source.scaled(size", scale)
        for method in (resize, layout, scale):
            for forbidden in ("set_person(", "_enqueue(", "_enqueue_crop(", "_on_selection("):
                self.assertNotIn(forbidden, method)

    def test_completed_previews_keep_source_pixmaps(self):
        ast.parse(SOURCE)
        self.assertIn("self._original_image = pixmap", SOURCE)
        self.assertIn("self._crop_image = QPixmap.fromImage(image)", SOURCE)
        self.assertIn("self._original_image = QPixmap()", SOURCE)
        self.assertIn("self._crop_image = QPixmap()", SOURCE)


if __name__ == "__main__": unittest.main()
