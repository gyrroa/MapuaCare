from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from typing import List, Optional, Set, Tuple
from .. import models, schemas, database, auth
from ..services import embedding
import json
import re
# --- NEW: Added for 'top' endpoints ---
import numpy as np
# --- END NEW ---

# --- MODIFIED: Using your old prefix ---
router = APIRouter(prefix="/matching", tags=["matching"])
# --- END MODIFIED ---

# --- NEW: Weights from your old code ---
SIM_WEIGHT = 0.7
COV_WEIGHT = 0.3
# --- END NEW ---

# ---------- DB ----------
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Helpers (Our new, stable versions) ----------

def _get_job(db: Session, job_id: int) -> models.CompanyJob:
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.job_embedding_vector:
        raise HTTPException(400, "Job is not ready for matching (missing embedding)")
    return job

def _get_candidate(db: Session, candidate_id: int) -> models.CandidateProfile:
    cand = db.get(models.CandidateProfile, candidate_id)
    if not cand:
        raise HTTPException(404, "Candidate not found")
    if not cand.embedding_vector:
        raise HTTPException(400, "Candidate is not ready for matching (missing embedding)")
    return cand

def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(x * y for x, y in zip(v1, v2))
    mag_v1 = sum(x * x for x in v1) ** 0.5
    mag_v2 = sum(x * x for x in v2) ** 0.5
    if mag_v1 == 0 or mag_v2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot_product / (mag_v1 * mag_v2)))

# --- These are our new, correct functions that query the association tables ---
def _candidate_skill_ids(db: Session, candidate_id: int) -> list[int]:
    stmt = select(models.candidate_skills.c.skill_id).where(
        models.candidate_skills.c.candidate_id == candidate_id
    )
    return [sid for (sid,) in db.execute(stmt).all()]

def _job_skill_ids(db: Session, job_id: int) -> list[int]:
    stmt = select(models.job_skills.c.skill_id).where(
        models.job_skills.c.job_id == job_id
    )
    return [sid for (sid,) in db.execute(stmt).all()]

def _coverage_candidate_vs_job(
    db: Session, candidate_id: int, job_id: int
) -> Tuple[float, Set[int], Set[int]]:
    cand_skill_ids = set(_candidate_skill_ids(db, candidate_id))
    job_skill_ids = set(_job_skill_ids(db, job_id))

    if not job_skill_ids:
        # If job requires no skills, coverage is 0 (or 1.0, your choice)
        return (0.0, set(), set()) 

    matched_ids = cand_skill_ids.intersection(job_skill_ids)
    missing_ids = job_skill_ids.difference(cand_skill_ids)
    
    coverage = len(matched_ids) / len(job_skill_ids)
    return (coverage, matched_ids, missing_ids)


# --- (THIS IS THE FIX) ---
# --- This is our new, smart _preprocess_text function (CORRECTED) ---
def _preprocess_text(text: str) -> str:
    if not text:
        return ""
    # 1. Add space before uppercase letter (camelCase)
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    # 2. Add spaces around punctuation
    text = re.sub(r'([.,!?;:])', r' \1 ', text)
    
    # --- THIS IS THE FIX ---
    # We replace only spaces and tabs, NOT newlines (\n).
    # This preserves the line breaks from the database.
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    # --- END OF FIX ---
    
    return text
# --- END CORRECTED FUNCTION ---


# --- This is the superior sentence tokenizer from your "old" code ---
def _tokenize_sentences(text: str) -> List[str]:
    """Splits text into sentences, respecting punctuation and newlines."""
    if not text:
        return []
    
    # We split on:
    # 1. Newlines (\n+)
    # 2. Punctuation (.!?) with optional spaces around it (\s*[.!?]\s*)
    # 3. The vertical pipe (|) which this resume uses heavily
    parts = re.split(r'\n+|\s*[\.\!\?]\s*|\|', text.strip())

    clean, seen = [], set()
    for p in parts:
        s = p.strip()
        # Keep non-empty, unique sentences
        if s and s not in seen:
            clean.append(s)
            seen.add(s)
    return clean
# --- END ADDED FUNCTION ---

# --- MODIFIED: This function now uses the correct helpers ---
def _find_evidence(
    db: Session,
    text: Optional[str], 
    matched_skill_ids: Set[int]
) -> List[str]:
    """Finds sentences in text that contain any of the matched skills or their aliases."""
    if not text or not matched_skill_ids:
        return []

    # 1. Get all labels for the matched skills from the DB
    skills = db.query(models.Skill.preferred_label, models.Skill.alt_labels).filter(
        models.Skill.skill_id.in_(matched_skill_ids)
    ).all()

    # 2. Create a set of all possible names to search for
    all_labels_to_find: Set[str] = set()
    for preferred_label, alt_labels in skills:
        all_labels_to_find.add(preferred_label.lower())
        if alt_labels:
            # Split aliases, clean them, and add to the set
            aliases = alt_labels.split(';')
            for alias in aliases:
                if alias:
                    all_labels_to_find.add(alias.lower())

    # 3. Build a regex pattern for each label
    patterns = []
    for label in all_labels_to_find:
        if not label:
            continue
        
        pattern = re.escape(label)
        # Add \b (word boundary) ONLY if the label starts/ends
        # with an alphanumeric character. This correctly handles "C#" and "Python".
        prefix = r'\b' if label[0].isalnum() else r''
        suffix = r'\b' if label[-1].isalnum() else r''
        patterns.append(f"{prefix}{pattern}{suffix}")
    
    if not patterns:
        return []

    # 4. Create one giant regex: (pattern1|pattern2|pattern3)
    skill_regex = re.compile("|".join(patterns), re.IGNORECASE)
    
    # 5. Preprocess text before searching
    #    (This now correctly preserves newlines)
    processed_text = _preprocess_text(text)
    
    # 6. Split text into sentences and find matches
    #    (This now correctly splits on newlines)
    sentences = _tokenize_sentences(processed_text)
    
    evidence = []
    for s_clean in sentences: # _tokenize_sentences already stripped the text
        if s_clean and skill_regex.search(s_clean):
            evidence.append(s_clean)
            if len(evidence) >= 3: # Limit to 3 pieces of evidence
                break
    return evidence
# --- END MODIFIED FUNCTION ---

# ---------------------------
# MATCH CANDIDATE vs. JOB
# ---------------------------
@router.get(
    "/pair/{candidate_id}/{job_id}",
    response_model=schemas.MatchResponse,
    summary="Match a candidate and a job",
    description="Computes similarity, coverage, combined fit, and gives short evidence snippets.",
    responses={404: {"description": "Candidate or job not found"}},
)
def match_pair(
    candidate_id: int,
    job_id: int,
    db: Session = Depends(get_db),
):
    # 1. Get both profiles
    cand = _get_candidate(db, candidate_id)
    job = _get_job(db, job_id)

    # 2. Calculate similarity
    cand_vector = json.loads(cand.embedding_vector or "[]")
    job_vector = json.loads(job.job_embedding_vector or "[]")
    sim_score = _cosine_similarity(cand_vector, job_vector)

    # 3. Calculate skill coverage
    cov, matched, missing = _coverage_candidate_vs_job(db, cand.candidate_id, job.job_id)

    # 4. Calculate final fit score (using 70/30 split)
    fit_score = (sim_score * SIM_WEIGHT) + (cov * COV_WEIGHT)

    # 5. Get skill names for the response
    def get_names(ids):
        if not ids: return []
        return [name for (name,) in db.query(models.Skill.preferred_label)
                .filter(models.Skill.skill_id.in_(ids)).all()]
    
    matched_names = get_names(matched)
    missing_names = get_names(missing)

    # --- 6. Build rich summary text (from old code) ---
    # This part now works correctly because _find_evidence was fixed
    job_hits = _find_evidence(db, job.job_description, matched)
    resume_hits = _find_evidence(db, cand.resume_text, matched)

    cov_pct = f"{round(cov*100)}%" if matched or missing else "N/A"
    sim_pct = f"{round(sim_score*100)}%"
    fit_pct = f"{round(fit_score*100)}%"

    summary_lines = [
        f"{cand.full_name} overall match: {fit_pct} (similarity {sim_pct}, skill coverage {cov_pct}).",
    ]
    if matched_names:
        summary_lines.append(f"Matched skills: {', '.join(matched_names)}.")
    if missing_names:
        summary_lines.append(f"Missing skills: {', '.join(missing_names)}.")
    if job_hits:
        summary_lines.append("Job mentions: " + " | ".join(job_hits))
    if resume_hits:
        summary_lines.append("Resume evidence: " + " | ".join(resume_hits))
    summary_text = " ".join(summary_lines)
    # --- End of summary text ---

    # 7. Return the single MatchResponse
    return schemas.MatchResponse(
        job_id=job.job_id,
        fit_score=fit_score,
        summary_text=summary_text, 
        sim_score=sim_score,
        coverage_score=cov,
        matched_skills=matched_names,
        missing_skills=missing_names,
        evidence=schemas.Evidence(
            job_mentions=job_hits,
            resume_mentions=resume_hits
        )
    )

# ---------------------------
# MATCH CANDIDATE (vs. All Jobs)
# ---------------------------
@router.get(
    "/top_jobs/{candidate_id}",
    response_model=List[schemas.JobRecommendation],
    summary="Top job recommendations for a candidate",
    description="Returns top-N jobs ranked by a weighted fit of semantic similarity and skill coverage.",
    responses={404: {"description": "Candidate not found"}},
)
def top_jobs_for_candidate(
    candidate_id: int,
    n: int = Query(10, ge=1, le=100, description="How many recommendations to return"),
    db: Session = Depends(get_db),
    # current: models.User = Depends(auth.get_current_user), 
):
    # 1. Get the candidate and their vector
    cand = _get_candidate(db, candidate_id)
    cand_vec = np.asarray(json.loads(cand.embedding_vector or "[]"), dtype=np.float32)

    # 2. Get all jobs that are ready for matching
    jobs = db.query(models.CompanyJob).filter(
        models.CompanyJob.job_embedding_vector.is_not(None)
    ).all()
    if not jobs:
        return []

    # 3. Load all job vectors into a NumPy matrix
    job_ids = [j.job_id for j in jobs]
    job_vecs = [json.loads(j.job_embedding_vector or "[]") for j in jobs]
    job_mat = np.asarray(job_vecs, dtype=np.float32)

    # 4. Get top-k similarities using embedding service
    try:
        sims = [_cosine_similarity(cand_vec, job_vec) for job_vec in job_mat]
    except Exception as e:
        raise HTTPException(500, f"Embedding similarity error: {e}")

    # 5. Re-score all with skill coverage
    recs = []
    for i, job in enumerate(jobs):
        sim = float(sims[i])
        cov, _, _ = _coverage_candidate_vs_job(db, candidate_id, job.job_id)
        fit = (SIM_WEIGHT * sim) + (COV_WEIGHT * cov)
        recs.append((fit, sim, cov, job))

    # 6. Sort by final fit score
    recs.sort(key=lambda t: t[0], reverse=True)
    return [
        schemas.JobRecommendation(
            job_id=j.job_id,
            job_title=j.job_title,
            job_category=j.job_category,
            fit_score=float(fit),
            sim_score=float(sim),
            coverage_score=float(cov),
        )
        for fit, sim, cov, j in recs[:n]
    ]

# ---------------------------
# MATCH JOB (vs. All Candidates)
# ---------------------------
@router.get(
    "/top_candidates/{job_id}",
    response_model=List[schemas.CandidateRecommendation],
    summary="Top candidate recommendations for a job",
    description="Returns top-N candidates ranked by a weighted fit of semantic similarity and skill coverage.",
    responses={4404: {"description": "Job not found"}},
)
def top_candidates_for_job(
    job_id: int,
    n: int = Query(10, ge=1, le=100, description="How many recommendations to return"),
    db: Session = Depends(get_db),
    # current: models.User = Depends(auth.get_current_user), 
):
    job = _get_job(db, job_id)
    # if current.role == 'company' and current.user_id != job.company_id:
    #     raise HTTPException(403, "You can only match your own company's jobs")
        
    # 1. Get the job and its vector
    job_vec = np.asarray(json.loads(job.job_embedding_vector or "[]"), dtype=np.float32)

    # 2. Get all candidates that are ready for matching
    cands = db.query(models.CandidateProfile).filter(
        models.CandidateProfile.embedding_vector.is_not(None)
    ).all()
    if not cands:
        return []

    # 3. Load all candidate vectors into a NumPy matrix
    cand_ids = [c.candidate_id for c in cands]
    cand_vecs = [json.loads(c.embedding_vector or "[]") for c in cands]
    cand_mat = np.asarray(cand_vecs, dtype=np.float32)

    # 4. Get top-k similarities
    try:
        sims = [_cosine_similarity(job_vec, cand_vec) for cand_vec in cand_mat]
    except Exception as e:
        raise HTTPException(500, f"Embedding similarity error: {e}")

    # 5. Re-score all with skill coverage
    recs = []
    for i, c in enumerate(cands):
        sim = float(sims[i])
        cov, _, _ = _coverage_candidate_vs_job(db, c.candidate_id, job.job_id)
        fit = (SIM_WEIGHT * sim) + (COV_WEIGHT * cov)
        recs.append((fit, sim, cov, c))

    # 6. Sort by final fit score
    recs.sort(key=lambda t: t[0], reverse=True)
    return [
        schemas.CandidateRecommendation(
            candidate_id=c.candidate_id,
            full_name=c.full_name,
            fit_score=float(fit),
            sim_score=float(sim),
            coverage_score=float(cov),
        )
        for fit, sim, cov, c in recs[:n]
    ]