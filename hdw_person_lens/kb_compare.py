#kb_compare.copy
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
import itertools
import numpy as np

#------------------------------------------------------------------
# highly vectorized generic compare helper
# also using pre-computing of numpy arrays outside/before the loop
#-------------------------------------------------------------------

def _as_matrix(vecs) -> np.ndarray | None:
    try:
        mat = np.asarray(vecs, dtype=np.float32)
    except Exception:
        return None
    if mat.ndim != 2 or mat.shape[0] < 1 or mat.shape[1] < 1:
        return None
    if not np.isfinite(mat).all():
        return None
    return mat

# Do not use A[:, None, :] - B[None, :, :] here: it creates an N×M×D temporary tensor
# The squared-distance identity keeps memory at N×M, so it's memory-safe!
def _pairwise_l2(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    aa = np.einsum("ij,ij->i", A, A)[:, None]
    bb = np.einsum("ij,ij->i", B, B)[None, :]
    sq = np.maximum(aa + bb - 2.0 * (A @ B.T), 0.0)
    return np.sqrt(sq, dtype=np.float32)

def _pairwise_person_distances(person_to_vecs: dict, *, min_images_per_person=1, dist_fn=None):
    """
    person_to_vecs: {name: [vec, vec, ...]} with each vec as (D,)
    dist_fn: optional legacy callable (B_2d, a_1d) -> 1D distances.
             If None, uses vectorized NumPy L2 distance.
    Returns: list of (name_a, name_b, avg_dist, min_dist)
    """
    matrices = {}
    for name, vecs in person_to_vecs.items():
        if len(vecs) < min_images_per_person:
            continue
        mat = _as_matrix(vecs)
        if mat is not None:
            matrices[name] = mat

    names = sorted(matrices.keys())
    results = []
    for name_a, name_b in itertools.combinations(names, 2):
        A = matrices[name_a]
        B = matrices[name_b]
        if A.shape[1] != B.shape[1]:
            continue
        if dist_fn is None:
            distances = _pairwise_l2(A, B)
        else:
            chunks = []
            for va in A:
                d = dist_fn(B, va)
                if d is not None and len(d):
                    chunks.append(np.asarray(d, dtype=np.float32).reshape(-1))
            if not chunks:
                continue
            distances = np.concatenate(chunks)
        if distances.size:
            results.append((name_a, name_b, round(float(np.mean(distances)), 4), round(float(np.min(distances)), 4)))
    results.sort(key=lambda row: row[3])
    return results