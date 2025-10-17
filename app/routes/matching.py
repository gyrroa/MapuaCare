from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Tuple
import json
import re
import numpy as np

from .. import models, schemas, database
from ..services import embedding
from sqlalchemy import select

router = APIRouter(prefix="/match", tags=["matching"])

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _get_cand_vec(c: models.CandidateProfile):
    if c.embedding_vector:
        try:
            return json.loads(c.embedding_vector)
        except Exception:
            pass
    return embedding.get_embedding(c.resume_text or "")

def _get_job_vec(j: models.CompanyJob):
    if getattr(j, "job_embedding_vector", None):
        try:
            return json.loads(j.job_embedding_vector)
        except Exception:
            pass
    text = f"{j.job_title}\nCategory: {j.job_category or ''}\n{j.job_description or ''}".lower()
    return embedding.get_embedding(text)

def _tokenize_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r'(?<=[\.\!\?])\s+|\n+', text.strip())
    clean, seen = [], set()
    for p in parts:
        s = p.strip()
        if s and s not in seen:
            clean.append(s); seen.add(s)
    return clean

def _skill_names_for_ids(db: Session, ids):
    if not ids:
        return []
    return db.execute(
        select(models.Skill.preferred_label).where(models.Skill.skill_id.in_(list(ids)))
    ).scalars().all()

def _candidate_skill_ids(db: Session, candidate_id: int) -> List[int]:
    return [sid for (sid,) in db.query(models.CandidateSkill.skill_id)
            .filter(models.CandidateSkill.candidate_id == candidate_id).all()]

def _job_skill_ids(db: Session, job_id: int) -> List[int]:
    return [sid for (sid,) in db.query(models.JobSkill.skill_id)
            .filter(models.JobSkill.job_id == job_id).all()]

def _find_evidence(sentences: List[str], skill_names: List[str], max_hits: int = 3) -> List[str]:
    hits = []
    if not sentences or not skill_names:
        return hits
    patterns = [re.compile(rf'\b{re.escape(name)}\b', re.I) for name in skill_names]
    for s in sentences:
        if any(p.search(s) for p in patterns):
            hits.append(s.strip())
            if len(hits) >= max_hits:
                break
    return hits

def _coverage_candidate_vs_job(db: Session, candidate_id: int, job_id: int) -> Tuple[float, List[int], List[int]]:
    job_skill_ids = set(_job_skill_ids(db, job_id))
    cand_skill_ids = set(_candidate_skill_ids(db, candidate_id))
    if not job_skill_ids or not cand_skill_ids:
        return 0.0, [], list(job_skill_ids)  # default -> 0.0
    matched = sorted(job_skill_ids & cand_skill_ids)
    missing = sorted(job_skill_ids - cand_skill_ids)
    coverage = len(matched) / max(1, len(job_skill_ids))
    return coverage, matched, missing

def _coverage_job_vs_candidate(db: Session, job_id: int, candidate_id: int) -> float:
    job_skill_ids = set(_job_skill_ids(db, job_id))
    cand_skill_ids = set(_candidate_skill_ids(db, candidate_id))
    if not job_skill_ids or not cand_skill_ids:
        return 0.0  # default -> 0.0
    return len(job_skill_ids & cand_skill_ids) / max(1, len(cand_skill_ids))

SIM_WEIGHT = 0.7
COV_WEIGHT = 0.3

@router.get("/pair/{candidate_id}/{job_id}", response_model=schemas.MatchResponse)
def match_candidate(candidate_id: int, job_id: int, db: Session = Depends(get_db)):
    candidate = db.get(models.CandidateProfile, candidate_id)
    job = db.get(models.CompanyJob, job_id)
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Not found")

    cand_vec = _get_cand_vec(candidate)
    job_vec = _get_job_vec(job)
    sim = embedding.cosine_similarity(cand_vec, job_vec)
    cov, matched_ids, missing_ids = _coverage_candidate_vs_job(db, candidate_id, job_id)
    fit = SIM_WEIGHT * sim + COV_WEIGHT * cov

    matched_names = _skill_names_for_ids(db, matched_ids)
    missing_names = _skill_names_for_ids(db, missing_ids)

    job_sents = _tokenize_sentences(job.job_description or "")
    resume_sents = _tokenize_sentences(candidate.resume_text or "")
    job_hits = _find_evidence(job_sents, matched_names, max_hits=3)
    resume_hits = _find_evidence(resume_sents, matched_names, max_hits=3)

    cov_pct = f"{round(cov*100)}%" if matched_ids or missing_ids else "N/A"
    sim_pct = f"{round(sim*100)}%"
    fit_pct = f"{round(fit*100)}%"

    summary_lines = [
        f"{candidate.full_name} overall match: {fit_pct} (similarity {sim_pct}, skill coverage {cov_pct}).",
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

    return schemas.MatchResponse(
        job_id=job.job_id,
        fit_score=fit,
        summary_text=summary_text,
        sim_score=sim,
        coverage_score=cov,
        matched_skills=matched_names,
        missing_skills=missing_names,
        evidence=schemas.Evidence(job_mentions=job_hits, resume_mentions=resume_hits),
    )

@router.get("/top_jobs/{candidate_id}", response_model=List[schemas.JobRecommendation])
def top_jobs_for_candidate(
    candidate_id: int,
    n: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    candidate = db.get(models.CandidateProfile, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")

    cand_vec = np.asarray(_get_cand_vec(candidate), dtype=np.float32)
    jobs = db.query(models.CompanyJob).all()
    if not jobs:
        return []

    job_vecs = [np.asarray(_get_job_vec(j), dtype=np.float32) for j in jobs]
    job_mat = np.vstack(job_vecs)
    idx, sims = embedding.cosine_topk(cand_vec, job_mat, k=min(n*5, len(jobs)))

    recs = []
    for r, i in enumerate(idx[:n*5]):
        job = jobs[i]
        sim = float(sims[r])
        cov, _, _ = _coverage_candidate_vs_job(db, candidate_id, job.job_id)
        fit = SIM_WEIGHT * sim + COV_WEIGHT * cov
        recs.append((fit, sim, cov, job))

    recs.sort(key=lambda t: t[0], reverse=True)
    return [
        schemas.JobRecommendation(
            job_id=j.job_id,
            job_title=j.job_title,
            job_category=j.job_category,
            location=j.location,
            fit_score=float(fit),
            sim_score=float(sim),
            coverage_score=float(cov),
        )
        for fit, sim, cov, j in recs[:n]
    ]

@router.get("/top_candidates/{job_id}", response_model=List[schemas.CandidateRecommendation])
def top_candidates_for_job(
    job_id: int,
    n: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    job_vec = np.asarray(_get_job_vec(job), dtype=np.float32)
    cands = db.query(models.CandidateProfile).all()
    if not cands:
        return []

    cand_vecs = [np.asarray(_get_cand_vec(c), dtype=np.float32) for c in cands]
    cand_mat = np.vstack(cand_vecs)
    idx, sims = embedding.cosine_topk(job_vec, cand_mat, k=min(n*5, len(cands)))

    recs = []
    for r, i in enumerate(idx[:n*5]):
        c = cands[i]
        sim = float(sims[r])
        cov = _coverage_job_vs_candidate(db, job_id, c.candidate_id)
        fit = SIM_WEIGHT * sim + COV_WEIGHT * cov
        recs.append((fit, sim, cov, c))

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
