"""Immutable source evidence for explicitly selected KB reference encoding."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ReferenceSourceSnapshot:
    folder: str
    members: tuple[tuple[str, int, int], ...]
    selected: tuple[tuple[str, int, int, str], ...]


def capture_reference_sources(folder: str | Path, paths: Sequence[str], extensions: tuple[str, ...]) -> ReferenceSourceSnapshot:
    """Reject foreign, ambiguous, missing and changed image inputs before encoding."""
    root = Path(folder).absolute()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("The KB person directory is missing or is a symbolic link.")
    if not isinstance(paths, (list, tuple)) or not paths:
        raise ValueError("Select at least one KB reference image.")
    allowed = {ext.lower() for ext in extensions}
    members = []
    for image in root.iterdir():
        if image.suffix.lower() not in allowed:
            continue
        if image.is_symlink():
            raise ValueError(f"Symbolic links are not supported in KB reference sets: {image.name}")
        if image.is_file():
            stat = image.stat()
            members.append((image.name, stat.st_size, stat.st_mtime_ns))
    members.sort()
    names = {item[0] for item in members}
    selected = []
    seen = set()
    for raw in paths:
        if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
            raise ValueError("Selected KB images require absolute paths.")
        image = Path(raw)
        if image.parent != root or image.name not in names or image.name in seen or image.is_symlink():
            raise ValueError(f"Invalid or duplicate KB reference input: {raw}")
        seen.add(image.name)
        stat = image.stat()
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        after = image.stat()
        if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"KB image changed while reading: {image.name}")
        selected.append((image.name, stat.st_size, stat.st_mtime_ns, digest))
    return ReferenceSourceSnapshot(str(root), tuple(members), tuple(selected))


def verify_reference_sources(snapshot: ReferenceSourceSnapshot, extensions: tuple[str, ...]) -> None:
    current = capture_reference_sources(snapshot.folder, [str(Path(snapshot.folder) / row[0]) for row in snapshot.selected], extensions)
    if current != snapshot:
        raise ValueError("KB reference sources changed since review; reassess the selection.")
