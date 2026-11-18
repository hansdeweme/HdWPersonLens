"""Read-only, bounded KB portrait selection and disk cache for PersonLens."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .kb_faces import extract_primary_face_embedding
from .kb_gallery_optimizer import _face_quality_score, _quick_image_quality


class PersonPortraitService:
    VERSION = 1

    def __init__(self, person_service, settings=None, *, max_candidates=24, size=224, cache_dir=None):
        self.person_service = person_service
        self.settings = settings or {}
        self.max_candidates = max(1, int(max_candidates))
        self.size = max(64, int(size))
        default_cache = Path.home() / ".cache" / "HdWPersonLens" / "portraits"
        self.cache_dir = Path(cache_dir or self.settings.get("portrait_cache_dir") or default_cache).expanduser()

    def _sources(self, name):
        paths = self.person_service.get_person_image_paths(name)[:self.max_candidates]
        records = []
        for raw in paths:
            path = Path(raw)
            try:
                stat = path.stat()
                records.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
            except OSError:
                continue
        return records

    def _cache_paths(self, name):
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.json", self.cache_dir / f"{digest}.png"

    def _signature(self, name, sources):
        payload = {"version": self.VERSION, "name": name, "size": self.size, "max_candidates": self.max_candidates,
                   "sources": sources, "pipeline": "primary_face_original_rgb_v1"}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def cached_portrait(self, name, sources):
        """Read cached results without entering the native image pipeline."""
        signature = self._signature(name, sources)
        meta_path, image_path = self._cache_paths(name)
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(metadata, dict) and metadata.get("signature") == signature:
                if metadata.get("empty"): return True, None
                data = image_path.read_bytes()
                if data.startswith(b"\x89PNG\r\n\x1a\n"):
                    return True, data
        except (OSError, ValueError, TypeError):
            pass
        return False, None

    def get_portrait(self, name: str) -> bytes | None:
        """Return PNG bytes or None. Run native analysis in a disposable process."""
        sources = self._sources(name)
        if not sources: return None
        hit, cached = self.cached_portrait(name, sources)
        if hit: return cached
        signature = self._signature(name, sources)
        meta_path, image_path = self._cache_paths(name)

        best = None
        for raw, _, _ in sources:
            try:
                with Image.open(raw) as opened:
                    image = ImageOps.exif_transpose(opened).convert("RGB")
                embedding, info = extract_primary_face_embedding(image, context="portrait")
                if embedding is None or info.get("detected_count") != 1 or not info.get("selected_bbox"): continue
                analysis = image.copy()
                analysis.thumbnail((640, 640), Image.Resampling.LANCZOS)
                quality = _quick_image_quality(np.asarray(analysis, dtype=np.uint8))
                score = _face_quality_score(quality, info.get("face_width_fraction"))
                if best is None or score > best[0]: best = (score, raw, image, info["selected_bbox"])
            except (OSError, ValueError, RuntimeError, TypeError):
                continue
        if best is None:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._atomic_bytes(meta_path, json.dumps({"signature": signature, "empty": True}).encode("utf-8"))
            except OSError:
                pass
            return None

        _, source, image, (top, right, bottom, left) = best
        center_x, center_y = (left + right) / 2, (top + bottom) / 2
        side = max(right - left, bottom - top) * 2.1
        side = min(max(1, side), image.width, image.height)
        x0 = min(max(0, round(center_x - side / 2)), max(0, image.width - round(side)))
        y0 = min(max(0, round(center_y - side / 2)), max(0, image.height - round(side)))
        crop = image.crop((x0, y0, x0 + round(side), y0 + round(side))).resize((self.size, self.size), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        crop.save(output, format="PNG")
        data = output.getvalue()
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._atomic_bytes(image_path, data)
            self._atomic_bytes(meta_path, json.dumps({"signature": signature, "source": source}).encode("utf-8"))
        except OSError:
            pass  # Cache failures must not block a usable portrait.
        return data

    @staticmethod
    def _atomic_bytes(target: Path, data: bytes):
        fd, temp = tempfile.mkstemp(prefix=".portrait-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as stream: stream.write(data)
            os.replace(temp, target)
        finally:
            if os.path.exists(temp): os.unlink(temp)
