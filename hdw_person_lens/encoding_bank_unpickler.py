# encoding_bank_unpickler.py
# Safer loading of pickle files
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of encoded face and body traits of known individuals and their associated media.
#

import sys
import pickle
from pathlib import Path
from typing import Any
import numpy as np

class EncodingBankUnpickler(pickle.Unpickler):
    SAFE_GLOBALS = {
        # NumPy array reconstruction, NumPy 1.x / compatibility paths
        ("numpy", "ndarray"),
        ("numpy", "dtype"),
        ("numpy.core.multiarray", "_reconstruct"),
        ("numpy.core.multiarray", "scalar"),
        ("numpy.core.numeric", "_frombuffer"),

        # NumPy array reconstruction, NumPy 2.x paths
        ("numpy._core.multiarray", "_reconstruct"),
        ("numpy._core.multiarray", "scalar"),
        ("numpy._core.numeric", "_frombuffer"),

        # Plain container/value types
        ("builtins", "dict"),
        ("builtins", "list"),
        ("builtins", "tuple"),
        ("builtins", "str"),
        ("builtins", "int"),
        ("builtins", "float"),
        ("builtins", "bool"),
        ("builtins", "bytes"),
        ("builtins", "bytearray"),
        ("builtins", "NoneType"),
        
        # Older protocol-2 pickles, may also need this:
        ("_codecs", "encode"),
    }

    def find_class(self, module, name):
        if (module, name) in self.SAFE_GLOBALS:
            return super().find_class(module, name)
        msg = f"Forbidden pickle global: {module}.{name}"
        print(f"[EncodingBankUnpickler] {msg}", file=sys.stderr, flush=True)
        raise pickle.UnpicklingError(msg)

def _load_restricted_pickle(path: str | Path, *, max_bytes=512 * 1024 * 1024) -> Any:
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError(f"Encoding bank is too large: {path.stat().st_size:,} bytes")
    with path.open("rb") as stream:
        return EncodingBankUnpickler(stream).load()
    
def _as_vector_list(value, *, name: str, expected_dim: int | None = None) -> list[np.ndarray]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list or tuple")

    vectors = []
    for index, vec in enumerate(value):
        arr = np.asarray(vec, dtype=np.float32)
        if arr.ndim != 1:
            raise ValueError(f"{name}[{index}] must be a 1D vector")
        if expected_dim is not None and arr.shape[0] != expected_dim:
            raise ValueError(f"{name}[{index}] has dimension {arr.shape[0]}, expected {expected_dim}")
        if arr.shape[0] < 1:
            raise ValueError(f"{name}[{index}] is empty")
        if not np.isfinite(arr).all():
            raise ValueError(f"{name}[{index}] contains NaN or infinite values")
        vectors.append(arr)
    return vectors

def _as_name_list(value, *, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list or tuple")
    names = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name}[{index}] must be a non-empty string")
        names.append(item.strip())
    return names

def validate_encoding_bank(bank: Any) -> dict:
    if not isinstance(bank, dict):
        raise ValueError("Encoding bank must be a dictionary")

    face_encodings = _as_vector_list(bank.get("face_encodings", []), name="face_encodings", expected_dim=128)
    face_names = _as_name_list(bank.get("face_names", []), name="face_names")
    body_encodings = _as_vector_list(bank.get("body_encodings", []), name="body_encodings")
    body_names = _as_name_list(bank.get("body_names", []), name="body_names")
    metadata = bank.get("metadata", {})

    if len(face_encodings) != len(face_names):
        raise ValueError(f"face_encodings / face_names count mismatch: {len(face_encodings)} vs {len(face_names)}")
    if len(body_encodings) != len(body_names):
        raise ValueError(f"body_encodings / body_names count mismatch: {len(body_encodings)} vs {len(body_names)}")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be a dictionary")

    body_dims = {int(vec.shape[0]) for vec in body_encodings}
    if len(body_dims) > 1:
        raise ValueError(f"Mixed body embedding dimensions found: {sorted(body_dims)}")

    return {"face_encodings": face_encodings, "face_names": face_names, "body_encodings": body_encodings, "body_names": body_names, "metadata": metadata or {}}


def load_encoding_bank(path: str | Path) -> dict:
    return validate_encoding_bank(_load_restricted_pickle(path))    