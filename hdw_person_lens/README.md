# PersonLens v1.9.9 ? KB-Only Image Management & Re-encoding

This cumulative integration package enables native Rename, Remove, Edit Images and conventional Re-encode for recognition-only profiles without creating Persons DB records. Empty KB folders permit image additions; re-encoding requires current KB images. Profile editing still requires a real DB record.

## Apply safely

These patches target the current checkout with v1.9.8 application patches still unapplied. From the repository root, check the complete set before applying:

```powershell
git apply --check hdw_person_lens/policy.patch hdw_person_lens/rename.patch hdw_person_lens/remove.patch hdw_person_lens/images.patch hdw_person_lens/dispatch.patch hdw_person_lens/reencode_panel.patch hdw_person_lens/workbench_guidance.patch
```

Apply the same set using `git apply` after checks pass. Do not also apply the older `workbench.patch`: `workbench_guidance.patch` includes its signal changes. If v1.9.8 is already applied, these cumulative patches require manual merging; do not overwrite or reset application sources.

`dispatch.patch` retains the v1.9.8 Rename/Remove dispatch and private confirmation-evidence helper. Rename/Remove still prohibit external photo-folder operations without a DB record. External photos remain preserved by default.

## Image-update safeguards

The editor captures one KB image list, validates it against the displayed membership, and derives confirmation evidence from that same list. It rechecks membership and source revisions after confirmation. The image worker repeats these checks under the service operation lock immediately before calling the existing transactional image-update service.

Source revisions use paths, sizes and modification times. They are not SHA-256 content verification and cannot detect deliberate edits preserving those values. The service lock coordinates application transactions; it does not prevent external filesystem writes.

The conventional re-encoding handler retains confirmed-snapshot forwarding. No re-encoding worker or starter replacement is included. Controlled-reference encoding keeps its separate confirmation and freshness checks.

## Verification

Run `tests/test_kb_only_images_encoding.py` after integration. These eight focused policy/structural checks replace the older KB-only policy expectations that Edit Images and Re-encode remain disabled. Native Windows transaction and lifecycle behavior still requires acceptance testing.

On a disposable KB copy, verify empty-folder additions, KB-only image changes and re-encoding, rejection of changes during confirmation or while queued, cancellation, transaction rollback, overlapping operation progress, and shutdown cleanup. Confirm DB-backed behavior and controlled-reference encoding remain unchanged.

Legacy commands remain available. This package is not a full management-parity sign-off.
