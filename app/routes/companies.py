from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_
from typing import Optional
from .. import models, schemas, database, auth
from ..services import embedding
import json
import os
import uuid

router = APIRouter(prefix="/company", tags=["companies"])

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _compose_job_text(db: Session, job: models.CompanyJob) -> str:
    skill_names = [
        s.preferred_label for s in db.query(models.Skill.preferred_label)
        .join(models.JobSkill, models.JobSkill.skill_id == models.Skill.skill_id)
        .filter(models.JobSkill.job_id == job.job_id)
        .limit(5).all()
    ]
    skill_names = [sn[0] if isinstance(sn, tuple) else sn for sn in skill_names]
    parts = [
        (job.job_title or "").strip().lower(),
        (f"category: {job.job_category}" if job.job_category else "").lower(),
        (f"skills: {', '.join(skill_names)}" if skill_names else ""),
        (job.job_description or "").strip().lower()
    ]
    return "\n".join([p for p in parts if p])

def _save_photo(user_id: int, photo: UploadFile) -> str:
    ext = os.path.splitext(photo.filename)[-1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        raise HTTPException(400, "Unsupported image type")
    upload_root = os.path.join(os.getcwd(), "uploads", "company_photos")
    os.makedirs(upload_root, exist_ok=True)
    fname = f"company_{user_id}_{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(upload_root, fname)
    with open(fpath, "wb") as f:
        f.write(photo.file.read())
    return f"/static/company_photos/{fname}"

def _delete_photo_url(photo_url: Optional[str]):
    if not photo_url:
        return
    if photo_url.startswith("/static/"):
        rel = photo_url.replace("/static/", "", 1)
        fpath = os.path.join(os.getcwd(), "uploads", rel)
        try:
            if os.path.isfile(fpath):
                os.remove(fpath)
        except Exception:
            pass

# ---------------------------
# CREATE COMPANY PROFILE (optional photo in same request) — auth required
# ---------------------------
@router.post("/profile", response_model=schemas.CompanyProfileRead)
async def create_company_profile(
    user_id: int = Form(..., description="user_id of the company"),
    company_name: str = Form(...),
    photo: Optional[UploadFile] = File(None, description="optional company photo/logo"),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != user_id:
        raise HTTPException(403, "You can only create your own company profile")
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.role and user.role != "company":
        raise HTTPException(400, "User is not a company")
    if db.get(models.CompanyProfile, user_id):
        raise HTTPException(400, "Company profile already exists")

    photo_url = _save_photo(user_id, photo) if photo else None
    prof = models.CompanyProfile(
        company_id=user_id,
        company_name=company_name,
        photo_url=photo_url,
    )
    db.add(prof)
    db.commit()
    db.refresh(prof)
    return prof

# ---------------------------
# READ ONE (public)
# ---------------------------
@router.get("/profiles/{company_id}", response_model=schemas.CompanyProfileRead)
def get_company_profile(company_id: int, db: Session = Depends(get_db)):
    prof = db.get(models.CompanyProfile, company_id)
    if not prof:
        raise HTTPException(404, "Company profile not found")
    return prof

# ---------------------------
# UPDATE COMPANY PROFILE (optional new photo / remove existing) — auth required
# ---------------------------
@router.put("/profiles/{company_id}", response_model=schemas.CompanyProfileRead)
async def update_company_profile(
    company_id: int,
    company_name: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None, description="optional new photo"),
    remove_photo: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != company_id:
        raise HTTPException(403, "You can only update your own company profile")
    prof = db.get(models.CompanyProfile, company_id)
    if not prof:
        raise HTTPException(404, "Company profile not found")

    if company_name is not None:
        prof.company_name = company_name

    new_photo_url = None
    if photo:
        # save new, then delete old (to avoid data loss if save fails)
        new_photo_url = _save_photo(company_id, photo)
        _delete_photo_url(prof.photo_url)
        prof.photo_url = new_photo_url
    elif remove_photo:
        _delete_photo_url(prof.photo_url)
        prof.photo_url = None

    db.commit()
    db.refresh(prof)
    return prof

# ---------------------------
# DELETE COMPANY PROFILE — auth required (cleans up stored photo)
# ---------------------------
@router.delete("/profiles/{company_id}", status_code=204)
def delete_company_profile(
    company_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    if current.user_id != company_id:
        raise HTTPException(403, "You can only delete your own company profile")
    prof = db.get(models.CompanyProfile, company_id)
    if not prof:
        raise HTTPException(404, "Company profile not found")
    _delete_photo_url(prof.photo_url)
    db.delete(prof)
    db.commit()

# ---------------------------
# JOBS (auth checks on mutations)
# ---------------------------
@router.post("/jobs", response_model=schemas.CompanyJobRead)
def create_job(
    job: schemas.CompanyJobCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
    company_id: Optional[int] = Query(None, description="Optional company/user id; defaults to current user"),
):
    cid = company_id if company_id is not None else current.user_id
    if current.user_id != cid:
        raise HTTPException(403, "You can only create jobs for your own company")
    company_job = models.CompanyJob(
        company_id=cid,
        job_title=job.job_title,
        job_description=job.job_description,
        location=job.location,
        job_category=job.job_category,
    )
    db.add(company_job)
    db.flush()

    if job.skills:
        valid_ids = [sid for (sid,) in db.execute(
            select(models.Skill.skill_id).where(models.Skill.skill_id.in_(job.skills))
        ).all()]
        for sid in valid_ids:
            db.add(models.JobSkill(job_id=company_job.job_id, skill_id=sid, required=True))

    composed = _compose_job_text(db, company_job)
    company_job.job_embedding_vector = json.dumps(embedding.get_embedding(composed))

    db.commit()
    db.refresh(company_job)
    return company_job

@router.get("/jobs/{job_id}", response_model=schemas.CompanyJobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

@router.get("/jobs", response_model=schemas.PageJob)
def list_jobs(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="search in title/description/category"),
    location: Optional[str] = None,
    category: Optional[str] = None,
    company_id: Optional[int] = Query(None, description="filter by company_id"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    stmt = select(models.CompanyJob)

    if location:
        stmt = stmt.where(models.CompanyJob.location == location)
    if category:
        stmt = stmt.where(models.CompanyJob.job_category == category)
    if company_id is not None:
        stmt = stmt.where(models.CompanyJob.company_id == company_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            models.CompanyJob.job_title.ilike(like),
            models.CompanyJob.job_description.ilike(like),
            models.CompanyJob.job_category.ilike(like),
        ))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.execute(
        stmt.order_by(models.CompanyJob.job_id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
    ).scalars().all()

    return schemas.PageJob(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )

@router.put("/jobs/{job_id}", response_model=schemas.CompanyJobRead)
def update_job(
    job_id: int,
    patch: schemas.CompanyJobUpdate,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.company_id != current.user_id:
        raise HTTPException(403, "You can only update your own company's job")

    changed = False
    for f in ["job_title", "job_description", "location", "job_category"]:
        val = getattr(patch, f)
        if val is not None:
            setattr(job, f, val)
            if f in ("job_title", "job_description", "job_category"):
                changed = True

    if patch.skills is not None:
        db.query(models.JobSkill).filter(models.JobSkill.job_id == job_id).delete()
        if patch.skills:
            valid_ids = [sid for (sid,) in db.execute(
                select(models.Skill.skill_id).where(models.Skill.skill_id.in_(patch.skills))
            ).all()]
            for sid in valid_ids:
                db.add(models.JobSkill(job_id=job.job_id, skill_id=sid, required=True))
        changed = True

    if changed:
        composed = _compose_job_text(db, job)
        job.job_embedding_vector = json.dumps(embedding.get_embedding(composed))

    db.commit()
    db.refresh(job)
    return job

@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
):
    job = db.get(models.CompanyJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.company_id != current.user_id:
        raise HTTPException(403, "You can only delete your own company's job")
    db.delete(job)
    db.commit()

@router.get("/my_jobs", response_model=schemas.PageJob)
def list_my_jobs(
    db: Session = Depends(get_db),
    current: models.User = Depends(auth.get_current_user),
    company_id: int = Query(..., description="company/user id to filter by"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    if current.user_id != company_id:
        raise HTTPException(403, "You can only view your own company's jobs")
    stmt = select(models.CompanyJob).where(models.CompanyJob.company_id == company_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.execute(
        stmt.order_by(models.CompanyJob.job_id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
    ).scalars().all()
    return schemas.PageJob(
        meta=schemas.PageMeta(page=page, per_page=per_page, total=total or 0),
        items=items,
    )
