# benchmark_pairwise_distances.py
from __future__ import annotations

import argparse, itertools, statistics, time
from collections.abc import Callable

import numpy as np

from kb_compare import _pairwise_person_distances as final_pairwise_person_distances


def basic_inner_outer_loop(person_to_vecs: dict[str, list[np.ndarray]], *, min_images_per_person=1):
    names = sorted(name for name, vecs in person_to_vecs.items() if len(vecs) >= min_images_per_person)
    results = []
    for name_a, name_b in itertools.combinations(names, 2):
        vecs_a = person_to_vecs[name_a]
        B = np.asarray(person_to_vecs[name_b], dtype=np.float32)
        distances = []
        for va in vecs_a:
            va = np.asarray(va, dtype=np.float32)
            d = np.linalg.norm(B - va, axis=1)
            distances.extend(d.tolist())
        if distances:
            results.append((name_a, name_b, round(float(np.mean(distances)), 4), round(float(np.min(distances)), 4)))
    results.sort(key=lambda row: row[3])
    return results


def precomputed_matrices_inner_loop(person_to_vecs: dict[str, list[np.ndarray]], *, min_images_per_person=1):
    matrices = {}
    for name, vecs in person_to_vecs.items():
        if len(vecs) < min_images_per_person:
            continue
        mat = np.asarray(vecs, dtype=np.float32)
        if mat.ndim == 2 and mat.shape[0] > 0 and np.isfinite(mat).all():
            matrices[name] = mat

    results = []
    for name_a, name_b in itertools.combinations(sorted(matrices), 2):
        A = matrices[name_a]
        B = matrices[name_b]
        if A.shape[1] != B.shape[1]:
            continue
        distances = []
        for va in A:
            d = np.linalg.norm(B - va, axis=1)
            distances.extend(d.tolist())
        if distances:
            results.append((name_a, name_b, round(float(np.mean(distances)), 4), round(float(np.min(distances)), 4)))
    results.sort(key=lambda row: row[3])
    return results


def make_synthetic_bank(*, persons=200, vectors_per_person=8, dims=128, seed=42) -> dict[str, list[np.ndarray]]:
    rng = np.random.default_rng(seed)
    return {f"Person_{i:04d}": [rng.normal(size=dims).astype(np.float32) for _ in range(vectors_per_person)] for i in range(persons)}


def time_once(fn: Callable, person_to_vecs: dict[str, list[np.ndarray]], *, min_images_per_person: int):
    t0 = time.perf_counter()
    result = fn(person_to_vecs, min_images_per_person=min_images_per_person)
    return time.perf_counter() - t0, result


def benchmark(fn: Callable, person_to_vecs: dict[str, list[np.ndarray]], *, min_images_per_person: int, repeats: int, warmups: int):
    for _ in range(warmups):
        fn(person_to_vecs, min_images_per_person=min_images_per_person)

    times = []
    last_result = None
    for _ in range(repeats):
        elapsed, last_result = time_once(fn, person_to_vecs, min_images_per_person=min_images_per_person)
        times.append(elapsed)

    return {"name": fn.__name__, "times": times, "best": min(times), "median": statistics.median(times), "mean": statistics.mean(times), "rows": len(last_result or []), "result": last_result}


def result_signature(result, *, n=10):
    return [(a, b, avg, mn) for a, b, avg, mn in result[:n]]


def check_results(results: list[dict]) -> None:
    baseline = results[0]["result"]
    baseline_rows = len(baseline)
    baseline_sig = result_signature(baseline)

    print("\nCorrectness sanity check")
    print("------------------------")
    for item in results:
        rows_ok = len(item["result"]) == baseline_rows
        sig_ok = result_signature(item["result"]) == baseline_sig
        print(f"{item['name']:<34} rows_ok={rows_ok!s:<5} top10_ok={sig_ok!s:<5}")


def print_table(results: list[dict]) -> None:
    baseline_best = results[0]["best"]
    print("\nBenchmark results")
    print("-----------------")
    print(f"{'function':<34} {'rows':>10} {'best':>10} {'median':>10} {'mean':>10} {'speedup':>10}")
    for item in results:
        speedup = baseline_best / item["best"] if item["best"] > 0 else float("inf")
        print(f"{item['name']:<34} {item['rows']:>10} {item['best']:>10.4f} {item['median']:>10.4f} {item['mean']:>10.4f} {speedup:>9.2f}x")


def main():
    parser = argparse.ArgumentParser(description="Benchmark person-pair embedding distance implementations.")
    parser.add_argument("--persons", type=int, default=200)
    parser.add_argument("--vectors", type=int, default=8)
    parser.add_argument("--dims", type=int, default=128)
    parser.add_argument("--min-images", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("Synthetic benchmark input")
    print("-------------------------")
    print(f"persons            : {args.persons}")
    print(f"vectors per person : {args.vectors}")
    print(f"embedding dims     : {args.dims}")
    print(f"person pairs       : {args.persons * (args.persons - 1) // 2:,}")
    print(f"distances per pair : {args.vectors * args.vectors:,}")
    print(f"total distances    : {args.persons * (args.persons - 1) // 2 * args.vectors * args.vectors:,}")

    person_to_vecs = make_synthetic_bank(persons=args.persons, vectors_per_person=args.vectors, dims=args.dims, seed=args.seed)
    funcs = [basic_inner_outer_loop, precomputed_matrices_inner_loop, final_pairwise_person_distances]
    results = [benchmark(fn, person_to_vecs, min_images_per_person=args.min_images, repeats=args.repeats, warmups=args.warmups) for fn in funcs]

    print_table(results)
    check_results(results)


if __name__ == "__main__":
    main()