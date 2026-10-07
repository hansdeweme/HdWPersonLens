#kb_compare.copy
import itertools
import numpy as np

# generic compare helpers
def _pairwise_person_distances(person_to_vecs: dict, *, min_images_per_person=1, dist_fn=None):
    """
    person_to_vecs: {name: [vec, vec, ...]} with each vec as (D,)
    dist_fn: (vecs_B_2d, vecA_1d) -> 1D array distances
            Must return distances where lower = more similar (like face_distance).
    Returns: list of (name_a, name_b, avg_dist, min_dist)
    """
    # filter
    filtered = {k: v for k, v in person_to_vecs.items() if len(v) >= min_images_per_person}
    names = sorted(filtered.keys())
    results = []
    for name_a, name_b in itertools.combinations(names, 2):
        vecs_a = filtered[name_a]
        vecs_b = filtered[name_b]
        if not vecs_a or not vecs_b:
            continue
        # Make B once as (nB, D)
        B = np.asarray(vecs_b, dtype=np.float32)
        if B.ndim != 2:
            continue
        distances = []
        for va in vecs_a:
            d = dist_fn(B, np.asarray(va, dtype=np.float32))
            if d is not None and len(d):
                distances.extend(d)
        if distances:
            avg_dist = round(float(np.mean(distances)), 4)
            min_dist = round(float(np.min(distances)), 4)
            results.append((name_a, name_b, avg_dist, min_dist))
    results.sort(key=lambda x: x[3])
    return results

