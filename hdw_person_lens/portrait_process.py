"""Keep native portrait analysis outside the Qt application's process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock


class PortraitProcessRunner:
    def __init__(self, service, *, timeout=120):
        self.service = service
        self.timeout = timeout
        self._lock = Lock()
        self._processes = set()
        self._closed = False

    def get_portrait(self, name):
        # Only filesystem inspection happens here; dlib runs in the child.
        request = self.service.prepare_request(name)
        if not request.sources:
            return None
        hit, cached = self.service.cached_portrait(name, request.sources, signature=request.signature)
        if hit:
            return cached
        payload = json.dumps({
            "name": name, "preferred": request.preferred,
            "sources": request.sources, "signature": request.signature,
            "size": self.service.size, "max_candidates": self.service.max_candidates,
            "cache_dir": str(self.service.cache_dir.resolve()),
        }).encode("utf-8")
        with self._lock:
            if self._closed:
                return None
            process = subprocess.Popen(
                [sys.executable, "-m", "hdw_person_lens.portrait_worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(Path(__file__).resolve().parents[1]),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._processes.add(process)
        try:
            try:
                output, errors = process.communicate(payload, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise RuntimeError("Portrait analysis timed out") from None
            with self._lock:
                if self._closed:
                    return None
            if process.returncode:
                code = f"0x{process.returncode & 0xffffffff:08X}"
                detail = errors.decode("utf-8", errors="replace")[-2000:].strip()
                raise RuntimeError(f"Portrait process exited with {code}. {detail}")
            if output and not output.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("Portrait process returned invalid image data")
            return output or None
        finally:
            try:
                # communicate() can itself fail (for example, a broken pipe).
                # Never drop tracking while a child could still be running.
                if process.poll() is None:
                    process.kill()
                try:
                    # Finish any Windows pipe-reader threads before closing pipes.
                    process.communicate()
                except (OSError, ValueError):
                    pass
                finally:
                    process.wait()
            finally:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
                with self._lock:
                    self._processes.discard(process)

    def close(self):
        # Prevent new children before terminating those currently being awaited.
        with self._lock:
            self._closed = True
            for process in self._processes:
                if process.poll() is None:
                    process.kill()
