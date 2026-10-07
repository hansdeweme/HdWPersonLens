# kb_layout.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#


from __future__ import annotations
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
# local imports
from config import KB_SYSTEM_DIRS

def kb_system_dirs(settings: Mapping[str, Any] | None = None) -> set[str]:
    settings = settings or {}
    extra = settings.get("kb_system_dirs", [])
    if isinstance(extra, str):
        extra = [part.strip() for part in extra.split(",")]
    return {str(name).strip().casefold() for name in (set(KB_SYSTEM_DIRS) | set(extra or [])) if str(name).strip()}

def is_kb_person_dir(path: str | Path, settings: Mapping[str, Any] | None = None) -> bool:
    p = Path(path)
    if not p.is_dir():
        return False
    name = p.name.strip()
    if not name or name.startswith("."):
        return False
    return name.casefold() not in kb_system_dirs(settings)

def iter_kb_person_dirs(kb_root: str | Path, settings: Mapping[str, Any] | None = None) -> Iterator[Path]:
    root = Path(kb_root).expanduser()
    if not root.is_dir():
        return
    for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        if is_kb_person_dir(child, settings):
            yield child

def kb_person_names(kb_root: str | Path, settings: Mapping[str, Any] | None = None) -> list[str]:
    return [path.name for path in iter_kb_person_dirs(kb_root, settings)]