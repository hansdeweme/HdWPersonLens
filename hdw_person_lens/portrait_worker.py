"""One disposable native portrait-analysis process; no Qt or application startup."""
from __future__ import annotations

import contextlib
import faulthandler
import json
import os
import sys


def main():
    if os.name == "nt":
        import ctypes
        # A child access violation must not leave a modal Windows crash dialog.
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    faulthandler.enable()
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))

    class Sources:
        def get_person_image_paths(self, name):
            return request["paths"]

    # Preserve stdout exclusively for PNG bytes, including during native imports.
    with contextlib.redirect_stdout(sys.stderr):
        from .person_portrait_service import PersonPortraitService
        service = PersonPortraitService(
            Sources(), size=request["size"], max_candidates=request["max_candidates"],
            cache_dir=request["cache_dir"],
        )
        data = service.get_portrait(request["name"])
    if data:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
