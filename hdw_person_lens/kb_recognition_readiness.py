"""Evidence-aware, read-only recognition readiness policy; never certifies a person's identity."""


def evaluate_readiness(*, images, faces, bodies, collection=None, identity=None, reviewed=0,
                       review_needed=0, provenance=None, provenance_busy=False):
    """Summarize current known facts without treating absent analyses as successful checks."""
    images, faces, bodies = (max(0, int(value)) for value in (images, faces, bodies))
    checks = []
    checks.append(("Encoding", f"{faces} face / {bodies} body embeddings", "ok" if faces and bodies else "warning"))
    checks.append(("KB inputs", f"{images} image(s)", "ok" if images else "warning"))

    if collection is None:
        checks.append(("Collection", "Not assessed or evidence stale", "unknown"))
        collection_flags = 0
    else:
        collection_flags = max(0, int(collection.get("duplicates", 0))) + len(collection.get("errors", []))
        if collection.get("truncated") or collection.get("analyzed") != collection.get("total"):
            checks.append(("Collection", "Incomplete assessment", "warning"))
            collection_flags += 1
        else:
            checks.append(("Collection", f"{collection_flags} duplicate/unreadable finding(s)",
                           "warning" if collection_flags else "ok"))

    identity_incomplete = False
    if identity is None:
        checks.append(("Consistency", "Not assessed or evidence stale · identity unverified", "unknown"))
        identity_flags = 0
    else:
        records = identity.get("records", [])
        identity_flags = sum(row.get("identity_finding") in ("review_outlier", "inconclusive", "unassessable")
                             or bool(row.get("error")) for row in records)
        if identity.get("status") != "consensus": identity_flags += 1
        identity_incomplete = (identity.get("truncated") is not False
                               or type(identity.get("total")) is not int or identity["total"] != images
                               or type(identity.get("analyzed")) is not int or identity["analyzed"] != images
                               or len(records) != images)
        if identity_incomplete:
            identity_flags += 1
        detail = "Incomplete assessment · rerun Identity Consistency · identity unverified" if identity_incomplete else f"{identity_flags} finding(s) to review · identity unverified"
        checks.append(("Consistency", detail,
                       "warning" if identity_flags else "ok"))

    checks.append(("Curation", f"{reviewed} reviewed · {review_needed} unresolved finding(s)",
                   "warning" if review_needed else "ok"))
    freshness_flags = 0
    provenance_checked = False
    if provenance_busy:
        checks.append(("Provenance", "Bank busy; freshness not checked", "unknown"))
    elif provenance is None:
        checks.append(("Provenance", "Source freshness not checked", "unknown"))
    elif provenance.get("status") == "legacy":
        checks.append(("Provenance", "Legacy embeddings · image mapping unavailable", "unknown"))
    elif provenance.get("status") == "recorded":
        provenance_checked = True
        counts = provenance.get("freshness", {})
        freshness_flags = sum(max(0, int(counts.get(kind, 0))) for kind in ("Changed", "Missing", "Unreadable"))
        checks.append(("Provenance", f"{freshness_flags} changed/missing/unreadable source(s)",
                       "warning" if freshness_flags else "ok"))
    else:
        checks.append(("Provenance", "Unavailable · verify stored metadata", "unknown"))

    if not images:
        status, action = "No KB references", "Add KB images, then encode recognition references"
    elif not faces and not bodies:
        status, action = "Not encoded", "Build and encode a reviewed reference shortlist"
    elif not faces or not bodies:
        status, action = "Partial encoding", "Inspect missing face/body coverage before re-encoding"
    elif freshness_flags:
        status, action = "Sources need attention", "Review changed or missing references and rebuild encoding"
    elif collection is None:
        status, action = "Assessment needed", "Run KB Collection assessment"
    elif identity is None:
        status, action = "Assessment needed", "Check Identity Consistency"
    elif identity_incomplete:
        status, action = "Assessment needed", "Run a complete Identity Consistency assessment"
    elif collection_flags or identity_flags or review_needed:
        status, action = "Review needed", "Review flagged KB images and curate references"
    elif not provenance_checked:
        status = "Assessment needed"
        action = ("Wait for the encoding operation, then refresh KB status" if provenance_busy else
                  "Build and encode reviewed references to establish source provenance" if provenance and provenance.get("status") == "legacy" else
                  "Refresh KB status to verify saved encoding provenance")
    else:
        status, action = "Technically prepared", "Recognition inputs available · identity remains unverified"
    return {"status": status, "next_action": action, "checks": tuple(checks), "identity_verified": False}
