# PersonLens v0.8 — Diversity-Aware Reference Selection (preview)

This patch is based directly on the uploaded `hdw_person_lens(1).zip` source (19 November 2026). It changes only three existing modules:

- `kb_identity_assessment.py`: return a path-indexed pairwise Euclidean distance matrix for consensus-supported face embeddings, before deleting raw embeddings from the report. The matrix is not written to disk.
- `kb_reference_recommendations.py`: validate the distance evidence and greedily select identity-supported, nonduplicate references by technical quality and marginal face-embedding distance.
- `person_kb_recommendations.py`: show novelty alongside the technical score and expose a configurable diversity weight.

`tests/test_kb_diversity_v08.py` provides fourteen focused tests, including malformed-input subcases.

## Ranking policy

The first reference is the best technical-quality candidate. For each subsequent reference:

```
novelty = min(1, nearest_distance_to_already_selected / identity_threshold)
rank_score = (1 - diversity_weight) * technical_score + diversity_weight * novelty
```

Default `kb_gallery_diversity_weight` is **0.35**, bounded to 0–0.70. Setting it to `0` restores technical-quality-only selection. The shortlist target still uses `kb_gallery_target_size` (default 12).

This variation proxy measures **face-embedding distance**, not explicitly pose, expression, age, lighting, or demographic diversity. A high score is not proof of identity or encoding improvement. The results remain provisional and read-only.

## Preserved safeguards

- No KB file, preference, cache, bank, or schema mutation.
- Existing process isolation, cancellation tokens, shutdown/reaping, and failure handling are unchanged.
- Existing full-report completeness, duplicate exclusion, consensus, and source-freshness checks are unchanged.
- No raw biometric embeddings leave the child; only pairwise distances for supported references are returned.
- A malformed, missing, asymmetric, or mismatched matrix is rejected and the reason explicitly says diversity data was unavailable; the quality-only v0.7.3 ranking remains usable.
- Matrix paths must be unique, nonempty strings matching all consensus-supported faces, including supported duplicates excluded from ranking. Matrix rows must be numeric JSON lists; strings, booleans, nonfinite/negative values, and malformed shapes are rejected without escaping the GUI action.

## Windows validation

1. Run existing regression tests before and after the patch; ensure 53 prior tests remain passing.
2. Run `py -3.10 -m unittest test_kb_diversity_v08 -v` (or your usual interpreter).
3. Analyze a KB with independent images of the same person, varying viewpoint or expression. Confirm matrix distances match direct `np.linalg.norm` values.
4. Use quality-near-equal images with one near copy and one distinct supported face. Confirm the latter rises in ranking with diversity weight 0.35–0.60.
5. Set `kb_gallery_diversity_weight` to 0. Verify earlier quality-only ranking is restored.
6. Mix a different-person outlier, exact duplicate, multi-face image and corrupt image. Verify none enters the provisional shortlist.
7. Verify ambiguous/insufficient consensus and incomplete reports still produce review-only output.
8. Repeat refresh, person switch, file replacement, KB membership change and shutdown checks; no stale result or child should survive.
9. Confirm no raw embeddings are in returned JSON and the KB, cache and preferences remain byte-for-byte unchanged.

## Local checks

The combined regression suite passes 67 tests and 22 malformed-input subtests. Offscreen Qt checks confirm malformed matrices fall back to quality-only suggestions without losing the workbench workflow. A native smoke test returned a finite, symmetric, path-indexed matrix without raw embeddings or source/cache writes; it used repeated copies of one usable image and does not establish independent-image recognition gains.
