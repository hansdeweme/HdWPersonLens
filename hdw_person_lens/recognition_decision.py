# recognition_decision.py
# Knowledge Base  Decision Engine for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Mapping

#---------------------------------------
# To be used by recognize_image
#---------------------------------------

@dataclass(frozen=True)
class IdentityCandidate:
    name: str | None
    score: float | None
    second_name: str | None = None
    second_score: float | None = None
    margin: float | None = None

    @property
    def available(self) -> bool:
        return (bool(self.name) and self.score is not None and math.isfinite(self.score))

@dataclass(frozen=True)
class RecognitionDecision:
    final_name: str
    reason: str
    accepted: bool
    modality: str

def _rank_face_identities(names, distances, *, topk: int,) -> list[tuple[str, float]]:
    """
    Keep the minimum face distance for each identity.
    Lower is better.
    """
    best_by_name: dict[str, float] = {}
    for name, raw_score in zip(names, distances):
        score = float(raw_score)
        current = best_by_name.get(name)
        if current is None or score < current:
            best_by_name[name] = score
    return sorted(best_by_name.items(), key=lambda item: item[1],)[:topk]

def _rank_body_identities(names, similarities, *, topk: int,) -> list[tuple[str, float]]:
    """
    Keep the maximum body similarity for each identity.
    Higher is better.
    """
    best_by_name: dict[str, float] = {}
    for name, raw_score in zip(names, similarities):
        score = float(raw_score)
        current = best_by_name.get(name)
        if current is None or score > current:
            best_by_name[name] = score
    return sorted(best_by_name.items(),key=lambda item: item[1], reverse=True,)[:topk]

def _face_candidate(rows: list[tuple[str, float]],
) -> IdentityCandidate:
    if not rows:
        return IdentityCandidate(None, None)
    best_name, best_score = rows[0]
    if len(rows) < 2:
        return IdentityCandidate(name=best_name, score=best_score,)
    second_name, second_score = rows[1]
    return IdentityCandidate(name=best_name, score=best_score, second_name=second_name, second_score=second_score, margin=second_score - best_score,)

def _body_candidate(rows: list[tuple[str, float]],) -> IdentityCandidate:
    if not rows:
        return IdentityCandidate(None, None)
    best_name, best_score = rows[0]
    if len(rows) < 2:
        return IdentityCandidate(name=best_name, score=best_score,)
    second_name, second_score = rows[1]
    return IdentityCandidate(name=best_name, score=best_score, second_name=second_name, second_score=second_score, margin=best_score - second_score,)

def _candidate_rank_score(face_rank: int | None, body_rank: int | None,) -> float:
    """
    Return deterministic rank support for contender ordering.
    This is not a confidence score. It only rewards identities that occur
    high in one or both modality rankings, with face rank weighted more
    heavily than body rank.
    """
    def support(rank: int | None, weight: float) -> float:
        if rank is None:
            return 0.0
        try:
            value = int(rank)
        except (TypeError, ValueError):
            return 0.0
        if value <= 0:
            return 0.0
        return weight / value
    return support(face_rank, 2.0) + support(body_rank, 1.0)

def build_identity_contenders(face_rows: list[tuple[str, float]], body_rows: list[tuple[str, float]], settings: Mapping[str, Any], *, topk: int = 3,) -> list[dict[str, Any]]:
    """
    Merge face and body identity rankings into one deterministic contender list.
    Face distance and body similarity remain separate measurements. They are
    never averaged or transformed into a synthetic confidence value.
    Ordering:
      1. plausible in both face and body;
      2. plausible face candidate;
      3. plausible body candidate;
      4. present in both rankings but weak in both;
      5. remaining nearest candidates.
    Within a tier, ``rank_score`` is used only as an ordering aid.
    """
    try:
        limit = int(topk)
    except (TypeError, ValueError) as exc:
        raise ValueError("topk must be an integer.") from exc
    if limit <= 0:
        return []

    def clean_name(value: object) -> str:
        return " ".join(str(value or "").split())

    def finite_float(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def setting_float(key: str, default: float) -> float:
        value = finite_float(settings.get(key, default))
        return default if value is None else value

    face_threshold = setting_float("face_threshold_supportable", 0.42)
    body_threshold = setting_float("body_threshold_agreement", 0.84)
    # Normalized identity key -> merged evidence.
    merged: dict[str, dict[str, Any]] = {}

    def ensure_candidate(name: str) -> dict[str, Any]:
        key = name.casefold()
        candidate = merged.get(key)
        if candidate is None:
            candidate = {
                "name": name,
                "face_distance": None,
                "face_rank": None,
                "body_similarity": None,
                "body_rank": None,
            }
            merged[key] = candidate
        return candidate

    # The input rows are expected to be identity-level rankings. Duplicate
    # rows are still handled defensively by retaining the best score.
    for rank, row in enumerate(face_rows or (), start=1):
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            continue
        name = clean_name(row[0])
        distance = finite_float(row[1])
        if not name or distance is None:
            continue
        candidate = ensure_candidate(name)
        current = candidate["face_distance"]
        if current is None or distance < current:
            candidate["face_distance"] = distance
            candidate["face_rank"] = rank

    for rank, row in enumerate(body_rows or (), start=1):
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            continue
        name = clean_name(row[0])
        similarity = finite_float(row[1])
        if not name or similarity is None:
            continue
        candidate = ensure_candidate(name)
        current = candidate["body_similarity"]
        if current is None or similarity > current:
            candidate["body_similarity"] = similarity
            candidate["body_rank"] = rank

    contenders: list[dict[str, Any]] = []
    for candidate in merged.values():
        face_distance = candidate["face_distance"]
        body_similarity = candidate["body_similarity"]
        face_rank = candidate["face_rank"]
        body_rank = candidate["body_rank"]
        face_present = face_distance is not None
        body_present = body_similarity is not None
        face_plausible = (face_present and float(face_distance) <= face_threshold)
        body_plausible = (body_present and float(body_similarity) >= body_threshold)
        if face_plausible and body_plausible:
            tier_order = 1
            tier = "face_and_body_plausible"
        elif face_plausible:
            tier_order = 2
            tier = "face_plausible"
        elif body_plausible:
            tier_order = 3
            tier = "body_plausible"
        elif face_present and body_present:
            tier_order = 4
            tier = "cross_modal_weak"
        else:
            tier_order = 5
            tier = "nearest_only"
        if face_present and body_present:
            evidence = "face_and_body"
        elif face_present:
            evidence = "face"
        else:
            evidence = "body"
        contenders.append(
            {
                "name": candidate["name"],
                "face_distance": face_distance,
                "face_rank": face_rank,
                "body_similarity": body_similarity,
                "body_rank": body_rank,
                "face_plausible": bool(face_plausible),
                "body_plausible": bool(body_plausible),
                "evidence": evidence,
                "tier": tier,
                "rank_score": _candidate_rank_score(face_rank, body_rank),
                "_tier_order": tier_order,
            }
        )

    infinity = float("inf")
    contenders.sort(key=lambda contender: (
            contender["_tier_order"],
            -contender["rank_score"],
            contender["face_rank"] if contender["face_rank"] is not None else infinity,
            contender["body_rank"] if contender["body_rank"] is not None else infinity,
            contender["name"].casefold(),
            contender["name"],
        )
    )

    result: list[dict[str, Any]] = []
    for rank, contender in enumerate(contenders[:limit], start=1):
        public_contender = {key: value for key, value in contender.items() if key != "_tier_order"}
        public_contender["rank"] = rank
        result.append(public_contender)
    return result

#-----------------------------------------------
# Decide Identity
#-----------------------------------------------
def decide_identity(face: IdentityCandidate, body: IdentityCandidate, settings: Mapping[str, Any],
                    ) -> tuple[dict[str, float], RecognitionDecision]:
    face_strong =               float(settings.get("face_threshold_strong", 0.35))
    face_extended =             float(settings.get("face_threshold_extended", 0.385))
    face_supportable =          float(settings.get("face_threshold_supportable", 0.42))
    body_support =              float(settings.get("body_threshold_support", 0.85))
    body_alone =                float(settings.get("body_threshold_alone", 0.87))
    face_margin_min =           float(settings.get("face_margin_min", 0.025))
    face_conflict_margin_min =  float(settings.get("face_conflict_margin_min", 0.050))
    body_margin_min =           float(settings.get("body_margin_min", 0.025))
    face_agreement =            float(settings.get("face_threshold_agreement", 0.50,))
    body_agreement =            float(settings.get("body_threshold_agreement",0.84,))
    face_agreement_margin_min = float(settings.get("face_agreement_margin_min", 0.015,))
    body_agreement_margin_min = float(settings.get("body_agreement_margin_min", 0.010,))    
    body_conflict_margin_min =  float(settings.get("body_conflict_margin_min", 0.025,))
    thresholds = {
                    "face_strong": face_strong,
                    "face_extended": face_extended,
                    "face_supportable": face_supportable,
                    "body_support": body_support,
                    "body_alone": body_alone,
                    "face_margin_min": face_margin_min,
                    "face_conflict_margin_min": face_conflict_margin_min,
                    "body_margin_min": body_margin_min,
                    "face_agreement": face_agreement,
                    "body_agreement": body_agreement,
                    "body_conflict_margin_min": body_conflict_margin_min,
                    "face_agreement_margin_min": face_agreement_margin_min,
                    "body_agreement_margin_min": body_agreement_margin_min,                    
     } 
    face_available = face.available # object has .name and .score
    body_available = body.available # object has .name and .score
    # ---------------------------------------------------------
    # Shared evidence states
    # ---------------------------------------------------------
    same_identity =  (face_available and body_available and face.name == body.name)
    body_conflicts = (face_available and body_available and face.name != body.name 
                      and body.score is not None and body.score >= body_support)
    # A conflicting body result is "clear" only when it also has meaningful 
    # separation from its runner-up.
    clear_body_conflict = (body_conflicts and body.score is not None and body.score >= body_alone 
                           and body.margin is not None and body.margin >= body_conflict_margin_min)
    face_agreement_supported = (face_available and face.score is not None and face.score <= face_agreement 
                                and face.margin is not None and face.margin >= face_agreement_margin_min)
    body_agreement_supported = (body_available and body.score is not None and body.score >= body_agreement 
                                and body.margin is not None and body.margin >= body_agreement_margin_min)       
    # 1. A genuinely strong face is sufficient. 
    # A clearly separated contradictory body result prevents immediate acceptance. 
    if (face_available and face.score is not None and face.score <= face_strong and face.margin is not None):
        if clear_body_conflict:
            return thresholds, RecognitionDecision(final_name="Unknown", 
                                                   reason="strong_face_clear_body_conflict", accepted=False, modality="none",)
        required_margin = (face_conflict_margin_min if body_conflicts else face_margin_min)
        if face.margin >= required_margin:
            return thresholds, RecognitionDecision(final_name=face.name, 
                                                reason=("strong_face_overrides_weak_body" if body_conflicts else "strong_face"),
                                                accepted=True, modality="face",)
    # 2. Face and body independently agree. Require actual runner-up separation for both modalities.
    if (same_identity and face.score is not None and face.score <= face_supportable 
        and body.score is not None and body.score >= body_support and face.margin is not None 
        and face.margin >= face_agreement_margin_min and body.margin is not None and body.margin >= body_agreement_margin_min):
        return thresholds, RecognitionDecision(final_name=face.name, reason="face_body_agreement", accepted=True, modality="fused",)
    # Face & Body agree both with clear margin but might fail a strict threshold
    decisive_body_agreement = float(settings.get("body_threshold_decisive_agreement", 0.75,))
    decisive_face_margin = float(settings.get("face_decisive_agreement_margin_min", 0.050, ))
    decisive_body_margin = float(settings.get("body_decisive_agreement_margin_min", 0.050,))
    if (same_identity and face.score is not None and face.score <= face_supportable and body.score is not None 
        and body.score >= decisive_body_agreement and face.margin is not None and face.margin >= decisive_face_margin 
        and body.margin is not None and body.margin >= decisive_body_margin):
        return thresholds, RecognitionDecision(final_name=face.name, reason="decisive_subthreshold_agreement", accepted=True, modality="fused",)    
    # 3. Weaker face/body agreement rescue
    if (same_identity and face_agreement_supported and body_agreement_supported):
        return thresholds, RecognitionDecision(final_name=face.name, reason="weak_face_body_agreement", accepted=True, modality="fused",)
    # 4. Extended face range 
    if (face_available and face.score is not None and face.score <= face_extended and face.margin is not None):
        # Do not let a moderate face override a body result that is both strong and clearly separated.
        if clear_body_conflict:
            return thresholds, RecognitionDecision(final_name="Unknown", reason="moderate_face_clear_body_conflict", accepted=False, modality="none",)
        required_margin = (face_conflict_margin_min if body_conflicts else face_margin_min)
        if face.margin >= required_margin:
            return thresholds, RecognitionDecision(final_name=face.name, reason=("moderate_face_overrides_weak_body" 
                                                    if body_conflicts else "moderate_face_clear_margin"), accepted=True, modality="face",)
    # 5. Remaining plausible face/body disagreement
    if (face_available and body_available and face.name != body.name and face.score is not None and face.score <= face_supportable 
        and body.score is not None and body.score >= body_support):
        return thresholds, RecognitionDecision(final_name="Unknown", reason=("clear_face_body_conflict" 
                                                if clear_body_conflict else "face_body_conflict"), accepted=False, modality="none",)
    # 6. Strict body-only acceptance
    face_is_not_plausible = (not face_available or face.score is None or face.score > face_supportable)
    if (face_is_not_plausible and body_available and body.score is not None and body.score >= body_alone 
        and body.margin is not None and body.margin >= body_margin_min):
        return thresholds, RecognitionDecision(final_name=body.name, reason="strong_body_only", accepted=True, modality="body",)
    # 7. Unknown
    return thresholds, RecognitionDecision(final_name="Unknown", reason="insufficient_identity_evidence", accepted=False, modality="none",)    

#-------------------------------------------
# To be used by PersonSearchers
#-------------------------------------------
@dataclass(frozen=True)
class TargetMatchDecision:
    matched: bool
    reason: str
    modality: str

def _normalize_identity(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()

def decide_target_match(target_name: str,  recognition_result: Mapping[str, Any], settings: Mapping[str, Any],) -> TargetMatchDecision:
    """
    Decide whether a recognition result sufficiently supports a
    particular requested identity.
    Strict default:
        Only accept when normal open-set recognition accepted the target.
    Optional recall rescue:
        Permit a clear face top-1 result when the normal result remained
        Unknown. Enable with person_search_allow_face_rescue=true.
    """    
    target_key = _normalize_identity(target_name)
    if not target_key:
        return TargetMatchDecision( matched=False, reason="invalid_target_name", modality="none",)
    if recognition_result.get("error"):
        return TargetMatchDecision(matched=False, reason="recognition_error", modality="none", )
    final_name = str(recognition_result.get("final_name", "Unknown", ) or "Unknown")
    diagnostics = dict(recognition_result.get("diagnostics", {},) or {})
    accepted = bool(diagnostics.get("accepted", final_name != "Unknown",))
    # Normal recognition accepted the requested person.
    if (accepted and _normalize_identity(final_name) == target_key):
        return TargetMatchDecision(matched=True, reason="accepted_target_identity", modality=str(diagnostics.get("decision", "unknown",)),)
    # Another person was explicitly accepted.
    # Do not rescue the target.
    if (accepted and _normalize_identity(final_name) not in {"", "unknown", target_key}):
        return TargetMatchDecision( matched=False, reason="different_identity_accepted", modality=str(diagnostics.get("decision", "unknown", )),)
    # Begin conservatively. This is disabled by default.
    allow_face_rescue = bool(settings.get("person_search_allow_face_rescue", False, ))
    if not allow_face_rescue:
        return TargetMatchDecision(matched=False, reason="target_not_accepted", modality="none",)
    face = dict(diagnostics.get("face", {}, ) or {})
    body = dict(diagnostics.get("body", {}, ) or {})
    face_name = face.get("name")
    face_score = face.get("score")
    face_margin = face.get("margin")
    body_name = body.get("name")
    body_score = body.get("score")
    face_extended = float(
        settings.get("person_search_face_threshold", settings.get("face_threshold_extended", 0.385, ),))
    face_margin_min = float(
        settings.get("person_search_face_margin_min", settings.get("face_margin_min", 0.025, ), ))
    conflict_margin_min = float(settings.get("person_search_face_conflict_margin_min", settings.get("face_conflict_margin_min", 0.050,), ))
    body_support = float(
        settings.get("body_threshold_support",  0.85,))
    body_conflicts = (body_name is not None and _normalize_identity(body_name) != target_key
        and body_score is not None
        and float(body_score) >= body_support
    )
    required_margin = (conflict_margin_min if body_conflicts else face_margin_min)
    # Optional rescue applies only when target is face top-1.
    if ( _normalize_identity(face_name) == target_key and face_score is not None and float(face_score) <= face_extended and face_margin is not None and float(face_margin) >= required_margin):
        return TargetMatchDecision(matched=True, reason=("target_face_rescue_over_body_conflict" if body_conflicts else "target_face_rescue"), modality="face",)
    return TargetMatchDecision(matched=False, reason="target_not_supported",  modality="none", )

