from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from typing import Optional, List
from .. import models, schemas, database, auth
from ..services import cv_parser, embedding, skill_extractor
import json
import os
import tempfile

router = APIRouter(prefix="/candidate", tags=["candidates"])

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- helpers ---
def _slug(s: str) -> str:
    return "-".join("".join(ch for ch in (s or "").lower().strip() if ch.isalnum() or ch.isspace()).split())

def _get_or_create_skill_by_name(db: Session, name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Skill name cannot be empty")
    skill = db.query(models.Skill).filter(models.Skill.preferred_label.ilike(name)).first()
    if skill:
        return skill.skill_id
    concept_uri = f"local:{_slug(name)}"
    skill = models.Skill(concept_uri=concept_uri, preferred_label=name, alt_labels=None)
    db.add(skill)
    db.flush()
    return skill.skill_id

def _link_candidate_skills_from_names(db: Session, candidate_id: int, names: Optional[List[str]]):
    if names is None:
        return
    db.query(models.CandidateSkill).filter(models.CandidateSkill.candidate_id == candidate_id).delete()
    for name in names or []:
        sid = _get_or_create_skill_by_name(db, name)
        db.add(models.CandidateSkill(candidate_id=candidate_id, skill_id=sid))

def _skill_names_for_candidate(db: Session, candidate_id: int) -> list[str]:
    rows = (
        db.query(models.Skill.preferred_label)
        .join(models.CandidateSkill, models.CandidateSkill.skill_id == models.Skill.skill_id)
        .filter(models.CandidateSkill.candidate_id == candidate_id)
        .all()
    )
    return [r[0] for r in rows]

# 1) CV Upload (extract only)
@router.post(
    "/upload_cv",
    summary="Upload CV (PDF/DOCX) and extract text + naive skills",
    description="Returns raw text and a simple skill hit list based on ESCO labels.",
)
async def upload_cv(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[-1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        if suffix == ".pdf":
            text = cv_parser.extract_text_from_pdf(tmp_path)
        elif suffix == ".docx":
            text = cv_parser.extract_text_from_docx(tmp_path)
        else:
            raise HTTPException(400, "Unsupported file type")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    skills = skill_extractor.extract_skills_from_text(text)
    return {"resume_text": text, "skills_found": skills}

# 2) Create profile — uses current.user_id
@router.post(
    "/profile",
    response_model=schemas.CandidateProfileRead,
    summary="Create your candidate profile",
    description="Uses the authenticated user's ID; do **not** send user_id.",
    responses={400: {"description": "Profile already exists"}, 404: {"description": "User not found"}},
)
def create_profile(
    profile: schemas.CandidateProfileCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    uid = current.user_id
    if not db.get(models.User, uid):
        raise HTTPException(404, "User not found")
    if db.get(models.CandidateProfile, uid):
        raise HTTPException(400, "Candidate profile already exists")

    candidate = models.CandidateProfile(
        candidate_id=uid,
        full_name=profile.full_name,
        contact_number=profile.contact_number,
        college_program=profile.college_program,
        batch_year=profile.batch_year,
        resume_text=profile.resume_text,
        embedding_vector=json.dumps(embedding.get_embedding(profile.resume_text)) if profile.resume_text else None
    )
    db.add(candidate)
    db.flush()
    if profile.skills:
        _link_candidate_skills_from_names(db, uid, profile.skills)
    db.commit()
    db.refresh(candidate)

    return schemas.CandidateProfileRead(
        candidate_id=candidate.candidate_id,
        full_name=candidate.full_name,
        contact_number=candidate.contact_number,
        college_program=candidate.college_program,
        batch_year=candidate.batch_year,
        resume_text=candidate.resume_text,
        skill_names=_skill_names_for_candidate(db, candidate.candidate_id),
    )

# 3) Get one (returns skill_names)
@router.get(
    "/profiles/{candidate_id}",
    response_model=schemas.CandidateProfileRead,
    summary="Get a candidate profile",
    description="Public read.",
    responses={404: {"description": "Candidate not found"}},
)
def get_profile(candidate_id: int, db: Session = Depends(get_db)):
    c = db.get(models.CandidateProfile, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")
    return schemas.CandidateProfileRead(
        candidate_id=c.candidate_id,
        full_name=c.full_name,
        contact_number=c.contact_number,
        college_program=c.college_program,
        batch_year=c.batch_year,
        resume_text=c.resume_text,
        skill_names=_skill_names_for_candidate(db, c.candidate_id),
    )

# 4) List with search/pagination
@router.get(
    "/profiles",
    response_model=schemas.PageCandidate,
    summary="List candidate profiles",
    description="Search in name/resume with `q`. Returns skill names for each candidate.",
)
def list_profiles(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="search in name/resume"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    stmt = select(models.CandidateProfile)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            models.CandidateProfile.full_name.ilike(like),
            models.CandidateProfile.resume_text.ilike(like)
        ))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    raw_items = db.execute(
        stmt.order_by(models.CandidateProfile.candidate_id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
    ).scalars().all()

    items = [
        schemas.CandidateProfileRead(
            candidate_id=c.candidate_id,
            full_name=c.full_name,
            contact_number=c.contact_number,
            college_program=c.college_program,
            batch_year=c.batch_year,
            resume_text=c.resume_text,
            skill_names=_skill_names_for_candidate(db, c.candidate_id),
        ) for c in raw_items
    ]

    return schemas.PageCandidate(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )

# 5) Update (auth: owner only)
@router.put(
    "/profiles/{candidate_id}",
    response_model=schemas.CandidateProfileRead,
    summary="Update your candidate profile",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Candidate not found"}},
)
def update_profile(
    candidate_id: int,
    patch: schemas.CandidateProfileUpdate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != candidate_id:
        raise HTTPException(403, "You can only update your own profile")
    c = db.get(models.CandidateProfile, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")
    changed_resume = False
    for f in ["full_name", "contact_number", "college_program", "batch_year", "resume_text"]:
        v = getattr(patch, f)
        if v is not None:
            if f == "resume_text":
                changed_resume = True
            setattr(c, f, v)
    if changed_resume:
        c.embedding_vector = json.dumps(embedding.get_embedding(c.resume_text)) if c.resume_text else None
    if patch.skills is not None:
        _link_candidate_skills_from_names(db, candidate_id, patch.skills)
    db.commit()
    db.refresh(c)
    return schemas.CandidateProfileRead(
        candidate_id=c.candidate_id,
        full_name=c.full_name,
        contact_number=c.contact_number,
        college_program=c.college_program,
        batch_year=c.batch_year,
        resume_text=c.resume_text,
        skill_names=_skill_names_for_candidate(db, c.candidate_id),
    )

# 6) Delete (auth: owner only)
@router.delete(
    "/profiles/{candidate_id}",
    status_code=204,
    summary="Delete your candidate profile",
    responses={403: {"description": "Forbidden"}, 404: {"description": "Candidate not found"}},
)
def delete_profile(
    candidate_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != candidate_id:
        raise HTTPException(403, "You can only delete your own profile")
    c = db.get(models.CandidateProfile, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")
    db.delete(c)
    db.commit()
